"""删除已接入的表（保留 CSV，撤销 onboarding 流程的全部痕迹）。

ONBOARDING.md 流程的逆操作，逐项撤销：
  1. scripts/import_data.py 的 TABLES 条目（连同 add_table.py 自动登记注释行）
  2. metadata/tables/<name>.yaml
  3. metadata/join_graph.yaml：tables 块条目 + 双向涉及该表的边
  4. metadata/pruning.yaml：fact_tables 行 + domain_seed_cues 条目
  5. metadata/value_descriptors.yaml：column_refs 引用；
     code_types 条目清空后降级回 unused_code_types
  6. db/competition.duckdb DROP TABLE（--keep-db 跳过）

data_sim/ 下的 CSV 一律不动；删除后可随时按 ONBOARDING.md 重新接入。
非 add_table.py 自动登记的表（如原始赛题表）默认拒绝删除，--force 强制。

用法:
  python scripts/remove_table.py dwd_cust_risk_assess_d
  python scripts/remove_table.py <name> --dry-run   # 只看会删什么，不写盘
  python scripts/remove_table.py <name> --keep-db   # 只撤销登记，不动 DuckDB 里的表
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "import_data.py"
METADATA_DIR = ROOT / "metadata"
DB_PATH = ROOT / "db" / "competition.duckdb"

_TABLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_AUTO_MARK_FMT = "# --- {table}（scripts/add_table.py 自动登记）---"


# ---------- 1. import_data.py TABLES 条目 ----------


def entry_is_auto_registered(script_text: str, table: str) -> bool:
    """条目是否由 add_table.py 自动登记（带标记注释行）。"""
    return _AUTO_MARK_FMT.format(table=table) in script_text


def import_entry_exists(script_text: str, table: str) -> bool:
    return re.search(rf'^    "{re.escape(table)}": \{{', script_text, re.M) is not None


def remove_import_entry(script_path: Path, table: str) -> bool:
    """从 TABLES 字典删除条目（连同自动登记注释行）；返回是否删除。

    删除后做 ast 语法校验（与 add_table.insert_entry 对称）。
    """
    import ast

    lines = script_path.read_text(encoding="utf-8").splitlines(keepends=True)
    entry_re = re.compile(rf'^    "{re.escape(table)}": \{{\s*$')
    start = next(
        (i for i, ln in enumerate(lines) if entry_re.match(ln.rstrip("\r\n"))), None
    )
    if start is None:
        return False
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].rstrip() == "    },"),
        None,
    )
    if end is None:
        raise ValueError(f"TABLES 条目 {table} 未找到收口 }}，（{script_path}）")
    begin = start
    # 条目上方紧邻的自动登记注释行一并删除（手写注释不动，交 --force 流程人工判断）
    if start > 0 and lines[start - 1].lstrip().startswith(f"# --- {table}"):
        begin = start - 1
    del lines[begin : end + 1]
    script_path.write_text("".join(lines), encoding="utf-8")
    ast.parse(script_path.read_text(encoding="utf-8"))
    return True


# ---------- 2. metadata/tables/<name>.yaml ----------


def delete_table_yaml(metadata_dir: Path, table: str) -> bool:
    path = metadata_dir / "tables" / f"{table}.yaml"
    if not path.exists():
        return False
    path.unlink()
    return True


# ---------- 3. join_graph.yaml：tables 条目 + 边 ----------


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8")


def _header_index(lines: list[str], header: str) -> int | None:
    for i, ln in enumerate(lines):
        if ln.rstrip("\r\n") == header:
            return i
    return None


def remove_join_graph_entries(path: Path, table: str) -> tuple[bool, int]:
    """删 tables 块条目 + 所有 from/to 涉及该表的边。返回 (表条目已删, 边数)。"""
    lines = _read_lines(path)
    removed_entry = False
    removed_edges = 0

    # tables 块条目：`  <table>:` 起，到下一个同级键 / 顶层键为止
    target = f"  {table}:"
    idx = _header_index(lines, target)
    if idx is not None:
        end = idx + 1
        while end < len(lines):
            ln = lines[end]
            if ln.strip() == "" or re.match(r"^(\S|  \S)", ln):
                break  # 空行 / 顶层键 / 同级表键
            end += 1
        del lines[idx:end]
        removed_entry = True

    # 边：`  - id:` 条目块，from/to 命中即整块删除
    edges_idx = _header_index(lines, "edges:")
    if edges_idx is not None:
        ranges: list[tuple[int, int]] = []
        i = edges_idx + 1
        while i < len(lines):
            ln = lines[i]
            if re.match(r"^\S", ln):
                break  # 下一个顶层键
            if ln.startswith("  - "):
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if nxt.strip() == "" or re.match(r"^(\S|  (- |#))", nxt):
                        break  # 空行 / 顶层键 / 下一条边 / 2 空格注释
                    j += 1
                block = "".join(lines[i:j])
                if re.search(
                    rf"^    (from|to): {re.escape(table)}\s*$", block, re.M
                ):
                    ranges.append((i, j))
                i = j
                continue
            i += 1  # 块间注释 / 空行
        for i, j in reversed(ranges):
            del lines[i:j]
        removed_edges = len(ranges)

    if removed_entry or removed_edges:
        _write_lines(path, lines)
    return removed_entry, removed_edges


# ---------- 4. pruning.yaml：fact_tables + domain_seed_cues ----------


def _block_range(lines: list[str], header_idx: int) -> tuple[int, int]:
    """顶层块的属性行范围（到下一个非注释顶层行为止，不含尾部空行）。"""
    end = header_idx + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() == "":
            break
        if not ln.startswith((" ", "\t")) and not ln.lstrip().startswith("#"):
            break
        if ln.lstrip().startswith("#") and not ln.startswith((" ", "\t")):
            break
        end += 1
    return header_idx + 1, end


def remove_pruning_entries(path: Path, table: str) -> tuple[bool, bool]:
    """删 fact_tables 行 + domain_seed_cues 条目。返回 (fact 行已删, cue 条目已删)。"""
    lines = _read_lines(path)
    removed_fact = False
    removed_cues = False

    fact_idx = _header_index(lines, "fact_tables:")
    if fact_idx is not None:
        start, end = _block_range(lines, fact_idx)
        fact_line = f"  - {table}"
        kept = [ln for ln in lines[start:end] if ln.rstrip("\r\n") != fact_line]
        if len(kept) != len(lines[start:end]):
            lines[start:end] = kept
            removed_fact = True

    cues_idx = _header_index(lines, "domain_seed_cues:")
    if cues_idx is not None:
        ranges: list[tuple[int, int]] = []
        i = cues_idx + 1
        while i < len(lines):
            ln = lines[i]
            if re.match(r"^\S", ln):
                break
            if ln.startswith("  - "):
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if nxt.strip() == "" or re.match(r"^(\S|  - )", nxt):
                        break
                    j += 1
                block = "".join(lines[i:j])
                if re.search(
                    rf"^    table: {re.escape(table)}\s*$", block, re.M
                ):
                    ranges.append((i, j))
                i = j
                continue
            i += 1
        for i, j in reversed(ranges):
            del lines[i:j]
        removed_cues = bool(ranges)

    if removed_fact or removed_cues:
        _write_lines(path, lines)
    return removed_fact, removed_cues


# ---------- 5. value_descriptors.yaml：column_refs + 降级 ----------


def remove_value_descriptor_refs(path: Path, table: str) -> list[str]:
    """删 code_types.*.column_refs 中指向该表的引用，返回被降级的 code_type_id 列表。

    code_types 条目的引用被清空后，整条降级回 unused_code_types（label 保留），
    与 register._promote_unused_code_type 互为逆操作。
    """
    lines = _read_lines(path)
    ct_idx = _header_index(lines, "code_types:")
    if ct_idx is None:
        return []

    out: list[str] = list(lines[: ct_idx + 1])  # 保留 code_types: 头及之前的注释
    demoted: list[tuple[str, str]] = []  # (code_type_id, label)
    i = ct_idx + 1
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln.strip() == "" or re.match(r"^\S", ln):
            # 空行 / 离开 code_types 块：原样保留剩余
            out.extend(lines[i:])
            i = n
            break
        m = re.match(r'^  "(?P<id>[^"]+)":\s*$', ln.rstrip("\r\n"))
        if not m:
            out.append(ln)
            i += 1
            continue
        # 条目块：到下一个 2 空格键 / 顶层键 / 空行为止
        j = i + 1
        while j < n:
            nxt = lines[j]
            if nxt.strip() == "" or re.match(r"^(\S|  \S)", nxt):
                break
            j += 1
        block = lines[i:j]
        kept: list[str] = []
        k = 0
        while k < len(block):
            bl = block[k]
            if bl.rstrip("\r\n") == f"      - table: {table}":
                k += 1
                while k < len(block) and block[k].rstrip("\r\n").startswith("        "):
                    k += 1
                continue
            kept.append(bl)
            k += 1
        if len(kept) == len(block):
            out.extend(block)  # 本条目无该表引用
        elif any(b.lstrip().startswith("- table:") for b in kept):
            out.extend(kept)  # 还有别的表引用，保留条目
        else:
            label = ""
            for b in block:
                if b.lstrip().startswith("label:"):
                    label = b.split(":", 1)[1].strip()
                    break
            demoted.append((m["id"], label))
        i = j

    if demoted:
        out = _demote_to_unused(out, demoted)
    _write_lines(path, out)
    return [ctid for ctid, _ in demoted]


def _demote_to_unused(lines: list[str], demoted: list[tuple[str, str]]) -> list[str]:
    """在 unused_code_types 块尾插入降级行；块不存在时新建。"""
    entries = [f'  "{ctid}": {label}\n' for ctid, label in demoted]
    unused_idx = _header_index(lines, "unused_code_types:")
    if unused_idx is None:
        # 找 code_types 块后的首个空行，插一个新块
        insert_at = len(lines)
        for i in range(unused_idx_or_code_types_end(lines), len(lines)):
            if lines[i].strip() == "":
                insert_at = i
                break
        block = ["\n", "unused_code_types:\n", *entries]
        return lines[:insert_at] + block + lines[insert_at:]
    start, end = _block_range(lines, unused_idx)
    return lines[:end] + entries + lines[end:]


def unused_idx_or_code_types_end(lines: list[str]) -> int:
    idx = _header_index(lines, "code_types:")
    return (idx + 1) if idx is not None else 0


# ---------- 6. DuckDB DROP TABLE ----------


def db_table_exists(db_path: Path, table: str) -> bool:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return (
            con.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
                [table],
            ).fetchone()[0]
            > 0
        )
    finally:
        con.close()


def drop_db_table(db_path: Path, table: str) -> bool:
    """DROP 真实库中的表（不动其他表）。返回是否存在并已删除。"""
    import duckdb

    con = duckdb.connect(str(db_path))
    try:
        exists = (
            con.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
                [table],
            ).fetchone()[0]
            > 0
        )
        if not exists:
            return False
        con.execute(f'DROP TABLE "{table}"')
        return True
    finally:
        con.close()


# ---------- 反向核验（A6 的逆检查） ----------


def verify_removal(metadata_dir: Path, table: str) -> list[str]:
    """删除后不应残留任何登记痕迹；返回残留问题列表（空 = 干净）。"""
    issues: list[str] = []
    from querypilot.metadata_engine.join_graph_loader import load_join_graph
    from querypilot.metadata_engine.loader import load_all_tables
    from querypilot.metadata_engine.pruning_config import load_pruning_config
    from querypilot.metadata_engine.value_descriptors import load_value_descriptor_config

    if table in load_all_tables(metadata_dir / "tables"):
        issues.append(f"loader 仍发现 {table}.yaml")
    graph = load_join_graph(metadata_dir / "join_graph.yaml")
    if table in graph.tables:
        issues.append("join_graph tables 块仍含该表")
    if any(e.from_table == table or e.to_table == table for e in graph.edges.values()):
        issues.append("join_graph 仍有边引用该表")
    values = load_value_descriptor_config(metadata_dir / "value_descriptors.yaml")
    for ctid, ct in values.code_types.items():
        if any(ref.table == table for ref in ct.column_refs):
            issues.append(f"value_descriptors code_types.{ctid} 仍引用该表")
    config = load_pruning_config(metadata_dir / "pruning.yaml")
    if table in config.fact_tables:
        issues.append("pruning fact_tables 仍含该表")
    if any(t == table for _, t in config.domain_seed_cues):
        issues.append("pruning domain_seed_cues 仍含该表")
    return issues


# ---------- CLI ----------


def _plan(script_text: str, metadata_dir: Path, table: str) -> list[tuple[str, bool]]:
    """各删除目标的现状清单（dry-run 与执行前提示共用）。"""
    items: list[tuple[str, bool]] = [
        ("import_data.py TABLES 条目", import_entry_exists(script_text, table)),
        ("metadata/tables/%s.yaml" % table, (metadata_dir / "tables" / f"{table}.yaml").exists()),
    ]
    jg = (metadata_dir / "join_graph.yaml").read_text(encoding="utf-8")
    items.append(
        (
            "join_graph tables 条目 + 边",
            f"\n  {table}:" in jg or re.search(rf"^    (from|to): {table}$", jg, re.M) is not None,
        )
    )
    pruning = (metadata_dir / "pruning.yaml").read_text(encoding="utf-8")
    items.append(
        (
            "pruning fact_tables / domain_seed_cues",
            f"\n  - {table}\n" in pruning or f"    table: {table}" in pruning,
        )
    )
    vd = (metadata_dir / "value_descriptors.yaml").read_text(encoding="utf-8")
    items.append(("value_descriptors column_refs", f"- table: {table}" in vd))
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="删除已接入的表：撤销 onboarding 全部登记（CSV 保留）"
    )
    parser.add_argument("table", help="表名（如 dwd_cust_risk_assess_d）")
    parser.add_argument("--dry-run", action="store_true", help="只列出会删什么，不写盘")
    parser.add_argument("--keep-db", action="store_true", help="不动 DuckDB 里的表（只撤销元数据登记）")
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许删除非 add_table.py 自动登记的表（如手写登记的原始赛题表，慎用）",
    )
    args = parser.parse_args(argv)

    table = args.table.strip()
    if not _TABLE_RE.match(table):
        print(f"错误: 非法表名: {table}")
        return 1

    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    if import_entry_exists(script_text, table) and not entry_is_auto_registered(
        script_text, table
    ):
        if not args.force:
            print(
                f"拒绝: {table} 不是 add_table.py 自动登记的表"
                "（可能是原始赛题表，删除会破坏既有查询）。确需删除请加 --force。"
            )
            return 1
        print(f"警告: {table} 非自动登记表，按 --force 强制删除。")

    plan = _plan(script_text, METADATA_DIR, table)
    db_present = False
    try:
        db_present = DB_PATH.exists() and db_table_exists(DB_PATH, table)
    except Exception as exc:
        print(f"警告: 无法检查 DuckDB（可能被 serve 占用）: {exc}")

    if not any(found for _, found in plan) and not db_present:
        print(f"未发现 {table} 的任何登记痕迹（import/metadata/DB 均无）。")
        return 1

    print(f"将删除 {table} 的以下登记（CSV 文件不动）:")
    for name, found in plan:
        print(f"  [{'x' if found else ' '}] {name}")
    print(f"  [{'x' if db_present else ' '}] DuckDB 表（--keep-db 可跳过）")
    if args.dry_run:
        print("dry-run：未做任何修改。")
        return 0

    if remove_import_entry(SCRIPT_PATH, table):
        print(f"✓ import_data.py TABLES 已移除 {table}")
    if delete_table_yaml(METADATA_DIR, table):
        print(f"✓ metadata/tables/{table}.yaml 已删除")
    entry_removed, edges_removed = remove_join_graph_entries(
        METADATA_DIR / "join_graph.yaml", table
    )
    if entry_removed or edges_removed:
        print(f"✓ join_graph 已移除表条目{'' if entry_removed else '（无）'}"
              f" + {edges_removed} 条边")
    fact_removed, cues_removed = remove_pruning_entries(
        METADATA_DIR / "pruning.yaml", table
    )
    if fact_removed or cues_removed:
        print(f"✓ pruning 已移除 fact_tables 行{'' if fact_removed else '（无）'}"
              f" + 触发词条目{'' if cues_removed else '（无）'}")
    demoted = remove_value_descriptor_refs(
        METADATA_DIR / "value_descriptors.yaml", table
    )
    if demoted:
        print(f"✓ value_descriptors 引用已移除；{demoted} 引用清空，已降级回 unused_code_types")

    dropped = False
    if not args.keep_db and DB_PATH.exists():
        try:
            dropped = drop_db_table(DB_PATH, table)
        except Exception as exc:
            print(f"✗ DuckDB 删表失败（表可能被 serve 占用，关掉后重跑或用 --keep-db）: {exc}")
            return 1
        if dropped:
            print(f"✓ DuckDB 已 DROP TABLE {table}")

    issues = verify_removal(METADATA_DIR, table)
    if issues:
        print("✗ 反向核验发现残留:")
        for issue in issues:
            print(f"    - {issue}")
        return 1
    print("✓ 反向核验通过：元数据中已无该表任何痕迹。")

    csv_hint = ""
    for cand in sorted((ROOT / "data_sim").glob(f"{table}*.csv")):
        csv_hint = str(cand.relative_to(ROOT))
    if csv_hint:
        print(f"\nCSV 已保留: {csv_hint}（重新接入: ONBOARDING.md ② 起，或 add_table.py）")
    if not dropped and db_present and args.keep_db:
        print("DuckDB 表仍在（--keep-db）；全量重建（import_data.py）时不会再次导入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())