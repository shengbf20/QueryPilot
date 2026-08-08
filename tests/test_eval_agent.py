"""Tests for Eval-Agent attribution (phase-3 step 4)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from querypilot.eval import (
    CaseEvalResult,
    Diagnosis,
    EvalReport,
    TimingInfo,
    classify_heuristic,
    diagnose_case,
    diagnose_failures,
    render_diagnosis_markdown,
    save_diagnoses,
)
from querypilot.eval.eval_agent import build_diagnose_prompt


def _fail(**kwargs) -> CaseEvalResult:
    base = dict(
        case_id="x",
        question="q",
        matched=False,
        score=0.0,
        gold_sql="SELECT 1",
        pred_sql="SELECT 1",
        ask_ok=True,
        gold_ok=True,
        stage="done",
        timing=TimingInfo(total_ms=1.0),
    )
    base.update(kwargs)
    return CaseEvalResult(**base)


def test_classify_column_mismatch():
    types = classify_heuristic(
        _fail(error="column count mismatch: pred=3 gold=2", match_reason="column count mismatch")
    )
    assert "column_mismatch" in types


def test_classify_schema_hallucination_l1():
    types = classify_heuristic(
        _fail(
            ask_ok=False,
            stage="l1",
            error="L1 安全围栏拦截: Table not allowed: dwd_cust_pnl_d; Unknown column: pnl",
            pred_sql="SELECT pnl FROM dwd_cust_pnl_d",
        )
    )
    assert "schema_hallucination" in types
    assert "agent_failed" in types


def test_classify_row_mismatch():
    types = classify_heuristic(_fail(error="row multiset mismatch", match_reason="row multiset mismatch"))
    assert "row_mismatch" in types


def test_classify_row_count_reason_as_row_mismatch():
    """P0: EX often emits 'row count pred=… gold=…' (not only multiset wording)."""
    types = classify_heuristic(
        _fail(error="row count pred=0 gold=1", match_reason="row count pred=0 gold=1")
    )
    assert "row_mismatch" in types
    assert "unknown" not in types


def test_classify_join_asymmetry():
    """P1: join present on only one side → join_error."""
    types = classify_heuristic(
        _fail(
            error="row multiset mismatch",
            pred_sql="SELECT * FROM a JOIN b ON a.pty_id=b.pty_id",
            gold_sql="SELECT * FROM a",
        )
    )
    assert "join_error" in types
    assert "row_mismatch" in types


def test_classify_unknown_fallback():
    """P1: no recognizable signal → unknown."""
    types = classify_heuristic(
        _fail(error="unexpected comparator", pred_sql="SELECT 1", gold_sql="SELECT 1")
    )
    assert types == ["unknown"]


def test_classify_agent_failed_only():
    """P1: ask failure without schema tokens → agent_failed."""
    types = classify_heuristic(
        _fail(ask_ok=False, stage="generate", error="gen fail", pred_sql="")
    )
    assert types == ["agent_failed"]


def test_classify_gold_failed():
    types = classify_heuristic(
        _fail(
            gold_ok=False,
            ask_ok=True,
            stage="gold_execute",
            error="gold execute failed: binder error",
        )
    )
    assert "gold_failed" in types


def test_classify_time_and_aggregation_signals():
    types = classify_heuristic(
        _fail(
            error="column count mismatch: pred=3 gold=2",
            pred_sql=(
                "SELECT age_group, COUNT(*) AS cust_cnt, SUM(nm_tot_aset) AS total_asset "
                "FROM t JOIN u ON t.pty_id=u.pty_id "
                "WHERE u.data_dt=(SELECT MAX(data_dt) FROM u) GROUP BY age_group"
            ),
            gold_sql=(
                "SELECT age_type, SUM(aset) AS aset FROM t "
                "JOIN u ON t.pty_id=u.pty_id AND u.data_dt='20260331' GROUP BY age_type"
            ),
        )
    )
    assert "column_mismatch" in types
    assert "time_filter" in types
    assert "aggregation" in types


def test_classify_matched_empty():
    assert (
        classify_heuristic(
            CaseEvalResult(
                case_id="1",
                question="q",
                matched=True,
                score=1.0,
                ask_ok=True,
                gold_ok=True,
                stage="done",
            )
        )
        == []
    )


def test_diagnose_case_heuristic_only():
    result = _fail(
        case_id="2",
        error="column count mismatch: pred=3 gold=2",
        pred_sql="SELECT a, b, c FROM t",
        gold_sql="SELECT a, b FROM t",
    )
    diag = diagnose_case(result, use_llm=False)
    assert isinstance(diag, Diagnosis)
    assert not diag.matched
    assert "column_mismatch" in diag.error_types
    assert diag.source == "heuristic"
    assert "Case 2" in diag.markdown
    assert "column_mismatch" in diag.markdown


def test_diagnose_case_matched_passthrough():
    result = CaseEvalResult(
        case_id="1",
        question="q",
        matched=True,
        score=1.0,
        ask_ok=True,
        gold_ok=True,
        stage="done",
    )
    diag = diagnose_case(result, use_llm=True)
    assert diag.matched
    assert diag.error_types == []
    assert diag.confidence == 1.0
    assert diag.source == "heuristic"


def test_diagnose_case_llm_enrichment():
    result = _fail(case_id="3", error="column count mismatch: pred=2 gold=1")

    def fake_generate_json(prompt, **kwargs):
        assert "column_mismatch" in prompt or "启发式" in prompt
        return {
            "error_types": ["column_mismatch", "aggregation"],
            "summary": "多选了聚合列",
            "evidence": ["pred has 2 cols"],
            "suggestions": ["去掉多余 COUNT"],
            "confidence": 0.8,
        }

    with patch("querypilot.llm.chat.generate_json", side_effect=fake_generate_json):
        diag = diagnose_case(result, use_llm=True)
    assert diag.source == "heuristic+llm"
    assert "aggregation" in diag.error_types
    assert diag.summary == "多选了聚合列"
    assert diag.confidence == pytest.approx(0.8)
    assert "去掉多余 COUNT" in diag.suggestions


def test_diagnose_case_llm_failure_falls_back():
    result = _fail(error="row multiset mismatch")

    with patch("querypilot.llm.chat.generate_json", side_effect=RuntimeError("api down")):
        diag = diagnose_case(result, use_llm=True)
    assert diag.source == "heuristic"
    assert "row_mismatch" in diag.error_types
    assert "llm_error" in diag.raw


def test_diagnose_case_llm_filters_bogus_types_and_clamps_confidence():
    """P1: invalid LLM error_types dropped; confidence clamped to [0, 1]."""
    result = _fail(error="column count mismatch: pred=2 gold=1")

    def fake_generate_json(prompt, **kwargs):
        return {
            "error_types": ["bogus", "COLUMN_MISMATCH", "aggregation"],
            "summary": "ok",
            "evidence": ["e"],
            "suggestions": ["s"],
            "confidence": 9.5,
        }

    with patch("querypilot.llm.chat.generate_json", side_effect=fake_generate_json):
        diag = diagnose_case(result, use_llm=True)
    assert "bogus" not in diag.error_types
    assert "column_mismatch" in diag.error_types
    assert "aggregation" in diag.error_types
    assert diag.confidence == pytest.approx(1.0)


def test_diagnose_failures_skips_matched_by_default():
    report = EvalReport(
        total=2,
        matched_count=1,
        accuracy=0.5,
        failed_ids=["2"],
        results=[
            CaseEvalResult(
                case_id="1",
                question="ok",
                matched=True,
                score=1.0,
                ask_ok=True,
                gold_ok=True,
                stage="done",
            ),
            _fail(case_id="2", error="column count mismatch: pred=2 gold=1"),
        ],
    )
    diags = diagnose_failures(report, use_llm=False)
    assert len(diags) == 1
    assert diags[0].case_id == "2"


def test_diagnose_failures_include_matched():
    """P1: include_matched=True keeps successful cases in the batch."""
    report = EvalReport(
        total=1,
        matched_count=1,
        accuracy=1.0,
        failed_ids=[],
        results=[
            CaseEvalResult(
                case_id="1",
                question="ok",
                matched=True,
                score=1.0,
                ask_ok=True,
                gold_ok=True,
                stage="done",
            )
        ],
    )
    diags = diagnose_failures(report, use_llm=False, include_matched=True)
    assert len(diags) == 1
    assert diags[0].matched and diags[0].error_types == []


def test_render_and_save_diagnoses(tmp_path):
    diag = diagnose_case(
        _fail(case_id="9", error="Table not allowed: foo", ask_ok=False, stage="l1"),
        use_llm=False,
    )
    md = render_diagnosis_markdown(diag)
    assert "## Case 9" in md
    path = save_diagnoses([diag], tmp_path / "d.json")
    text = path.read_text(encoding="utf-8")
    assert '"case_id": "9"' in text
    assert "schema_hallucination" in text
    assert "markdown" in text


def test_build_diagnose_prompt_contains_sqls():
    result = _fail(
        question="资产分布",
        pred_sql="SELECT 1",
        gold_sql="SELECT 2",
        error="column count mismatch",
    )
    prompt = build_diagnose_prompt(result, heuristic_types=["column_mismatch"])
    assert "资产分布" in prompt
    assert "SELECT 1" in prompt
    assert "SELECT 2" in prompt
    assert "column_mismatch" in prompt


def test_save_diagnoses_default_dir(tmp_path, monkeypatch):
    """P1: path=None writes diag_*.json under logs/eval_reports/."""
    report_dir = tmp_path / "logs" / "eval_reports"
    monkeypatch.setattr(
        "querypilot.eval.eval_agent.get_settings",
        lambda: type("S", (), {"root_dir": tmp_path})(),
    )
    diag = diagnose_case(
        _fail(case_id="1", error="column count mismatch: pred=2 gold=1"),
        use_llm=False,
    )
    path = save_diagnoses([diag], path=None)
    assert path.parent == report_dir
    assert path.name.startswith("diag_")
    assert path.suffix == ".json"
    assert path.exists()
