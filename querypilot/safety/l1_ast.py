"""L1 static AST safety fence (sqlglot): readonly / table allowlist / column fuzzy fix."""

from __future__ import annotations

import difflib
from collections.abc import Mapping

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.metadata_engine.loader import EXPECTED_TABLES, load_all_tables
from querypilot.safety.models import ColumnFix, GuardViolation, L1GuardResult

_FORBIDDEN_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Merge,
    exp.Command,
    exp.Copy,
    exp.Grant,
    exp.Revoke,
    exp.TruncateTable,
    exp.Replace,
    exp.Attach,
    exp.Detach,
)

_DIALECT = "duckdb"


def build_column_catalog(
    metadata: MetadataBundle | Mapping[str, set[str]] | None = None,
) -> dict[str, set[str]]:
    """table -> column names from metadata (or a prebuilt mapping)."""
    if metadata is None:
        tables = load_all_tables()
        return {name: set(meta.column_names) for name, meta in tables.items()}
    if isinstance(metadata, MetadataBundle):
        return {name: set(meta.column_names) for name, meta in metadata.tables.items()}
    return {name: set(cols) for name, cols in metadata.items()}


def guard_sql(
    sql: str,
    *,
    metadata: MetadataBundle | Mapping[str, set[str]] | None = None,
    allowed_tables: set[str] | list[str] | None = None,
    auto_fix_columns: bool = True,
    min_similarity: float = 0.78,
) -> L1GuardResult:
    """Validate and optionally rewrite SQL at the AST level.

    - Blocks non-readonly statements and unauthorized physical tables.
    - Optionally fuzzy-fixes unknown column names against the catalog.
    """
    original = sql
    normalized = sql.strip().rstrip(";").strip()
    if not normalized:
        return L1GuardResult(
            ok=False,
            sql=original,
            original_sql=original,
            violations=[GuardViolation("empty_sql", "Empty SQL")],
        )

    catalog = build_column_catalog(metadata)
    allow = set(allowed_tables) if allowed_tables is not None else set(catalog.keys()) or set(
        EXPECTED_TABLES
    )

    try:
        expressions = sqlglot.parse(normalized, read=_DIALECT)
    except ParseError as exc:
        return L1GuardResult(
            ok=False,
            sql=original,
            original_sql=original,
            violations=[GuardViolation("parse_error", f"SQL parse failed: {exc}")],
        )

    expressions = [e for e in expressions if e is not None]
    if not expressions:
        return L1GuardResult(
            ok=False,
            sql=original,
            original_sql=original,
            violations=[GuardViolation("parse_error", "SQL parse produced no expression")],
        )
    if len(expressions) > 1:
        return L1GuardResult(
            ok=False,
            sql=original,
            original_sql=original,
            violations=[
                GuardViolation("multiple_statements", "Only a single SQL statement is allowed")
            ],
        )

    tree = expressions[0]
    violations: list[GuardViolation] = []
    fixes: list[ColumnFix] = []

    for node_type in _FORBIDDEN_TYPES:
        hit = tree.find(node_type)
        if hit is not None:
            violations.append(
                GuardViolation(
                    "dangerous_op",
                    f"Forbidden operation: {node_type.__name__}",
                )
            )
            break
    else:
        if not isinstance(tree, (exp.Select, exp.Union)) and tree.find(exp.Select) is None:
            violations.append(
                GuardViolation(
                    "dangerous_op",
                    f"Only SELECT/WITH queries are allowed, got {type(tree).__name__}",
                )
            )

    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    physical_tables = _collect_physical_tables(tree, cte_names)

    for table in sorted(physical_tables):
        if table not in allow:
            violations.append(
                GuardViolation(
                    "unauthorized_table",
                    f"Table not allowed: {table}",
                )
            )

    if not any(v.code == "dangerous_op" for v in violations):
        if auto_fix_columns:
            fixes.extend(
                _fix_columns_scoped(
                    tree,
                    cte_names,
                    catalog,
                    allow,
                    min_similarity,
                )
            )
        for _col, _table_hint, message in _unknown_columns_scoped(
            tree,
            cte_names,
            catalog,
            allow,
        ):
            violations.append(GuardViolation("unknown_column", message))

    if violations:
        return L1GuardResult(
            ok=False,
            sql=original,
            original_sql=original,
            violations=violations,
            fixes=fixes,
        )

    rewritten = tree.sql(dialect=_DIALECT)
    return L1GuardResult(
        ok=True,
        sql=rewritten,
        original_sql=original,
        violations=[],
        fixes=fixes,
    )


def _collect_physical_tables(tree: exp.Expression, cte_names: set[str]) -> set[str]:
    """Physical base tables referenced anywhere (for allowlist)."""
    physical: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name
        if name and name not in cte_names:
            physical.add(name)
    return physical


def _enclosing_select(node: exp.Expression) -> exp.Select | None:
    cur: exp.Expression | None = node
    while cur is not None:
        if isinstance(cur, exp.Select):
            return cur
        cur = cur.parent
    return None


