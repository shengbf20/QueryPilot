"""Phase-4 step-2 preflight: step-1 still green; metadata/prune hooks ready for caching."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from querypilot.agent import StageTiming, ask
from querypilot.config import get_settings
from querypilot.metadata_engine import load_metadata


requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)

    def create(self, **kwargs: Any) -> SimpleNamespace:
        content = (
            self._contents.pop(0)
            if self._contents
            else '{"sql":"SELECT 1","rationale":"","uses_cte":false}'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


class _FakeClient:
    def __init__(self, contents: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(contents))


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=False)


def test_stage_timing_exposes_cache_hit_hook():
    """Step 3 will flip cache_hit; step 2 must not break the field."""
    t = StageTiming()
    assert "cache_hit" in t.to_dict()
    assert t.cache_hit is False


def test_load_metadata_repeatable_without_cache(metadata):
    """Baseline: repeated load_metadata succeeds (step 2 will make 2nd call cheaper)."""
    t0 = time.perf_counter()
    md2 = load_metadata(load_db_codes=False)
    second_ms = (time.perf_counter() - t0) * 1000.0
    assert set(metadata.tables) == set(md2.tables)
    assert second_ms >= 0.0


def test_prune_same_question_stable(metadata):
    q = "有多少年龄大于30岁的女性客户？"
    a = metadata.prune_schema(q)
    b = metadata.prune_schema(q)
    assert list(a.tables) == list(b.tables)
    assert a.tables  # non-empty for a real marketing question


@requires_db
def test_ask_accepts_shared_metadata_for_batch_path(metadata):
    """Step 2/bench will share one MetadataBundle across asks — contract must hold."""
    client = _FakeClient(
        [
            '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 30",'
            '"rationale":"统计","uses_cte":false}'
        ]
    )
    out = ask(
        "年龄大于30的客户有多少",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
    )
    assert out.ok, out.message
    assert out.timing.prune_ms > 0
    assert out.timing.cache_hit is False


@requires_db
def test_bench_run_bench_still_importable(metadata):
    bench_path = Path(__file__).resolve().parents[1] / "scripts" / "bench_pipeline.py"
    spec = importlib.util.spec_from_file_location("bench_pipeline_prep", bench_path)
    assert spec and spec.loader
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)

    client = _FakeClient(
        [
            '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d",'
            '"rationale":"计数","uses_cte":false}'
        ]
        * 2
    )
    report = bench.run_bench(
        ["客户有多少"],
        warm=False,
        rounds=1,
        max_few_shots=0,
        include_values=False,
        client=client,
        metadata=metadata,
    )
    assert report["ok_count"] == 1
    assert "prune_ms" in report["stage_mean_ms"]
    assert report["items"][0]["timing"]["cache_hit"] is False
