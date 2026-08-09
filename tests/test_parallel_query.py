"""Phase-4 step 4: parallel metric plan (B) + eval workers (C)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from querypilot.agent.parallel import (
    benchmark_plan,
    build_parallel_plan,
    detect_multi_metric_question,
    execute_plan,
    merge_on_pty_id,
)
from querypilot.agent.pipeline import ask
from querypilot.config import get_settings
from querypilot.eval.models import EvalCase
from querypilot.eval.runner import run_eval
from querypilot.metadata_engine import load_metadata


requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=False)


def test_detect_multi_metric_requires_filter_and_two_domains():
    assert detect_multi_metric_question("客户资产与持仓") == ["asset", "hold"]
    assert detect_multi_metric_question("资产和持仓") == []  # no 客群 cue
    assert detect_multi_metric_question("客户总资产") == []  # single domain


def test_build_parallel_plan_asset_hold():
    plan = build_parallel_plan("查询客户的资产和持仓市值")
    assert plan is not None
    assert [q.name for q in plan.queries] == ["asset", "hold"]
    assert "dws_cust_aset_d" in plan.queries[0].sql
    assert "dwd_cust_hold_d" in plan.queries[1].sql


def test_merge_on_pty_id_outer():
    cols, rows = merge_on_pty_id(
        ["pty_id", "a"],
        [("1", 10), ("2", 20)],
        ["pty_id", "b"],
        [("2", 200), ("3", 300)],
        how="outer",
    )
    assert cols == ["pty_id", "a", "b"]
    by_id = {r[0]: r for r in rows}
    assert by_id["1"] == ("1", 10, None)
    assert by_id["2"] == ("2", 20, 200)
    assert by_id["3"] == ("3", None, 300)


@requires_db
def test_execute_plan_parallel_matches_serial(metadata):
    plan = build_parallel_plan("统计客户资产与持仓")
    assert plan is not None
    cmp = benchmark_plan(plan, metadata=metadata, max_rows=500)
    assert cmp["ok"], (cmp.get("serial_error"), cmp.get("parallel_error"))
    assert cmp["rows_match"]
    assert cmp["columns_match"]
    assert cmp["parallel_rows"] > 0


@requires_db
def test_ask_use_parallel_success(metadata):
    out = ask(
        "统计客户的资产和持仓市值",
        metadata=metadata,
        use_parallel=True,
        use_cache=False,
        include_values=False,
        max_few_shots=0,
        max_rows=200,
    )
    assert out.ok, out.message
    assert out.extras.get("parallel") is True
    assert "pty_id" in out.columns
    assert out.row_count > 0
    assert out.timing.generate_ms == 0.0


@requires_db
def test_ask_use_parallel_falls_back_when_not_eligible(metadata):
    """Single-domain question should not take parallel path; needs LLM/fake → use cache path off."""
    from types import SimpleNamespace

    class _FC:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs: Any) -> SimpleNamespace:
            self.calls += 1
            content = (
                '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d",'
                '"rationale":"n","uses_cte":false}'
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                model="fake",
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=_FC()))
    out = ask(
        "有多少客户",
        metadata=metadata,
        client=client,
        use_parallel=True,
        use_cache=False,
        include_values=False,
        max_few_shots=0,
        allow_exact_few_shot=False,
    )
    assert out.ok, out.message
    assert out.extras.get("parallel") is not True
    assert client.chat.completions.calls == 1


def test_run_eval_max_workers_preserves_order_and_ex():
    cases = [
        EvalCase(id="a", question="q1", gold_sql="SELECT 1 AS n"),
        EvalCase(id="b", question="q2", gold_sql="SELECT 2 AS n"),
        EvalCase(id="c", question="q3", gold_sql="SELECT 3 AS n"),
    ]

    def ask_fn(q: str, **kwargs: Any) -> SimpleNamespace:
        n = {"q1": 1, "q2": 2, "q3": 3}[q]
        return SimpleNamespace(
            ok=True,
            sql=f"SELECT {n} AS n",
            columns=["n"],
            rows=[(n,)],
            message="ok",
            stage="done",
            timing=SimpleNamespace(
                prune_ms=0,
                generate_ms=0,
                l1_ms=0,
                l2_ms=0,
                execute_ms=0,
                probe_ms=0,
                total_ms=1,
                cache_hit=False,
            ),
        )

    def execute_fn(sql: str, **kwargs: Any) -> SimpleNamespace:
        # gold and pred both SELECT n
        val = int(sql.split()[1])
        time.sleep(0.05)
        return SimpleNamespace(columns=["n"], rows=[(val,)])

    t0 = time.perf_counter()
    serial = run_eval(
        cases,
        ask_fn=ask_fn,
        execute_fn=execute_fn,
        max_workers=1,
        save_path=False,
    )
    serial_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    parallel = run_eval(
        cases,
        ask_fn=ask_fn,
        execute_fn=execute_fn,
        max_workers=3,
        save_path=False,
    )
    parallel_ms = (time.perf_counter() - t0) * 1000.0

    assert serial.accuracy == 1.0
    assert parallel.accuracy == 1.0
    assert [r.case_id for r in parallel.results] == ["a", "b", "c"]
    # Wall clock should improve with sleep-bound workers (loose bound)
    assert parallel_ms < serial_ms
