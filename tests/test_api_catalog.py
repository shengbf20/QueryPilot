"""表清单 API：只暴露已登记的表，并按页返回数据。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from querypilot.api.app import create_app
from querypilot.db.connection import QueryResult
from querypilot.metadata_engine.models import ColumnMeta, TableMeta


def _meta() -> TableMeta:
    return TableMeta(
        table="dim_mgr_info",
        alias="客户经理",
        layer="dim",
        description="客户经理名册",
        primary_key=["mgr_id"],
        columns=[
            ColumnMeta(name="mgr_id", type="VARCHAR", description="经理编号"),
            ColumnMeta(name="mgr_name", type="VARCHAR", description="经理姓名"),
        ],
        usage=["一位客户经理"],
        notes=["模拟数据"],
    )


def _execute(sql: str, **_kwargs) -> QueryResult:
    if sql.startswith("SELECT COUNT"):
        return QueryResult(columns=["count"], rows=[(2,)], row_count=1)
    return QueryResult(
        columns=["mgr_id", "mgr_name"],
        rows=[("m1", "甲"), ("m2", "乙")],
        row_count=2,
    )


def test_catalog_lists_registered_tables(monkeypatch) -> None:
    monkeypatch.setattr(
        "querypilot.api.catalog_routes.load_metadata",
        lambda: SimpleNamespace(tables={"dim_mgr_info": _meta()}),
    )
    monkeypatch.setattr("querypilot.api.catalog_routes.execute", _execute)
    client = TestClient(create_app())
    resp = client.get("/api/catalog/tables")
    assert resp.status_code == 200
    item = resp.json()["tables"][0]
    assert item["name"] == "dim_mgr_info"
    assert item["alias"] == "客户经理"
    assert item["layer"] == "维表"
    assert item["row_count"] == 2


def test_catalog_detail_pages_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "querypilot.api.catalog_routes.load_metadata",
        lambda: SimpleNamespace(tables={"dim_mgr_info": _meta()}),
    )
    monkeypatch.setattr("querypilot.api.catalog_routes.execute", _execute)
    client = TestClient(create_app())
    resp = client.get("/api/catalog/tables/dim_mgr_info", params={"offset": 0, "limit": 50})
    assert resp.status_code == 200
    body = resp.json()
    assert body["grain"] == "一位客户经理"
    assert body["columns"][0] == {"name": "mgr_id", "description": "经理编号"}
    assert body["rows"] == [["m1", "甲"], ["m2", "乙"]]


def test_catalog_unknown_table(monkeypatch) -> None:
    monkeypatch.setattr(
        "querypilot.api.catalog_routes.load_metadata",
        lambda: SimpleNamespace(tables={}),
    )
    client = TestClient(create_app())
    resp = client.get("/api/catalog/tables/not_a_table")
    assert resp.status_code == 404
