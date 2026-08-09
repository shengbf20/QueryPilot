"""API-1: PipelineResult → JSON-safe API dict (no LLM / DB)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from querypilot.agent.models import PipelineResult, StageTiming
from querypilot.api.serialize import json_safe, prune_summary_from
from querypilot.metadata_engine.join_graph import JoinPlan
from querypilot.metadata_engine.schema_pruner import PrunedSchema


def _pruned(*, seeds: list[str], tables: list[str]) -> PrunedSchema:
    return PrunedSchema(
        question="q",
        search_text="q",
        seed_tables=list(seeds),
        tables=list(tables),
        join_plan=JoinPlan(tables=list(tables), edges=[]),
    )


def test_json_safe_primitives_and_specials() -> None:
    assert json_safe(None) is None
    assert json_safe(True) is True
    assert json_safe(3) == 3
    assert json_safe(1.5) == 1.5
    assert json_safe("x") == "x"
    assert json_safe(Decimal("12.30")) == "12.30"
    assert json_safe(date(2026, 5, 31)) == "2026-05-31"
    assert json_safe(datetime(2026, 5, 31, 12, 0, 0)) == "2026-05-31T12:00:00"
    assert json_safe(UUID("12345678-1234-5678-1234-567812345678")) == (
        "12345678-1234-5678-1234-567812345678"
    )
    assert json_safe(b"hi") == "hi"
    assert json_safe((Decimal("1"), date(2026, 1, 1))) == ["1", "2026-01-01"]


def test_prune_summary_bridge_tables() -> None:
    pruned = _pruned(
        seeds=["ads_cust_info_d"],
        tables=["ads_cust_info_d", "dim_branch", "dws_cust_aset_d"],
    )
    summary = prune_summary_from(pruned)
    assert summary["seed_tables"] == ["ads_cust_info_d"]
    assert summary["tables"] == ["ads_cust_info_d", "dim_branch", "dws_cust_aset_d"]
    assert summary["bridge_tables"] == ["dim_branch", "dws_cust_aset_d"]
    assert summary["metrics"] == []


def test_prune_summary_none() -> None:
    assert prune_summary_from(None) == {
        "tables": [],
        "seed_tables": [],
        "bridge_tables": [],
        "metrics": [],
    }


def test_to_api_dict_contract_and_json_dumps() -> None:
    pruned = _pruned(seeds=["t1"], tables=["t1", "t2"])
    result = PipelineResult(
        ok=True,
        question="有多少年龄大于30岁的女性客户？",
        sql="SELECT COUNT(*) AS n FROM ads_cust_info_d",
        rationale="count female age>30",
        tables=["ads_cust_info_d"],
        columns=["n"],
        rows=[(Decimal("42"),), (date(2026, 5, 31),)],
        row_count=2,
        degraded=False,
        message="ok",
        probe_message="",
        probe_suggestions=[],
        corrected=False,
        stage="done",
        pruned=pruned,
        timing=StageTiming(
            prune_ms=1.0,
            generate_ms=10.0,
            l1_ms=0.5,
            l2_ms=0.5,
            execute_ms=2.0,
            probe_ms=0.0,
            total_ms=14.0,
            cache_hit=False,
        ),
        extras={"parallel": False},
    )
    payload = result.to_api_dict()
    expected_keys = {
        "ok",
        "question",
        "sql",
        "rationale",
        "tables",
        "columns",
        "rows",
        "row_count",
        "degraded",
        "message",
        "probe_message",
        "probe_suggestions",
        "corrected",
        "stage",
        "timing",
        "prune_summary",
        "extras",
    }
    assert set(payload) == expected_keys
    assert payload["rows"] == [["42"], ["2026-05-31"]]
    assert payload["prune_summary"]["bridge_tables"] == ["t2"]
    assert payload["timing"]["cache_hit"] is False
    # Must be fully JSON-serializable
    json.dumps(payload)


def test_to_api_dict_max_rows_truncates() -> None:
    result = PipelineResult(
        ok=True,
        question="q",
        columns=["a"],
        rows=[(1,), (2,), (3,)],
        row_count=3,
        stage="done",
    )
    payload = result.to_api_dict(max_rows=2)
    assert payload["rows"] == [[1], [2]]
    assert payload["row_count"] == 3  # original count preserved
