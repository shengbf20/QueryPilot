"""Thin tool wrappers: schema search + run_sql (fences stay inside run_sql)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
from openai import OpenAI

from querypilot.agent.pnl_fix import fix_period_pnl_sql
from querypilot.agent.prompt import compose_prune_text, load_few_shots, select_few_shots
from querypilot.agent.topn_fix import fix_org_topn_sql
from querypilot.cache.metadata_cache import get_metadata, get_pruned_schema
from querypilot.db import execute
from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.metadata_engine.schema_pruner import PrunedSchema
from querypilot.safety.l1_ast import guard_sql
from querypilot.safety.l2_explain import validate_with_l2
from querypilot.safety.result_probe import probe_result

_PREVIEW_ROWS = 8


@dataclass
class AgentWorkspace:
    """Mutable working set for one agentic.run() call."""

    question: str
    history: list[dict[str, str]] = field(default_factory=list)
    metadata: MetadataBundle | None = None
    client: OpenAI | None = None
    con: duckdb.DuckDBPyConnection | None = None
    max_rows: int = 1000
    include_values: bool = True
    constraints: list[str] = field(default_factory=list)
    sql: str = ""
    rationale: str = ""
    tables: list[str] = field(default_factory=list)
    schema_text: str = ""
    pruned: PrunedSchema | None = None
    validated: bool = False
    corrected: bool = False
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    row_count: int = 0
    probe_message: str = ""
    probe_suggestions: list[str] = field(default_factory=list)
    ran: bool = False

    def prune_text(self) -> str:
        extra = " ".join(self.constraints).strip()
        q = f"{self.question} {extra}".strip()
        return compose_prune_text(q, self.history)


def _md(ws: AgentWorkspace) -> MetadataBundle:
    if ws.metadata is None:
        ws.metadata = get_metadata(load_db_codes=ws.include_values)
    return ws.metadata


def _catalog_tables(ws: AgentWorkspace) -> list[str]:
    """All known tables. Prune is prompt-only; it is not an access control list."""
    return list(_md(ws).tables)


def _format_rows(columns: list[str], rows: list[tuple[Any, ...]], limit: int) -> str:
    if not columns:
        return "(无列)"
    header = " | ".join(columns)
    shown = rows[:limit]
    body = "\n".join(" | ".join("" if c is None else str(c) for c in row) for row in shown)
    more = f"\n… 另有 {len(rows) - limit} 行未列出" if len(rows) > limit else ""
    return f"{header}\n{body}{more}" if body else header


def refresh_schema(ws: AgentWorkspace) -> list[str]:
    """Re-prune for the current question; keep prior tables so follow-ups do not shrink."""
    md = _md(ws)
    pruned = get_pruned_schema(ws.prune_text(), md)
    ws.pruned = pruned
    prior = list(ws.tables)
    ws.tables = list(dict.fromkeys([*pruned.tables, *prior]))
    ws.schema_text = pruned.format_for_prompt(md, include_values=ws.include_values)
    return ws.tables


def build_followup(ws: AgentWorkspace) -> str:
    """Later user turn: new question plus a freshly pruned schema."""
    refresh_schema(ws)
    names = ", ".join(ws.tables) or "(无表命中)"
    return "\n".join(
        [
            f"用户问题:\n{ws.question}",
            "",
            f"本题相关表: {names}",
            "",
            ws.schema_text,
            "",
            "上一轮相关表不是权限限制。库内只读表均可 run_sql，不要反问是否放宽权限。",
        ]
    )


def build_opening(ws: AgentWorkspace, *, max_few_shots: int = 3) -> str:
    """First user turn: same prune + few-shot materials as ask(), then tool hint."""
    refresh_schema(ws)
    shots = select_few_shots(ws.question, load_few_shots(), max_few_shots=max_few_shots)
    parts = [f"用户问题:\n{ws.question}", "", ws.schema_text]
    if shots:
        parts.append("")
        parts.append("参考示例（Few-Shot）:")
        for i, ex in enumerate(shots, start=1):
            parts.append(f"\n示例 {i} 问题: {ex.question}")
            if ex.rationale:
                parts.append(f"思路: {ex.rationale}")
            parts.append(f"SQL:\n{ex.sql}")
    parts.extend(
        [
            "",
            "意图清楚时 run_sql 一条完整 SQL。跑完后必须核对结果表是否严格满足题面，不满足就改再查。",
            "不要分步探查，不要为验证某一段再跑会覆盖结果的 SQL。",
        ]
    )
    return "\n".join(parts)


def search_schema(ws: AgentWorkspace, args: dict[str, Any]) -> str:
    focus = str(args.get("query") or args.get("focus") or "").strip()
    text = f"{ws.prune_text()} {focus}".strip()
    md = _md(ws)
    pruned = get_pruned_schema(text, md)
    ws.pruned = pruned
    ws.tables = list(dict.fromkeys([*pruned.tables, *ws.tables]))
    ws.schema_text = pruned.format_for_prompt(md, include_values=ws.include_values)
    names = ", ".join(ws.tables) or "(无表命中)"
    return f"相关表: {names}\n\n{ws.schema_text}"


def run_sql(ws: AgentWorkspace, args: dict[str, Any]) -> str:
    sql = str(args.get("sql") or ws.sql).strip()
    if not sql:
        return "缺少 sql。请在 args.sql 里提供要执行的 SELECT / WITH。"
    ws.sql = fix_org_topn_sql(fix_period_pnl_sql(sql))
    ws.rationale = str(args.get("rationale") or ws.rationale)
    ws.validated = False
    md = _md(ws)
    allowed = _catalog_tables(ws)

    l1 = guard_sql(ws.sql, metadata=md, allowed_tables=allowed)
    if not l1.ok:
        detail = "; ".join(v.message for v in l1.violations) or "语句不被允许"
        return f"未执行。这条 SQL 不被允许（只读取数，不能写库）。{detail}"
    ws.sql = l1.sql

    l2 = validate_with_l2(
        ws.sql,
        question=ws.question,
        schema_context=ws.schema_text,
        metadata=md,
        allowed_tables=allowed,
        client=ws.client,
        con=ws.con,
    )
    if not l2.ok:
        err = l2.explain_error or l2.message or "数据库无法执行"
        return f"未执行。数据库无法运行这条 SQL：{err}\n当前 SQL:\n{ws.sql}"
    ws.sql = l2.sql
    ws.validated = True
    ws.corrected = bool(l2.corrected)

    try:
        data = execute(ws.sql, con=ws.con, max_rows=ws.max_rows)
    except Exception as exc:  # noqa: BLE001
        return f"执行失败：{exc}\n当前 SQL:\n{ws.sql}"

    ws.columns = list(data.columns)
    ws.rows = list(data.rows)
    ws.row_count = data.row_count
    ws.ran = True
    probe = probe_result(ws.question, data, sql=ws.sql)
    ws.probe_message = probe.message if probe.triggered else ""
    ws.probe_suggestions = list(probe.suggestions)
    preview = _format_rows(ws.columns, ws.rows, _PREVIEW_ROWS)
    extra = ""
    if probe.triggered:
        extra = f"\n提示: {probe.message}"
        if probe.suggestions:
            extra += " " + " / ".join(probe.suggestions)
    return f"执行成功，{ws.row_count} 行。\nSQL:\n{ws.sql}\n\n{preview}{extra}"


def dispatch_tool(ws: AgentWorkspace, name: str, args: dict[str, Any]) -> str:
    if name == "search_schema":
        return search_schema(ws, args)
    if name == "run_sql":
        return run_sql(ws, args)
    raise ValueError(f"not a workspace tool: {name}")
