"""已登记表的清单、基本信息和分页数据。"""

from __future__ import annotations

import re

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from querypilot.api.serialize import json_safe
from querypilot.db import execute
from querypilot.metadata_engine import load_metadata
from querypilot.metadata_engine.models import TableMeta

router = APIRouter()

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LAYER_LABEL = {
    "dim": "维表",
    "ads": "应用表",
    "dwd": "明细表",
    "dws": "汇总表",
}
_LAYER_ORDER = {"dim": 0, "ads": 1, "dwd": 2, "dws": 3}
_PAGE_MAX = 200


def _quote(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError(name)
    return '"' + name + '"'


def _layer_label(layer: str) -> str:
    return _LAYER_LABEL.get(layer, layer or "表")


def _count_rows(name: str) -> int:
    result = execute(f"SELECT COUNT(*) FROM {_quote(name)}", max_rows=1)
    if not result.rows:
        return 0
    return int(result.rows[0][0])


def _summary(meta: TableMeta, row_count: int) -> dict:
    return {
        "name": meta.table,
        "alias": meta.alias or meta.table,
        "layer": _layer_label(meta.layer),
        "description": meta.description or "",
        "column_count": len(meta.columns),
        "row_count": row_count,
    }


def _ordered_tables() -> list[TableMeta]:
    tables = list(load_metadata().tables.values())
    tables.sort(key=lambda meta: (_LAYER_ORDER.get(meta.layer, 9), meta.alias or meta.table))
    return tables


@router.get("/api/catalog/tables")
def api_catalog_tables() -> JSONResponse:
    items = []
    for meta in _ordered_tables():
        items.append(_summary(meta, _count_rows(meta.table)))
    return JSONResponse({"tables": items}, media_type="application/json; charset=utf-8")


@router.get("/api/catalog/tables/{name}")
def api_catalog_table(
    name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=_PAGE_MAX),
) -> JSONResponse:
    meta = load_metadata().tables.get(name)
    if meta is None or not _NAME.fullmatch(name):
        return JSONResponse({"detail": "没有这张表"}, status_code=404)
    total = _count_rows(name)
    quoted = _quote(name)
    page = execute(
        f"SELECT * FROM {quoted} LIMIT {int(limit)} OFFSET {int(offset)}",
        max_rows=limit,
    )
    payload = {
        **_summary(meta, total),
        "primary_key": list(meta.primary_key),
        "grain": (meta.usage[0] if meta.usage else ""),
        "notes": [note for note in meta.notes if note],
        "columns": [
            {"name": col.name, "description": col.description or ""}
            for col in meta.columns
        ],
        "offset": offset,
        "limit": limit,
        "data_columns": page.columns,
        "rows": json_safe(page.rows),
    }
    return JSONResponse(payload, media_type="application/json; charset=utf-8")
