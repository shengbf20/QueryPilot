"""DuckDB 连接辅助：connect / execute / explain。"""

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
    """成功执行 SQL 后的表格结果。"""

    columns: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int

    def to_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]


@dataclass(frozen=True)
class ExplainResult:
    """EXPLAIN 干跑结果（供 L2 安全围栏使用）。"""

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
    """打开竞赛库（或自定义路径）的 DuckDB 连接。"""
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
    """上下文管理的 DuckDB 连接，退出时必定关闭。"""
    con = get_connection(db_path, read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def normalize_sql(sql: str) -> str:
    """去掉首尾空白，并去掉末尾单个分号。"""
    return sql.strip().rstrip(";").strip()


def execute(
    sql: str, # SQL 查询语句
    *,
    con: duckdb.DuckDBPyConnection | None = None, # 可选的 DuckDB 连接
    db_path: Path | str | None = None, # 可选的数据库路径
    read_only: bool = True, # 是否只读
    max_rows: int | None = 1000, # 可选的最大行数
    params: Sequence[Any] | None = None, # 可选的参数
) -> QueryResult:
    """执行 SQL，返回列名与行数据。

    未传入 ``con`` 时会临时开连接，用完即关。
    ``max_rows`` 截断取回行数（``None`` 表示不限制）。
    """

    def _run(active: duckdb.DuckDBPyConnection) -> QueryResult:
        """执行 SQL 查询，返回列名与行数据。"""
        relation = (
            active.execute(normalize_sql(sql), params)
            if params is not None
            else active.execute(normalize_sql(sql))
        )
        columns = [desc[0] for desc in relation.description] if relation.description else [] # 获取列名
        if max_rows is None:
            rows = relation.fetchall() # 获取所有行
        else:
            rows = relation.fetchmany(max_rows) # 获取指定行数
        return QueryResult(columns=columns, rows=rows, row_count=len(rows)) # 返回结果

    if con is not None: # 如果提供了连接，则直接使用
        return _run(con)

    with connection(db_path, read_only=read_only) as owned: # 否则临时打开连接并使用
        return _run(owned)


def explain(
    sql: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    db_path: Path | str | None = None,
    read_only: bool = True,
) -> ExplainResult:
    """执行 ``EXPLAIN <sql>``，返回结构化的 ok/错误结果（不改数据）。"""

    normalized = normalize_sql(sql) # 规范化 SQL 语句
    if not normalized:
        return ExplainResult(ok=False, error="Empty SQL")

    upper = normalized.lstrip().upper() # 转换为大写
    explain_sql = normalized if upper.startswith("EXPLAIN") else f"EXPLAIN {normalized}" # 如果 SQL 以 EXPLAIN 开头，则直接使用，否则添加 EXPLAIN 前缀

    def _run(active: duckdb.DuckDBPyConnection) -> ExplainResult:
        try:
            rows = active.execute(explain_sql).fetchall() # 执行 EXPLAIN 查询并获取结果
            return ExplainResult(ok=True, plan_rows=tuple(rows))
        except duckdb.Error as exc:
            return ExplainResult(ok=False, error=str(exc)) # 如果执行失败，则返回错误结果

    if con is not None: # 如果提供了连接，则直接使用
        return _run(con)

    with connection(db_path, read_only=read_only) as owned: # 否则临时打开连接并使用
        return _run(owned)
