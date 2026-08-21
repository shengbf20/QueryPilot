"""Deterministic period-PnL SQL normalization (no LLM).

Rewrites ``end_aset - bgn_aset + out - in`` and the unparenthesized quirk
``end_nm+end_fc - bgn_nm + bgn_fc + out - in`` to
``end_nm+end_fc - (bgn_nm+bgn_fc) + out - in``.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

_DIALECT = "duckdb"
_ASSET_ALIAS = {"bgn_aset", "end_aset"}


def _coalesce_col(table: str | None, column: str) -> exp.Expression:
    col = exp.column(column, table=table) if table else exp.column(column)
    return exp.Coalesce(this=col, expressions=[exp.Literal.number(0)])


def _nm_plus_fc(table: str | None) -> exp.Expression:
    return exp.Add(this=_coalesce_col(table, "nm_tot_aset"), expression=_coalesce_col(table, "fc_pur_aset"))


def _gold_aset_pft(end_alias: str, bgn_alias: str, flow_alias: str | None) -> exp.Expression:
    """end_nm+end_fc - bgn_nm - bgn_fc + out - in (equivalent to minus grouped bgn)."""
    body = exp.Sub(this=_nm_plus_fc(end_alias), expression=_coalesce_col(bgn_alias, "nm_tot_aset"))
    body = exp.Sub(this=body, expression=_coalesce_col(bgn_alias, "fc_pur_aset"))
    if flow_alias:
        body = exp.Add(this=body, expression=_coalesce_col(flow_alias, "aset_out"))
        body = exp.Sub(this=body, expression=_coalesce_col(flow_alias, "aset_in"))
    return body


def _is_nm_plus_fc_expr(node: exp.Expression) -> bool:
    text = node.sql(dialect=_DIALECT).lower().replace(" ", "")
    return (
        "nm_tot_aset" in text
        and "fc_pur_aset" in text
        and "+" in text
        and "aset_in" not in text
        and "aset_out" not in text
    )


def _expand_asset_cte(cte: exp.CTE) -> bool:
    """Rewrite ``nm+fc AS bgn_aset|end_aset`` into separate nm/fc columns. Returns changed."""
    sel = cte.this
    if not isinstance(sel, exp.Select):
        return False
    new_exprs: list[exp.Expression] = []
    changed = False
    for expr in sel.expressions:
        alias = expr.alias if isinstance(expr, exp.Alias) else None
        inner = expr.this if isinstance(expr, exp.Alias) else expr
        if alias in _ASSET_ALIAS and _is_nm_plus_fc_expr(inner):
            new_exprs.append(
                exp.alias_(_coalesce_col(None, "nm_tot_aset"), "nm_tot_aset", copy=False)
            )
            new_exprs.append(
                exp.alias_(_coalesce_col(None, "fc_pur_aset"), "fc_pur_aset", copy=False)
            )
            changed = True
        else:
            new_exprs.append(expr)
    if changed:
        sel.set("expressions", new_exprs)
    return changed


def _iter_table_sources(select: exp.Select) -> list[exp.Expression]:
    sources: list[exp.Expression] = []
    from_ = select.args.get("from_")
    if from_ is not None and from_.this is not None:
        sources.append(from_.this)
    for join in select.args.get("joins") or []:
        if join.this is not None:
            sources.append(join.this)
    return sources


def _outer_alias_for_cte(select: exp.Select, cte_name: str) -> str | None:
    for src in _iter_table_sources(select):
        if isinstance(src, exp.Table) and src.name == cte_name:
            return src.alias_or_name or src.name
    return None


def _alias_by_join_name(select: exp.Select, names: set[str]) -> str | None:
    wanted = {n.lower() for n in names}
    for src in _iter_table_sources(select):
        if not isinstance(src, exp.Table):
            continue
        alias = (src.alias_or_name or src.name or "").lower()
        if alias in wanted:
            return src.alias_or_name or src.name
    return None


def _find_flow_alias(select: exp.Select) -> str | None:
    """Best-effort: CTE/subquery alias that exposes aset_in/aset_out."""
    from_ = select.args.get("from_")
    sources: list[exp.Expression] = []
    if from_ is not None and from_.this is not None:
        sources.append(from_.this)
    for join in select.args.get("joins") or []:
        if join.this is not None:
            sources.append(join.this)
    for src in sources:
        if isinstance(src, exp.Table):
            alias = src.alias_or_name or src.name
            # Heuristic names from model / gold
            if (src.name or "").lower() in {"flows", "fin", "flow", "cashflow"}:
                return alias
        elif isinstance(src, exp.Subquery) and src.alias:
            sub = src.this
            if isinstance(sub, exp.Select):
                aliases = {
                    e.alias
                    for e in sub.expressions
                    if isinstance(e, exp.Alias) and e.alias
                }
                if "aset_in" in aliases and "aset_out" in aliases:
                    return src.alias
    # Fallback: any joined table alias used with aset_in in SELECT list
    for expr in select.expressions:
        if isinstance(expr, exp.Alias) and expr.alias in {"aset_in", "aset_out"}:
            cols = list(expr.find_all(exp.Column))
            if cols and cols[0].table:
                return cols[0].table
    return None


def _compact_sql(expr: exp.Expression) -> str:
    return re.sub(r"\s+", "", expr.sql(dialect=_DIALECT).lower())


def _already_grouped_bgn(expr: exp.Expression) -> bool:
    compact = _compact_sql(expr)
    if re.search(
        r"-\(coalesce\([^)]*nm_tot_aset[^)]*\)\+coalesce\([^)]*fc_pur_aset",
        compact,
    ):
        return True
    if re.search(
        r"-coalesce\([^)]*nm_tot_aset[^)]*\)-coalesce\([^)]*fc_pur_aset",
        compact,
    ):
        return True
    return False


def _quirk_plus_bgn_fc(expr: exp.Expression) -> bool:
    compact = _compact_sql(expr)
    return bool(
        re.search(
            r"-coalesce\([^)]*nm_tot_aset[^)]*\)\+coalesce\([^)]*fc_pur_aset",
            compact,
        )
    )


def _intuitive_pnl(expr: exp.Expression) -> bool:
    """True if aset_pft should be rewritten to grouped beginning assets."""
    if _already_grouped_bgn(expr):
        return False
    if _quirk_plus_bgn_fc(expr):
        return True
    compact = _compact_sql(expr)
    has_end = "end_aset" in compact
    has_bgn = "bgn_aset" in compact
    return bool(has_end and has_bgn)


def _cte_projects_nm_fc(cte: exp.CTE) -> bool:
    sel = cte.this
    if not isinstance(sel, exp.Select):
        return False
    aliases = {
        (e.alias if isinstance(e, exp.Alias) else None)
        or (e.name if isinstance(e, exp.Column) else None)
        for e in sel.expressions
    }
    return "nm_tot_aset" in aliases and "fc_pur_aset" in aliases


def _outer_aliases_for_nm_fc_ctes(select: exp.Select, with_: exp.With) -> tuple[str | None, str | None]:
    """Map begin/end asset CTEs (nm+fc columns) to outer join aliases."""
    begin_names: set[str] = set()
    end_names: set[str] = set()
    for cte in with_.expressions:
        if not isinstance(cte, exp.CTE) or not _cte_projects_nm_fc(cte):
            continue
        name = (cte.alias_or_name or "").lower()
        if any(k in name for k in ("bgn", "begin", "start")):
            begin_names.add(cte.alias_or_name)
        elif any(k in name for k in ("end", "final")):
            end_names.add(cte.alias_or_name)
    bgn = end = None
    for name in begin_names:
        bgn = bgn or _outer_alias_for_cte(select, name)
    for name in end_names:
        end = end or _outer_alias_for_cte(select, name)
    return bgn, end


def fix_period_pnl_sql(sql: str) -> str:
    """Rewrite period-PnL SQL toward grouped ``aset_pft``. No-op if N/A."""
    if not sql or "aset_pft" not in sql.lower():
        return sql
    try:
        tree = sqlglot.parse_one(sql.strip().rstrip(";"), read=_DIALECT)
    except Exception:  # noqa: BLE001
        return sql
    if not isinstance(tree, exp.Select):
        return sql

    with_ = tree.args.get("with_")
    if with_ is None:
        return sql

    expanded = False
    for cte in list(with_.expressions):
        if isinstance(cte, exp.CTE) and _expand_asset_cte(cte):
            expanded = True

    bgn_alias = _outer_alias_for_cte(tree, "bgn_aset")
    end_alias = _outer_alias_for_cte(tree, "end_aset")
    if not bgn_alias or not end_alias:
        bgn_alias = bgn_alias or _outer_alias_for_cte(tree, "aset_bgn")
        end_alias = end_alias or _outer_alias_for_cte(tree, "aset_end")
    if not bgn_alias or not end_alias:
        alt_bgn, alt_end = _outer_aliases_for_nm_fc_ctes(tree, with_)
        bgn_alias = bgn_alias or alt_bgn
        end_alias = end_alias or alt_end
    if not bgn_alias or not end_alias:
        bgn_alias = bgn_alias or _alias_by_join_name(tree, {"aset_bgn", "bgn_aset"})
        end_alias = end_alias or _alias_by_join_name(tree, {"aset_end", "end_aset"})
    if not (bgn_alias and end_alias):
        return sql if not expanded else tree.sql(dialect=_DIALECT)

    # CTEs already expose nm/fc under begin/end aliases — still rewrite broken outer refs.
    nm_fc_ready = bool(_outer_aliases_for_nm_fc_ctes(tree, with_)[0])

    flow_alias = _find_flow_alias(tree)
    new_exprs: list[exp.Expression] = []
    touched = False
    for expr in tree.expressions:
        alias = expr.alias if isinstance(expr, exp.Alias) else None
        inner = expr.this if isinstance(expr, exp.Alias) else expr
        if alias == "bgn_aset" and (expanded or nm_fc_ready):
            new_exprs.append(exp.alias_(_nm_plus_fc(bgn_alias), "bgn_aset", copy=False))
            touched = True
        elif alias == "end_aset" and (expanded or nm_fc_ready):
            new_exprs.append(exp.alias_(_nm_plus_fc(end_alias), "end_aset", copy=False))
            touched = True
        elif alias == "aset_pft" and (expanded or nm_fc_ready or _intuitive_pnl(inner)):
            new_exprs.append(
                exp.alias_(
                    _gold_aset_pft(end_alias, bgn_alias, flow_alias),
                    "aset_pft",
                    copy=False,
                )
            )
            touched = True
        else:
            new_exprs.append(expr)

    if not touched and not expanded:
        return sql
    if touched:
        tree.set("expressions", new_exprs)
    return tree.sql(dialect=_DIALECT)
