"""API-2: FastAPI routes with mocked ask() (no LLM / DB)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from querypilot.agent.models import PipelineResult, StageTiming
from querypilot.api.app import create_app
from querypilot.cli import build_parser


def _fake_result(*, cache_hit: bool = False) -> PipelineResult:
    return PipelineResult(
        ok=True,
        question="有多少年龄大于30岁的女性客户？",
        sql="SELECT COUNT(*) AS n FROM ads_cust_info_d",
        rationale="count",
        tables=["ads_cust_info_d"],
        columns=["n"],
        rows=[(Decimal("42"),)],
        row_count=1,
        message="ok",
        stage="done",
        timing=StageTiming(total_ms=12.0, cache_hit=cache_hit),
        extras={},
    )


def test_build_parser_serve_defaults() -> None:
    args = build_parser().parse_args(["serve"])
    assert args.command == "serve"
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.reload is False


def test_health() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_api_ask_uses_ask_and_serializes() -> None:
    app = create_app()
    client = TestClient(app)
    with patch("querypilot.agent.pipeline.ask", return_value=_fake_result()) as mocked:
        resp = client.post(
            "/api/ask",
            json={
                "question": "有多少年龄大于30岁的女性客户？",
                "use_cache": True,
                "max_rows": 50,
                "use_parallel": False,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["rows"] == [["42"]]
    assert body["timing"]["cache_hit"] is False
    assert "prune_summary" in body
    mocked.assert_called_once()
    kwargs = mocked.call_args.kwargs
    assert kwargs["max_rows"] == 50
    assert kwargs["use_cache"] is True
    assert kwargs["use_parallel"] is False
    assert kwargs["history"] is None


def test_api_ask_forwards_history() -> None:
    app = create_app()
    client = TestClient(app)
    with patch("querypilot.agent.pipeline.ask", return_value=_fake_result()) as mocked:
        resp = client.post(
            "/api/ask",
            json={
                "question": "只要人数",
                "history": [
                    {"role": "user", "content": "帮我看看客户"},
                    {"role": "assistant", "content": "人数还是资产？"},
                ],
            },
        )
    assert resp.status_code == 200
    hist = mocked.call_args.kwargs["history"]
    assert hist[0]["role"] == "user"
    assert hist[-1]["content"] == "人数还是资产？"


def test_api_ask_rejects_empty_question() -> None:
    client = TestClient(create_app())
    resp = client.post("/api/ask", json={"question": ""})
    assert resp.status_code == 422


def test_api_export_csv() -> None:
    client = TestClient(create_app())
    resp = client.post(
        "/api/export",
        json={
            "columns": ["n", "name"],
            "rows": [[1, "a"], [2, "b"]],
            "filename": "demo.csv",
        },
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "demo.csv" in resp.headers["content-disposition"]
    text = resp.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "n,name"
    assert "1,a" in text
    assert "2,b" in text
