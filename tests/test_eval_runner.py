"""Tests for eval runner (phase-3 step 2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from querypilot.config import get_settings
from querypilot.db.connection import QueryResult
from querypilot.eval import (
    CaseEvalResult,
    TimingInfo,
    load_eval_report,
    percentile,
    run_case,
    run_eval,
    save_eval_report,
    summarize,
)
from querypilot.eval.models import EvalCase


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

requires_qa = pytest.mark.skipif(
    not (get_settings().data_dir / "Q&A.xlsx").exists(),
    reason="data/Q&A.xlsx not present",
)


def _pipe(*, ok: bool, sql: str = "", columns=None, rows=None, message="", stage="done"):
    return SimpleNamespace(
        ok=ok,
        sql=sql,
        columns=columns or [],
        rows=rows or [],
        message=message,
        stage=stage,
    )


def _exec(columns, rows):
    def _fn(_sql: str) -> QueryResult:
        return QueryResult(columns=list(columns), rows=[tuple(r) for r in rows], row_count=len(rows))

    return _fn


# ---------------------------------------------------------------------------
# percentile / summarize (scaffold)
# ---------------------------------------------------------------------------


def test_percentile_empty_and_basic():
    assert percentile([], 50) is None
    assert percentile([10.0], 50) == 10.0
    assert percentile([1, 2, 3, 4], 50) == 2.0
    assert percentile([1, 2, 3, 4], 100) == 4.0
    assert percentile([1, 2, 3, 4], 0) == 1.0


def test_percentile_rejects_bad_p():
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        percentile([1.0], 101)


def test_summarize_accuracy_and_failed_ids():
    results = [
        CaseEvalResult(
            case_id="1",
            question="q1",
            matched=True,
            score=1.0,
            difficulty="easy",
            timing=TimingInfo(total_ms=100),
        ),
        CaseEvalResult(
            case_id="2",
            question="q2",
            matched=False,
            score=0.0,
            difficulty="easy",
            timing=TimingInfo(total_ms=200),
        ),
        CaseEvalResult(
            case_id="3",
            question="q3",
            matched=True,
            score=1.0,
            difficulty="hard",
            timing=TimingInfo(total_ms=300),
        ),
    ]
    report = summarize(results)
    assert report.total == 3
    assert report.matched_count == 2
    assert report.accuracy == pytest.approx(2 / 3)
    assert report.failed_ids == ["2"]
    assert report.by_difficulty["easy"] == pytest.approx(0.5)
    assert report.by_difficulty["hard"] == pytest.approx(1.0)
    assert report.p50_ms is not None
    assert report.p95_ms is not None
    assert report.mean_ms == pytest.approx(200.0)
    assert report.to_dict()["matched_count"] == 2


def test_summarize_empty():
    report = summarize([])
    assert report.total == 0
    assert report.accuracy == 0.0
    assert report.failed_ids == []
    assert report.p50_ms is None


# ---------------------------------------------------------------------------
# 2.1 run_case
# ---------------------------------------------------------------------------


def test_run_case_match():
    case = EvalCase(id="1", question="q", gold_sql="SELECT 1 AS n", difficulty="easy")
    out = run_case(
        case,
        ask_fn=lambda _q: _pipe(ok=True, sql="SELECT 1 AS n", columns=["n"], rows=[(1,)]),
        execute_fn=_exec(["n"], [(1,)]),
    )
    assert out.matched
    assert out.score == 1.0
    assert out.ask_ok and out.gold_ok
    assert out.stage == "done"
    assert out.pred_sql == "SELECT 1 AS n"
    assert out.timing.total_ms >= 0
    assert out.timing.ask_ms >= 0
    assert out.timing.gold_execute_ms >= 0
    assert out.timing.match_ms >= 0


def test_run_case_mismatch():
    case = EvalCase(id="2", question="q", gold_sql="SELECT 1")
    out = run_case(
        case,
        ask_fn=lambda _q: _pipe(ok=True, sql="SELECT 2", columns=["n"], rows=[(2,)]),
        execute_fn=_exec(["n"], [(1,)]),
    )
    assert not out.matched
    assert out.ask_ok and out.gold_ok
    assert out.score < 1.0
    assert out.match_reason or out.error


def test_run_case_ask_failed_still_runs_gold():
    case = EvalCase(id="3", question="q", gold_sql="SELECT 1")
    out = run_case(
        case,
        ask_fn=lambda _q: _pipe(ok=False, message="L1 blocked", stage="l1", sql="DROP t"),
        execute_fn=_exec(["n"], [(1,)]),
    )
    assert not out.matched
    assert not out.ask_ok
    assert out.gold_ok
    assert out.stage == "l1"
    assert "L1" in out.error
    assert out.pred_sql == "DROP t"
    assert out.score == 0.0


def test_run_case_ask_raises():
    case = EvalCase(id="4", question="q", gold_sql="SELECT 1")

    def boom(_q: str):
        raise RuntimeError("llm down")

    out = run_case(case, ask_fn=boom, execute_fn=_exec(["n"], [(1,)]))
    assert not out.matched
    assert not out.ask_ok
    assert out.gold_ok
    assert "ask raised" in out.error
    assert out.stage == "ask"


def test_run_case_gold_execute_failed():
    case = EvalCase(id="5", question="q", gold_sql="SELECT bad")

    def bad_exec(_sql: str):
        raise RuntimeError("binder error")

    out = run_case(
        case,
        ask_fn=lambda _q: _pipe(ok=True, sql="SELECT 1", columns=["n"], rows=[(1,)]),
        execute_fn=bad_exec,
    )
    assert not out.matched
    assert out.ask_ok
    assert not out.gold_ok
    assert out.stage == "gold_execute"
    assert "gold execute failed" in out.error


def test_run_case_column_reorder_still_matches():
    case = EvalCase(id="6", question="q", gold_sql="SELECT 1 AS id, 'a' AS name")
    out = run_case(
        case,
        ask_fn=lambda _q: _pipe(
            ok=True,
            sql="SELECT 'a' AS name, 1 AS id",
            columns=["name", "id"],
            rows=[("a", 1)],
        ),
        execute_fn=_exec(["id", "name"], [(1, "a")]),
    )
    assert out.matched


def test_run_case_forwards_max_rows_to_ask_and_execute(monkeypatch):
    """P1: max_rows must reach both default ask() and execute() (avoid truncated false EX)."""
    seen: dict[str, object] = {}

    def fake_ask(question: str, **kwargs):
        seen["ask_max_rows"] = kwargs.get("max_rows")
        return _pipe(ok=True, sql="SELECT 1 AS n", columns=["n"], rows=[(1,)])

    def fake_execute(sql: str, **kwargs):
        seen["exec_max_rows"] = kwargs.get("max_rows")
        return QueryResult(columns=["n"], rows=[(1,)], row_count=1)

    monkeypatch.setattr("querypilot.agent.pipeline.ask", fake_ask)
    monkeypatch.setattr("querypilot.db.execute", fake_execute)

    case = EvalCase(id="7", question="q", gold_sql="SELECT 1 AS n")
    out = run_case(case, max_rows=123)
    assert out.matched
    assert seen["ask_max_rows"] == 123
    assert seen["exec_max_rows"] == 123


# ---------------------------------------------------------------------------
# 2.2 run_eval
# ---------------------------------------------------------------------------


def test_run_eval_batch_accuracy_and_limit():
    cases = [
        EvalCase(id="a", question="q1", gold_sql="SELECT 1", difficulty="easy"),
        EvalCase(id="b", question="q2", gold_sql="SELECT 2", difficulty="easy"),
        EvalCase(id="c", question="q3", gold_sql="SELECT 3", difficulty="hard"),
    ]
    answers = {
        "q1": _pipe(ok=True, sql="SELECT 1", columns=["n"], rows=[(1,)]),
        "q2": _pipe(ok=True, sql="SELECT 9", columns=["n"], rows=[(9,)]),  # mismatch
        "q3": _pipe(ok=True, sql="SELECT 3", columns=["n"], rows=[(3,)]),
    }
    gold = {
        "SELECT 1": (["n"], [(1,)]),
        "SELECT 2": (["n"], [(2,)]),
        "SELECT 3": (["n"], [(3,)]),
    }

    report = run_eval(
        cases=cases,
        limit=2,
        ask_fn=lambda q: answers[q],
        execute_fn=lambda sql: QueryResult(
            columns=gold[sql][0], rows=gold[sql][1], row_count=len(gold[sql][1])
        ),
    )
    assert report.total == 2
    assert report.matched_count == 1
    assert report.accuracy == pytest.approx(0.5)
    assert report.failed_ids == ["b"]
    assert report.p50_ms is not None
    assert len(report.results) == 2


def test_run_eval_empty_cases():
    report = run_eval(cases=[], ask_fn=lambda _q: _pipe(ok=True), execute_fn=_exec([], []))
    assert report.total == 0
    assert report.accuracy == 0.0
    assert report.failed_ids == []


def test_run_eval_continues_after_ask_failure():
    cases = [
        EvalCase(id="1", question="bad", gold_sql="SELECT 1"),
        EvalCase(id="2", question="good", gold_sql="SELECT 2"),
    ]

    def ask(q: str):
        if q == "bad":
            return _pipe(ok=False, message="gen fail", stage="generate")
        return _pipe(ok=True, sql="SELECT 2", columns=["n"], rows=[(2,)])

    report = run_eval(
        cases=cases,
        ask_fn=ask,
        execute_fn=lambda sql: QueryResult(
            columns=["n"],
            rows=[(1,)] if sql.endswith("1") else [(2,)],
            row_count=1,
        ),
    )
    assert report.total == 2
    assert report.matched_count == 1
    assert report.failed_ids == ["1"]
    assert report.results[0].ask_ok is False
    assert report.results[1].matched


def test_run_eval_continues_after_gold_failure():
    """P1: gold SQL failure on one case must not abort the batch."""
    cases = [
        EvalCase(id="1", question="q1", gold_sql="SELECT bad"),
        EvalCase(id="2", question="q2", gold_sql="SELECT 2"),
    ]

    def ask(q: str):
        n = 1 if q == "q1" else 2
        return _pipe(ok=True, sql=f"SELECT {n}", columns=["n"], rows=[(n,)])

    def execute(sql: str):
        if "bad" in sql:
            raise RuntimeError("binder error")
        return QueryResult(columns=["n"], rows=[(2,)], row_count=1)

    report = run_eval(cases=cases, ask_fn=ask, execute_fn=execute)
    assert report.total == 2
    assert report.matched_count == 1
    assert report.failed_ids == ["1"]
    assert report.results[0].ask_ok and not report.results[0].gold_ok
    assert report.results[0].stage == "gold_execute"
    assert report.results[1].matched


# ---------------------------------------------------------------------------
# 2.3 report JSON
# ---------------------------------------------------------------------------


def test_save_and_load_eval_report(tmp_path):
    report = summarize(
        [
            CaseEvalResult(
                case_id="1",
                question="q",
                matched=True,
                score=1.0,
                timing=TimingInfo(total_ms=12.5, ask_ms=10.0, gold_execute_ms=2.0, match_ms=0.5),
            )
        ]
    )
    path = save_eval_report(report, tmp_path / "r.json")
    assert path.exists()
    loaded = load_eval_report(path)
    assert loaded["total"] == 1
    assert loaded["matched_count"] == 1
    assert loaded["accuracy"] == pytest.approx(1.0)
    assert loaded["results"][0]["case_id"] == "1"
    assert loaded["results"][0]["timing"]["total_ms"] == pytest.approx(12.5)
    assert "saved_at" in loaded


def test_run_eval_save_path(tmp_path):
    cases = [EvalCase(id="1", question="q", gold_sql="SELECT 1")]
    out = tmp_path / "batch.json"
    report = run_eval(
        cases=cases,
        ask_fn=lambda _q: _pipe(ok=True, sql="SELECT 1", columns=["n"], rows=[(1,)]),
        execute_fn=_exec(["n"], [(1,)]),
        save_path=out,
    )
    assert report.matched_count == 1
    loaded = load_eval_report(out)
    assert loaded["failed_ids"] == []
    assert loaded["total"] == 1


def test_run_eval_forwards_allow_exact_few_shot(monkeypatch):
    """Default ask path must receive allow_exact_few_shot from run_eval kwargs."""
    seen: dict = {}

    def _fake_ask(question, **kwargs):
        seen.update(kwargs)
        return _pipe(ok=True, sql="SELECT 1", columns=["n"], rows=[(1,)])

    monkeypatch.setattr("querypilot.agent.pipeline.ask", _fake_ask)
    cases = [EvalCase(id="1", question="q", gold_sql="SELECT 1")]
    report = run_eval(
        cases=cases,
        execute_fn=_exec(["n"], [(1,)]),
        allow_exact_few_shot=False,
        max_few_shots=0,
    )
    assert report.matched_count == 1
    assert seen.get("allow_exact_few_shot") is False
    assert seen.get("max_few_shots") == 0


def test_run_eval_paths_loads_many(tmp_path, monkeypatch):
    from openpyxl import Workbook

    from querypilot.eval.dataset import load_qa_cases_many

    def _write(name: str, case_id: str) -> Path:
        path = tmp_path / name
        wb = Workbook()
        ws = wb.active
        ws.append(["序号", "问题", "SQL"])
        ws.append([case_id, f"q-{case_id}", "SELECT 1"])
        wb.save(path)
        return path

    p1 = _write("a.xlsx", "E01")
    p2 = _write("b.xlsx", "M01")
    loaded = load_qa_cases_many([p1, p2])
    assert [c.id for c in loaded] == ["E01", "M01"]

    report = run_eval(
        paths=[p1, p2],
        ask_fn=lambda _q: _pipe(ok=True, sql="SELECT 1", columns=["n"], rows=[(1,)]),
        execute_fn=_exec(["n"], [(1,)]),
    )
    assert report.total == 2
    assert report.failed_ids == []


def test_run_eval_save_path_true_uses_default_report_dir(tmp_path, monkeypatch):
    """P1: save_path=True writes timestamped JSON under logs/eval_reports/."""
    report_dir = tmp_path / "eval_reports"
    monkeypatch.setattr(
        "querypilot.eval.runner.default_report_dir",
        lambda: report_dir,
    )
    cases = [EvalCase(id="1", question="q", gold_sql="SELECT 1")]
    report = run_eval(
        cases=cases,
        ask_fn=lambda _q: _pipe(ok=True, sql="SELECT 1", columns=["n"], rows=[(1,)]),
        execute_fn=_exec(["n"], [(1,)]),
        save_path=True,
    )
    assert report.matched_count == 1
    files = sorted(report_dir.glob("eval_*.json"))
    assert len(files) == 1
    loaded = load_eval_report(files[0])
    assert loaded["total"] == 1
    assert loaded["failed_ids"] == []
    assert "saved_at" in loaded


# ---------------------------------------------------------------------------
# 2.4 live smoke (skip without key/db/qa)
# ---------------------------------------------------------------------------


@requires_live_llm
@requires_db
@requires_qa
def test_run_eval_live_smoke_limit_1(tmp_path):
    """Real ask + gold SQL on 1 case; only checks report shape, not EX target."""
    report = run_eval(limit=1, save_path=tmp_path / "live_smoke.json")
    assert report.total == 1
    assert len(report.results) == 1
    item = report.results[0]
    assert item.case_id
    assert item.question
    assert item.gold_sql
    assert item.timing.total_ms >= 0
    assert item.stage in {"ask", "generate", "l1", "l2", "execute", "gold_execute", "done"}
    loaded = load_eval_report(tmp_path / "live_smoke.json")
    assert loaded["total"] == 1
    assert "accuracy" in loaded
    assert "p50_ms" in loaded or loaded.get("p50_ms") is None
