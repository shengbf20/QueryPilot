"""Tests for phase-4 step 1: StageTiming on ask() + bench scaffolding."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from querypilot.agent import StageTiming, ask
from querypilot.agent.models import PipelineResult
from querypilot.cli import format_pipeline_result
from querypilot.config import get_settings
from querypilot.eval import TimingInfo, run_case
from querypilot.eval.models import EvalCase
from querypilot.metadata_engine import load_metadata


def _api_key_ready() -> bool:
    key = get_settings().deepseek_api_key
    return bool(key) and not key.startswith("sk-your")


requires_live_llm = pytest.mark.skipif(
    not _api_key_ready(),
    reason="DEEPSEEK_API_KEY not set (or still placeholder in .env)",
)

requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.calls = 0

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
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


def test_stage_timing_to_dict_defaults():
    t = StageTiming()
    d = t.to_dict()
    assert d["total_ms"] == 0.0
    assert d["cache_hit"] is False
    assert set(d) >= {
        "prune_ms",
        "generate_ms",
        "l1_ms",
        "l2_ms",
        "execute_ms",
        "probe_ms",
        "total_ms",
        "cache_hit",
    }


def test_format_pipeline_result_includes_timing():
    result = PipelineResult(
        ok=True,
        question="q",
        stage="done",
        timing=StageTiming(
            prune_ms=1.5,
            generate_ms=100.0,
            l1_ms=2.0,
            l2_ms=3.0,
            execute_ms=4.0,
            probe_ms=0.5,
            total_ms=111.0,
        ),
    )
    text = format_pipeline_result(result)
    assert "timing_ms:" in text
    assert "total=111.0" in text
    assert "generate=100.0" in text
    assert "cache_hit=False" in text


@requires_db
def test_ask_success_fills_stage_timing(metadata):
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
    assert out.timing.total_ms > 0
    assert out.timing.prune_ms > 0
    assert out.timing.generate_ms > 0
    assert out.timing.l1_ms >= 0
    assert out.timing.l2_ms >= 0
    assert out.timing.execute_ms >= 0
    assert out.timing.probe_ms >= 0
    # Stages should roughly sum near total (allow overhead / clock noise)
    staged = (
        out.timing.prune_ms
        + out.timing.generate_ms
        + out.timing.l1_ms
        + out.timing.l2_ms
        + out.timing.execute_ms
        + out.timing.probe_ms
    )
    assert staged <= out.timing.total_ms + 5.0
    assert out.timing.cache_hit is False


@requires_db
def test_ask_l1_failure_still_has_partial_timing(metadata):
    client = _FakeClient(
        ['{"sql":"DELETE FROM ads_cust_info_d","rationale":"坏","uses_cte":false}']
    )
    out = ask(
        "删除客户",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
    )
    assert not out.ok
    assert out.stage == "l1"
    assert out.timing.total_ms > 0
    assert out.timing.prune_ms > 0
    assert out.timing.generate_ms > 0
    assert out.timing.l1_ms >= 0
    assert out.timing.execute_ms == 0.0
    assert out.timing.probe_ms == 0.0


def test_run_case_copies_stage_timing_from_pipeline():
    case = EvalCase(id="t1", question="q", gold_sql="SELECT 1 AS n")
    pipe = SimpleNamespace(
        ok=True,
        sql="SELECT 1 AS n",
        columns=["n"],
        rows=[(1,)],
        message="ok",
        stage="done",
        timing=StageTiming(
            prune_ms=10.0,
            generate_ms=200.0,
            l1_ms=1.0,
            l2_ms=2.0,
            execute_ms=3.0,
            probe_ms=0.5,
            total_ms=216.5,
            cache_hit=False,
        ),
    )
    out = run_case(
        case,
        ask_fn=lambda _q: pipe,
        execute_fn=lambda _sql: SimpleNamespace(columns=["n"], rows=[(1,)]),
    )
    assert out.matched
    assert out.timing.prune_ms == pytest.approx(10.0)
    assert out.timing.generate_ms == pytest.approx(200.0)
    assert out.timing.l1_ms == pytest.approx(1.0)
    assert out.timing.l2_ms == pytest.approx(2.0)
    assert out.timing.execute_ms == pytest.approx(3.0)
    assert out.timing.probe_ms == pytest.approx(0.5)
    assert out.timing.cache_hit is False
    assert out.timing.ask_ms >= 0
    assert out.timing.total_ms >= 0


def test_timing_info_defaults_keep_old_fields():
    t = TimingInfo(total_ms=1.0, ask_ms=2.0)
    assert t.gold_execute_ms == 0.0
    assert t.prune_ms == 0.0
    assert t.cache_hit is False


def test_bench_run_and_save_with_fake_client(tmp_path: Path, metadata):
    import importlib.util

    if not get_settings().db_path.exists():
        pytest.skip("competition.duckdb not imported yet")

    bench_path = Path(__file__).resolve().parents[1] / "scripts" / "bench_pipeline.py"
    spec = importlib.util.spec_from_file_location("bench_pipeline", bench_path)
    assert spec and spec.loader
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    format_bench_report = bench.format_bench_report
    run_bench = bench.run_bench
    save_bench_report = bench.save_bench_report

    client = _FakeClient(
        [
            '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d",'
            '"rationale":"计数","uses_cte":false}'
        ]
        * 4
    )
    report = run_bench(
        ["客户有多少"],
        warm=True,
        rounds=1,
        max_few_shots=0,
        include_values=False,
        client=client,
        metadata=metadata,
    )
    assert report["question_count"] == 1
    assert report["run_count"] == 2  # 1 cold + 1 warm
    assert report["by_mode"]["cold"]["count"] == 1
    assert report["by_mode"]["warm"]["count"] == 1
    assert report["stage_mean_ms"]["total_ms"] is not None
    assert "prune_ms" in report["stage_mean_ms"]
    text = format_bench_report(report)
    assert "stage_mean_ms:" in text
    assert "generate=" in text

    out = tmp_path / "bench.json"
    saved = save_bench_report(report, out)
    assert saved.exists()
    loaded = json.loads(saved.read_text(encoding="utf-8"))
    assert loaded["run_count"] == 2
    assert "timing" in loaded["items"][0]
    assert "generate_ms" in loaded["items"][0]["timing"]