def _direct_from_sources(select: exp.Select) -> list[exp.Expression]:
    """Immediate FROM/JOIN sources of a SELECT (not nested subqueries' inners)."""
    sources: list[exp.Expression] = []
    from_ = select.args.get("from_")
    if from_ is not None and from_.this is not None:
        sources.append(from_.this)
    for join in select.args.get("joins") or []:
        if join.this is not None:
            sources.append(join.this)
    return sources


def _scope_maps(
    select: exp.Select,
    cte_names: set[str],
) -> tuple[dict[str, str], set[str], set[str]]:
    """Return (alias->relation, physical tables, virtual relation names) for one SELECT."""
    alias_map: dict[str, str] = {}
    physical: set[str] = set()
    virtual: set[str] = set(cte_names)

    for cte_name in cte_names:
        alias_map[cte_name] = cte_name

    for src in _direct_from_sources(select):
        if isinstance(src, exp.Table):
            name = src.name
            if not name:
                continue
            alias = src.alias_or_name or name
            if name in cte_names:
                alias_map[alias] = name
                virtual.add(name)
                continue
            physical.add(name)
            alias_map[alias] = name
            alias_map[name] = name
        elif isinstance(src, exp.Subquery):
            alias = src.alias
            if alias:
                alias_map[alias] = alias
                virtual.add(alias)

    return alias_map, physical, virtual


def _select_projection_aliases(select: exp.Select) -> set[str]:
    """Aliases introduced by this SELECT's projection list (ORDER BY etc.)."""
    names: set[str] = set()
    for expr in select.expressions:
        if isinstance(expr, exp.Alias) and expr.alias:
            names.add(expr.alias)
    return names


def _is_select_alias_ref(column: exp.Column, select_aliases: set[str]) -> bool:
    """Unqualified reference to a projection alias (e.g. ORDER BY cust_cnt)."""
    if column.table:
        return False
    return bool(column.name) and column.name in select_aliases


def _candidate_columns(
    catalog: dict[str, set[str]],
    scope_tables: set[str],
    table_hint: str | None,
) -> set[str]:
    if table_hint and table_hint in catalog:
        return set(catalog[table_hint])
    cols: set[str] = set()
    for name in scope_tables:
        cols |= catalog.get(name, set())
    return cols


def _resolve_column_scope(
    column: exp.Column,
    cte_names: set[str],
    catalog: dict[str, set[str]],
    allow: set[str],
) -> tuple[str | None, set[str], bool]:
    """Return (resolved_table_or_None, candidate_cols, skip_catalog_check).

    ``skip_catalog_check`` is True for CTE/subquery-qualified refs and projection aliases.
    """
    select = _enclosing_select(column)
    if select is None:
        return None, set(), False

    alias_map, physical, virtual = _scope_maps(select, cte_names)
    select_aliases = _select_projection_aliases(select)
    if _is_select_alias_ref(column, select_aliases):
        return None, set(), True

    table_ref = column.table or None
    if table_ref and table_ref in virtual:
        return table_ref, set(), True
    resolved = alias_map.get(table_ref, table_ref) if table_ref else None
    if resolved in virtual:
        return resolved, set(), True

    scope_tables = physical & allow if physical else set()
    candidates = _candidate_columns(catalog, scope_tables, resolved)
    return resolved, candidates, False


def _fix_columns_scoped(
    tree: exp.Expression,
    cte_names: set[str],
    catalog: dict[str, set[str]],
    allow: set[str],
    min_similarity: float,
) -> list[ColumnFix]:
    fixes: list[ColumnFix] = []
    for column in tree.find_all(exp.Column):
        col_name = column.name
        if not col_name or col_name == "*":
            continue
        resolved, candidates, skip = _resolve_column_scope(
            column, cte_names, catalog, allow
        )
        if skip or not candidates or col_name in candidates:
            continue
        match = difflib.get_close_matches(
            col_name, sorted(candidates), n=1, cutoff=min_similarity
        )
        if not match:
            continue
        fixed = match[0]
        column.set(
            "this",
            exp.to_identifier(
                fixed, quoted=column.this.quoted if column.this else False
            ),
        )
        fixes.append(ColumnFix(original=col_name, fixed=fixed, table=resolved))
    return fixes


def _unknown_columns_scoped(
    tree: exp.Expression,
    cte_names: set[str],
    catalog: dict[str, set[str]],
    allow: set[str],
) -> list[tuple[str, str | None, str]]:
    """Return remaining unknown columns after fuzzy fixes (scope-aware)."""
    unknown: list[tuple[str, str | None, str]] = []
    for column in tree.find_all(exp.Column):
        col_name = column.name
        if not col_name or col_name == "*":
            continue
        resolved, candidates, skip = _resolve_column_scope(
            column, cte_names, catalog, allow
        )
        if skip:
            continue
        if not candidates:
            # Unqualified / empty local FROM: nothing to validate against.
            continue
        if col_name in candidates:
            continue
        where = f" (table {resolved})" if resolved else ""
        unknown.append((col_name, resolved, f"Unknown column{where}: {col_name}"))
    return unknown
