"""Tests for HITL review routing + Few-Shot reflux (phase-3 step 5)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from querypilot.eval import (
    BUCKET_AUTO_PASS,
    BUCKET_BAD_CASE,
    BUCKET_NEEDS_REVIEW,
    CaseEvalResult,
    Diagnosis,
    EvalReport,
    TimingInfo,
    append_few_shot,
    approve_and_reflux,
    build_review_queue,
    diagnose_case,
    find_ticket,
    format_review_queue,
    load_review_queue,
    reject_ticket,
    route_case,
    save_review_queue,
)
from querypilot.eval.review import CONF_REVIEW_MIN


def _result(**kwargs) -> CaseEvalResult:
    base = dict(
        case_id="1",
        question="q",
        matched=False,
        score=0.0,
        gold_sql="SELECT 1",
        pred_sql="SELECT 2",
        ask_ok=True,
        gold_ok=True,
        stage="done",
        timing=TimingInfo(total_ms=1.0),
    )
    base.update(kwargs)
    return CaseEvalResult(**base)


def test_route_matched_auto_pass():
    assert route_case(_result(matched=True, score=1.0)) == BUCKET_AUTO_PASS


def test_route_needs_review_by_confidence():
    diag = Diagnosis(case_id="2", matched=False, confidence=0.7, error_types=["column_mismatch"])
    assert route_case(_result(case_id="2"), diag) == BUCKET_NEEDS_REVIEW


def test_route_bad_case_low_confidence_or_missing_diag():
    low = Diagnosis(case_id="3", matched=False, confidence=0.2)
    assert route_case(_result(case_id="3"), low) == BUCKET_BAD_CASE
    assert route_case(_result(case_id="4"), None) == BUCKET_BAD_CASE


def test_route_boundary_review_min():
    at_min = Diagnosis(case_id="5", matched=False, confidence=CONF_REVIEW_MIN)
    below = Diagnosis(case_id="6", matched=False, confidence=CONF_REVIEW_MIN - 1e-9)
    assert route_case(_result(case_id="5"), at_min) == BUCKET_NEEDS_REVIEW
    assert route_case(_result(case_id="6"), below) == BUCKET_BAD_CASE


def test_build_review_queue_buckets():
    report = EvalReport(
        total=3,
        matched_count=1,
        accuracy=1 / 3,
        failed_ids=["2", "3"],
        results=[
            _result(case_id="1", matched=True, score=1.0, question="ok"),
            _result(case_id="2", question="fuzzy", error="column count mismatch"),
            _result(case_id="3", question="bad", error="unknown"),
        ],
    )
    diagnoses = [
        Diagnosis(case_id="2", matched=False, confidence=0.8, error_types=["column_mismatch"], summary="cols"),
        Diagnosis(case_id="3", matched=False, confidence=0.1, error_types=["unknown"], summary="unk"),
    ]
    queue = build_review_queue(report, diagnoses)
    assert queue.auto_pass_ids == ["1"]
    assert queue.needs_review_ids == ["2"]
    assert queue.bad_case_ids == ["3"]
    assert find_ticket(queue, "2").bucket == BUCKET_NEEDS_REVIEW


def test_save_load_review_queue(tmp_path: Path):
    report = EvalReport(
        total=1,
        matched_count=0,
        accuracy=0.0,
        failed_ids=["2"],
        results=[_result(case_id="2", question="资产分布")],
    )
    queue = build_review_queue(
        report,
        [Diagnosis(case_id="2", matched=False, confidence=0.75, error_types=["column_mismatch"])],
    )
    path = save_review_queue(queue, tmp_path / "q.json")
    loaded = load_review_queue(path)
    assert loaded.needs_review_ids == ["2"]
    assert loaded.tickets[0].question == "资产分布"


def test_append_few_shot_and_skip_duplicate(tmp_path: Path):
    path = tmp_path / "examples.yaml"
    path.write_text("# header\n\nexamples: []\n", encoding="utf-8")
    written, out = append_few_shot("问A", "SELECT 1", rationale="r1", path=path)
    assert written and out == path
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(doc["examples"]) == 1
    assert doc["examples"][0]["question"] == "问A"

    written2, _ = append_few_shot("问A", "SELECT 9", path=path)
    assert written2 is False
    doc2 = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(doc2["examples"]) == 1
    assert "SELECT 1" in doc2["examples"][0]["sql"]


def test_approve_and_reflux_updates_ticket(tmp_path: Path):
    few = tmp_path / "fs.yaml"
    few.write_text("examples: []\n", encoding="utf-8")
    ticket = build_review_queue(
        EvalReport(
            total=1,
            matched_count=0,
            accuracy=0.0,
            results=[
                _result(
                    case_id="2",
                    question="年龄段资产",
                    gold_sql="SELECT age, SUM(a) AS aset FROM t GROUP BY age",
                )
            ],
        ),
        [Diagnosis(case_id="2", matched=False, confidence=0.7, summary="列数不一致")],
    ).tickets[0]

    written, path, updated = approve_and_reflux(ticket, few_shots_path=few)
    assert written
    assert updated.status == "approved"
    assert updated.refluxed is True
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["examples"][0]["question"] == "年龄段资产"
    assert "SUM(a)" in doc["examples"][0]["sql"]


def test_approve_with_sql_override(tmp_path: Path):
    few = tmp_path / "fs.yaml"
    ticket = build_review_queue(
        EvalReport(
            total=1,
            matched_count=0,
            accuracy=0.0,
            results=[_result(case_id="9", question="q9", gold_sql="SELECT 1")],
        ),
        [Diagnosis(case_id="9", matched=False, confidence=0.9)],
    ).tickets[0]
    written, path, _ = approve_and_reflux(
        ticket,
        sql="SELECT 42 AS n",
        rationale="人工修正",
        few_shots_path=few,
    )
    assert written
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "42" in doc["examples"][0]["sql"]
    assert doc["examples"][0]["rationale"] == "人工修正"


def test_reject_ticket():
    ticket = build_review_queue(
        EvalReport(
            total=1,
            matched_count=0,
            accuracy=0.0,
            results=[_result(case_id="8")],
        ),
        [Diagnosis(case_id="8", matched=False, confidence=0.1)],
    ).tickets[0]
    reject_ticket(ticket)
    assert ticket.status == "rejected"
    assert ticket.refluxed is False


def test_heuristic_diagnose_confidence_routes_to_bad_case():
    """P1: heuristic conf (0.55) is below review_min → bad_case without LLM."""
    result = _result(
        case_id="2",
        error="column count mismatch: pred=3 gold=2",
        match_reason="column count mismatch: pred=3 gold=2",
    )
    diag = diagnose_case(result, use_llm=False)
    assert diag.confidence < CONF_REVIEW_MIN
    assert route_case(result, diag) == BUCKET_BAD_CASE


def test_append_few_shot_rejects_empty():
    """P1: empty question/sql must not write Few-Shot."""
    with pytest.raises(ValueError, match="question and sql"):
        append_few_shot("", "SELECT 1", path=Path("unused.yaml"))
    with pytest.raises(ValueError, match="question and sql"):
        append_few_shot("q", "  ", path=Path("unused.yaml"))


def test_append_few_shot_whitespace_normalized_duplicate(tmp_path: Path):
    """P1: question dedup ignores repeated whitespace."""
    path = tmp_path / "examples.yaml"
    path.write_text("examples: []\n", encoding="utf-8")
    assert append_few_shot("问  A", "SELECT 1", path=path)[0] is True
    assert append_few_shot("问 A", "SELECT 9", path=path)[0] is False
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(doc["examples"]) == 1


def test_approve_empty_sql_raises(tmp_path: Path):
    """P1: approve without gold/override SQL fails loudly."""
    ticket = build_review_queue(
        EvalReport(
            total=1,
            matched_count=0,
            accuracy=0.0,
            results=[_result(case_id="1", gold_sql="")],
        ),
        [Diagnosis(case_id="1", matched=False, confidence=0.7)],
    ).tickets[0]
    with pytest.raises(ValueError, match="no SQL"):
        approve_and_reflux(ticket, few_shots_path=tmp_path / "fs.yaml")


def test_approve_duplicate_still_marks_refluxed(tmp_path: Path):
    """P1: duplicate skip still marks ticket approved/refluxed (already in corpus)."""
    few = tmp_path / "fs.yaml"
    few.write_text("examples: []\n", encoding="utf-8")
    append_few_shot("同一问", "SELECT 1", path=few)
    ticket = build_review_queue(
        EvalReport(
            total=1,
            matched_count=0,
            accuracy=0.0,
            results=[_result(case_id="2", question="同一问", gold_sql="SELECT 9")],
        ),
        [Diagnosis(case_id="2", matched=False, confidence=0.8)],
    ).tickets[0]
    written, _, updated = approve_and_reflux(ticket, few_shots_path=few)
    assert written is False
    assert updated.status == "approved"
    assert updated.refluxed is True


def test_save_review_queue_default_dir(tmp_path: Path, monkeypatch):
    """P1: path=None writes queue_*.json under logs/review/."""
    monkeypatch.setattr(
        "querypilot.eval.review.default_review_dir",
        lambda: tmp_path / "logs" / "review",
    )
    queue = build_review_queue(
        EvalReport(
            total=1,
            matched_count=1,
            accuracy=1.0,
            results=[_result(case_id="1", matched=True, score=1.0)],
        ),
        [],
    )
    path = save_review_queue(queue, path=None)
    assert path.parent == tmp_path / "logs" / "review"
    assert path.name.startswith("queue_")
    assert path.exists()


def test_format_review_queue_summary():
    queue = build_review_queue(
        EvalReport(
            total=1,
            matched_count=0,
            accuracy=0.0,
            results=[_result(case_id="2", error="column count mismatch")],
        ),
        [Diagnosis(case_id="2", matched=False, confidence=0.8, error_types=["column_mismatch"])],
    )
    text = format_review_queue(queue)
    assert "needs_review=['2']" in text
    assert "[needs_review] id=2" in text
