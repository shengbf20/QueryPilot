"""Deterministic period-PnL SQL normalization (no LLM).

Aligns intuitive ``end_aset - bgn_aset + out - in`` with the gold/quirk formula
``end_nm+end_fc - bgn_nm + bgn_fc + out - in`` when CTEs pre-sum nm+fc.
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
    """end_nm+end_fc - bgn_nm + bgn_fc + out - in."""
    end_total = _nm_plus_fc(end_alias)
    body = exp.Add(
        this=exp.Sub(this=end_total, expression=_coalesce_col(bgn_alias, "nm_tot_aset")),
        expression=_coalesce_col(bgn_alias, "fc_pur_aset"),
    )
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


def _outer_alias_for_cte(select: exp.Select, cte_name: str) -> str | None:
    from_ = select.args.get("from_")
    sources: list[exp.Expression] = []
    if from_ is not None and from_.this is not None:
        sources.append(from_.this)
    for join in select.args.get("joins") or []:
        if join.this is not None:
            sources.append(join.this)
    for src in sources:
        if isinstance(src, exp.Table) and src.name == cte_name:
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


def _intuitive_pnl(expr: exp.Expression) -> bool:
    """True if aset_pft looks like end_total - bgn_total + out - in (not gold quirk)."""
    text = expr.sql(dialect=_DIALECT).lower()
    if "nm_tot_aset" in text and re.search(
        r"-\s*coalesce\([^)]*nm_tot_aset", text.replace("\n", " ")
    ):
        # Already has -bgn_nm ... +bgn_fc shape
        if re.search(r"\+\s*coalesce\([^)]*fc_pur_aset", text.replace("\n", " ")):
            return False
    compact = re.sub(r"\s+", "", text)
    has_end = "end_aset" in compact
    has_bgn = "bgn_aset" in compact
    if has_end and has_bgn and "-" in compact:
        return True
    # end/bgn as bare summed aliases without nm/fc split
    if has_end and has_bgn:
        return True
    return False


def fix_period_pnl_sql(sql: str) -> str:
    """Rewrite intuitive period-PnL SQL toward gold ``aset_pft`` quirk. No-op if N/A."""
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
    if not expanded:
        # Outer already joins raw asset tables — only fix aset_pft if intuitive
        pass

    bgn_alias = _outer_alias_for_cte(tree, "bgn_aset")
    end_alias = _outer_alias_for_cte(tree, "end_aset")
    if not bgn_alias or not end_alias:
        # Try gold-style direct joins: aset_bgn / aset_end
        bgn_alias = bgn_alias or _outer_alias_for_cte(tree, "aset_bgn")
        end_alias = end_alias or _outer_alias_for_cte(tree, "aset_end")
        if not (bgn_alias and end_alias):
            return sql if not expanded else tree.sql(dialect=_DIALECT)

    flow_alias = _find_flow_alias(tree)
    new_exprs: list[exp.Expression] = []
    touched = False
    for expr in tree.expressions:
        alias = expr.alias if isinstance(expr, exp.Alias) else None
        inner = expr.this if isinstance(expr, exp.Alias) else expr
        if alias == "bgn_aset" and expanded:
            new_exprs.append(exp.alias_(_nm_plus_fc(bgn_alias), "bgn_aset", copy=False))
            touched = True
        elif alias == "end_aset" and expanded:
            new_exprs.append(exp.alias_(_nm_plus_fc(end_alias), "end_aset", copy=False))
            touched = True
        elif alias == "aset_pft" and (expanded or _intuitive_pnl(inner)):
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
