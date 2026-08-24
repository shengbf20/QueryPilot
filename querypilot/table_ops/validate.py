"""A7/A8 注册后校验与回归编排（logs/08 §三）。

三层防线，全部复用既有机制，零新增维护点：
  1. validate_registration —— A7：元数据静态校验（表 YAML / join_graph / DB 列对齐）
  2. smoke_join_check    —— 新表每条 join 边在 DB 里真实可连（行数 > 0）
  3. prune_smoke         —— 新表冒烟问句经剪枝命中新表（确定性，零 LLM）
  4. baseline_regression —— 旧集回归（subprocess 调 scripts/baseline_eval.py，需 LLM）
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from querypilot.config import get_settings, ROOT_DIR
from querypilot.metadata_engine.bundle import load_metadata_uncached
from querypilot.metadata_engine.join_graph_loader import load_join_graph
from querypilot.metadata_engine.loader import load_all_tables
from querypilot.metadata_engine.models import TableMeta
from querypilot.metadata_engine.validator import ValidationResult
from querypilot.metadata_engine.validator import validate_table
from querypilot.metadata_engine.join_graph_validator import (
    _validate_edges,
    _validate_paths,
    _validate_tables,
)
from querypilot.metadata_engine.value_descriptors import load_value_descriptor_config


@dataclass
class RegressionCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class RegressionReport:
    """onboarding 回归报告（A7 校验 + A8 冒烟）。"""

    table: str
    checks: list[RegressionCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failed(self) -> list[RegressionCheck]:
        return [c for c in self.checks if not c.ok]

    def report(self) -> str:
        lines = [f"表 {self.table} onboarding 回归报告", "=" * 60]
        for c in self.checks:
            mark = "✓" if c.ok else "✗"
            detail = f"  {c.detail}" if c.detail else ""
            lines.append(f"  {mark} {c.name}{detail}")
        lines.append("结论: " + ("回归通过" if self.ok else f"{len(self.failed)} 项失败"))
        return "\n".join(lines)


# ---------- A7 元数据静态校验 ----------


def _validate_metadata_dir(metadata_dir: Path, table: str) -> ValidationResult:
    """对目标目录跑表级 + join_graph 校验（复用既有子校验器，支持自定义路径）。"""
    tables = load_all_tables(metadata_dir / "tables")
    graph = load_join_graph(metadata_dir / "join_graph.yaml")
    value_config = load_value_descriptor_config(metadata_dir / "value_descriptors.yaml")

    result = ValidationResult()
    for meta in tables.values():
        validate_table(meta, result, known_tables=set(tables))
    _validate_tables(graph, tables, result)
    _validate_edges(graph, tables, value_config, result)
    _validate_paths(graph, result)
    return result


def _check_db_columns(
    meta: TableMeta,
    con: duckdb.DuckDBPyConnection,
    result: ValidationResult,
) -> None:
    """表 YAML 列与 DB information_schema 对齐（原 validator 的 DB 检查等价实现）。"""
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?",
        [meta.table],
    ).fetchall()
    if not rows:
        result.add_error(f"{meta.table}: not found in database")
        return
    db_types = {name: dtype for name, dtype in rows}
    for col in meta.columns:
        if col.name not in db_types:
            result.add_error(f"{meta.table}.{col.name}: in YAML but missing in DB")
        elif col.type.upper() != db_types[col.name].upper():
            result.add_warning(
                f"{meta.table}.{col.name}: YAML type {col.type} != DB type {db_types[col.name]}"
            )
    extra = set(db_types) - {c.name for c in meta.columns}
    for name in sorted(extra):
        result.add_warning(f"{meta.table}.{name}: in DB but not described in YAML")


# ---------- A8 冒烟：join 边连通性 ----------


def _edge_join_count(edge: Any, con: duckdb.DuckDBPyConnection) -> int:
    clauses = [
        f't0."{left}" = t1."{right}"' for left, right in edge.join.items()
    ]
    for key, value in edge.filter.items():
        clauses.append(f't1."{key}" = ?')
    sql = (
        f'SELECT COUNT(*) FROM "{edge.from_table}" t0 '
        f'JOIN "{edge.to_table}" t1 ON {" AND ".join(clauses)}'
    )
    params = [str(v) for v in edge.filter.values()]
    return con.execute(sql, params).fetchone()[0]


def smoke_join_check(
    table: str,
    *,
    metadata_dir: Path | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> list[tuple[Any, int]]:
    """新表每条 join 边在 DB 里的连通行数（0 = 边失效）。"""
    from querypilot.db import get_connection

    metadata_dir = metadata_dir or get_settings().metadata_dir
    graph = load_join_graph(metadata_dir / "join_graph.yaml")
    own_con = con is None
    con = con or get_connection(read_only=True)
    try:
        results = []
        for edge in graph.edges.values():
            if table in (edge.from_table, edge.to_table):
                results.append((edge, _edge_join_count(edge, con)))
        return results
    finally:
        if own_con:
            con.close()


# ---------- A8 冒烟：剪枝命中 ----------


def prune_smoke(
    table: str,
    questions: list[str],
    *,
    metadata_dir: Path | None = None,
) -> dict[str, bool]:
    """每个冒烟问句剪枝后应包含新表（确定性，零 LLM）。"""
    from querypilot.metadata_engine.pruning_config import load_pruning_config
    from querypilot.metadata_engine.schema_pruner import SchemaPruner

    metadata_dir = metadata_dir or get_settings().metadata_dir
    bundle = load_metadata_uncached(
        tables_dir=metadata_dir / "tables",
        join_graph_path=metadata_dir / "join_graph.yaml",
        value_config_path=metadata_dir / "value_descriptors.yaml",
        load_db_codes=False,
    )
    # 剪枝配置也要用副本的：新表的 cues/fact_tables 登记在副本 pruning.yaml 里
    pruner = SchemaPruner(bundle, pruning_config=load_pruning_config(metadata_dir / "pruning.yaml"))
    return {q: table in pruner.prune(q).tables for q in questions}


# ---------- A8 旧集回归（subprocess 编排） ----------


def baseline_regression(
    *,
    limit: int | None = None,
    dry_run: bool = False,
    stem: str | None = None,
    timeout: int = 1800,
) -> tuple[bool, str]:
    """调用 scripts/baseline_eval.py 做旧集回归。

    dry_run=True 走 --dry-run-summary（不调 LLM，验证编排链路）；
    完整回归需 DEEPSEEK_API_KEY，返回 (ok, 输出文本)。
    """
    cmd = [sys.executable, str(ROOT_DIR / "scripts" / "baseline_eval.py")]
    if dry_run:
        cmd.append("--dry-run-summary")
    if limit is not None:
        cmd += ["--limit", str(limit)]
    if stem:
        cmd += ["--stem", stem]
    proc = subprocess.run(
        cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output


# ---------- 编排入口 ----------


def run_onboarding_regression(
    table: str,
    *,
    smoke_questions: list[str] | None = None,
    metadata_dir: Path | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> RegressionReport:
    """A7 + A8 编排：静态校验 → join 连通 → 剪枝冒烟。旧集回归单独调 baseline_regression。"""
    from querypilot.db import get_connection

    metadata_dir = metadata_dir or get_settings().metadata_dir
    report = RegressionReport(table=table)

    # A7：静态校验
    static = _validate_metadata_dir(metadata_dir, table)
    report.checks.append(
        RegressionCheck("A7 元数据静态校验", static.ok, "; ".join(static.errors[:3]))
    )

    own_con = con is None
    con = con or get_connection(read_only=True)
    try:
        # A7 补充：表 YAML ↔ DB 列对齐
        tables = load_all_tables(metadata_dir / "tables")
        meta = tables.get(table)
        if meta is None:
            report.checks.append(RegressionCheck("表 YAML 存在", False, f"{table} 未注册"))
            return report
        db_check = ValidationResult()
        _check_db_columns(meta, con, db_check)
        report.checks.append(
            RegressionCheck("表 YAML ↔ DB 列对齐", db_check.ok, "; ".join(db_check.errors[:3]))
        )

        # A8：join 边连通
        edges = smoke_join_check(table, metadata_dir=metadata_dir, con=con)
        if not edges:
            report.checks.append(RegressionCheck("join 边连通", False, "新表没有任何 join 边"))
        else:
            dead = [e.id for e, n in edges if n == 0]
            report.checks.append(
                RegressionCheck(
                    f"join 边连通（{len(edges)} 条）", not dead, f"失效边: {dead}" if dead else ""
                )
            )
    finally:
        if own_con:
            con.close()

    # A8：剪枝冒烟
    if smoke_questions:
        hits = prune_smoke(table, smoke_questions, metadata_dir=metadata_dir)
        missed = [q for q, hit in hits.items() if not hit]
        report.checks.append(
            RegressionCheck(
                f"剪枝冒烟（{len(smoke_questions)} 问）",
                not missed,
                f"未命中: {missed}" if missed else "",
            )
        )

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m querypilot.table_ops.validate",
        description="新表 onboarding 回归（A7 校验 + A8 冒烟）",
    )
    parser.add_argument("table", help="表名")
    parser.add_argument(
        "--question", action="append", default=None, help="剪枝冒烟问句（可多次）"
    )
    parser.add_argument(
        "--baseline-dry-run", action="store_true", help="附带跑旧集回归 dry-run"
    )
    args = parser.parse_args()

    report = run_onboarding_regression(args.table, smoke_questions=args.question)
    print(report.report())
    if args.baseline_dry_run:
        ok, output = baseline_regression(dry_run=True)
        print(f"\n旧集回归 dry-run: {'OK' if ok else 'FAIL'}")
        if not ok:
            print(output)
    sys.exit(0 if report.ok else 1)
