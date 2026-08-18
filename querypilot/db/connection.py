"""DuckDB connection helpers: connect / execute / explain."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import duckdb

from querypilot.config import get_settings


@dataclass(frozen=True)
class QueryResult:
    """Tabular result from a successful SQL execution."""

    columns: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int

    def to_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]


@dataclass(frozen=True)
class ExplainResult:
    """Outcome of an EXPLAIN dry-run (L2 safety fence input)."""

    ok: bool
    error: str | None = None
    plan_rows: tuple[tuple[Any, ...], ...] | None = None

    @property
    def error_message(self) -> str:
        return self.error or ""


def get_connection(
    db_path: Path | str | None = None,
    *,
    read_only: bool = True,
) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection to the competition database (or a custom path)."""
    path = Path(db_path) if db_path is not None else get_settings().db_path
    if not path.exists():
        raise FileNotFoundError(
            f"Database not found: {path}. Run `python scripts/import_data.py` first."
        )
    return duckdb.connect(str(path), read_only=read_only)


@contextmanager
def connection(
    db_path: Path | str | None = None,
    *,
    read_only: bool = True,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Context-managed DuckDB connection that always closes."""
    con = get_connection(db_path, read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def normalize_sql(sql: str) -> str:
    """Strip whitespace and a single trailing semicolon."""
    return sql.strip().rstrip(";").strip()


def execute(
    sql: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    db_path: Path | str | None = None,
    read_only: bool = True,
    max_rows: int | None = 1000,
    params: Sequence[Any] | None = None,
) -> QueryResult:
    """Execute SQL and return columns + rows.

    If ``con`` is omitted, opens a short-lived connection (closed afterwards).
    ``max_rows`` truncates the fetched result (``None`` = no limit).
    """

    def _run(active: duckdb.DuckDBPyConnection) -> QueryResult:
        relation = (
            active.execute(normalize_sql(sql), params)
            if params is not None
            else active.execute(normalize_sql(sql))
        )
        columns = [desc[0] for desc in relation.description] if relation.description else []
        if max_rows is None:
            rows = relation.fetchall()
        else:
            rows = relation.fetchmany(max_rows)
        return QueryResult(columns=columns, rows=rows, row_count=len(rows))

    if con is not None:
        return _run(con)

    with connection(db_path, read_only=read_only) as owned:
        return _run(owned)


def explain(
    sql: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    db_path: Path | str | None = None,
    read_only: bool = True,
) -> ExplainResult:
    """Run ``EXPLAIN <sql>`` and return a structured ok/error result (no data mutation)."""

    normalized = normalize_sql(sql)
    if not normalized:
        return ExplainResult(ok=False, error="Empty SQL")

    upper = normalized.lstrip().upper()
    explain_sql = normalized if upper.startswith("EXPLAIN") else f"EXPLAIN {normalized}"

    def _run(active: duckdb.DuckDBPyConnection) -> ExplainResult:
        try:
            rows = active.execute(explain_sql).fetchall()
            return ExplainResult(ok=True, plan_rows=tuple(rows))
        except duckdb.Error as exc:
            return ExplainResult(ok=False, error=str(exc))

    if con is not None:
        return _run(con)

    with connection(db_path, read_only=read_only) as owned:
        return _run(owned)
