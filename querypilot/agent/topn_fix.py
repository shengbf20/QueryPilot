"""Stabilize branch Top-N SQL that groups by org_id then projects org_name."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_DIALECT = "duckdb"


def fix_org_topn_sql(sql: str) -> str:
    """If final SELECT is org_name + metric from org_id grain with LIMIT, re-aggregate by org_name."""
    if not sql or "limit" not in sql.lower() or "org_name" not in sql.lower():
        return sql
    try:
        tree = sqlglot.parse_one(sql.strip().rstrip(";"), read=_DIALECT)
    except Exception:  # noqa: BLE001
        return sql
    if not isinstance(tree, exp.Select):
        return sql
    if tree.args.get("limit") is None:
        return sql

    # Already groups by org_name in the outermost select
    group = tree.args.get("group")
    if group is not None:
        gsql = group.sql(dialect=_DIALECT).lower()
        if "org_name" in gsql:
            return sql

    # Pattern: SELECT b.org_name, o.metric FROM ... JOIN dim_branch ... ORDER BY metric LIMIT n
    # without GROUP BY org_name — wrap to aggregate duplicate names.
    projections = tree.expressions
    if len(projections) != 2:
        return sql
    aliases = []
    for expr in projections:
        if isinstance(expr, exp.Alias) and expr.alias:
            aliases.append(expr.alias)
        elif isinstance(expr, exp.Column):
            aliases.append(expr.name)
        else:
            return sql
    if "org_name" not in {a.lower() for a in aliases}:
        return sql

    metric_alias = aliases[1] if aliases[0].lower() == "org_name" else aliases[0]
    org_alias = "org_name"
    lim = tree.args.get("limit")
    limit_n = lim.expression.sql(dialect=_DIALECT) if lim is not None else "5"
    # Strip LIMIT/ORDER from inner
    inner = tree.copy()
    inner.set("limit", None)
    inner.set("order", None)
    inner_sql = inner.sql(dialect=_DIALECT)
    wrapped = (
        f"SELECT {org_alias}, SUM({metric_alias}) AS {metric_alias} "
        f"FROM ({inner_sql}) AS _org_topn "
        f"GROUP BY {org_alias} "
        f"ORDER BY {metric_alias} DESC, {org_alias} "
        f"LIMIT {limit_n}"
    )
    try:
        sqlglot.parse_one(wrapped, read=_DIALECT)
    except Exception:  # noqa: BLE001
        return sql
    return wrapped
