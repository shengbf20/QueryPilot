"""Tests for phase-3 baseline closeout helpers (step 6)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from querypilot.eval import (
    CaseEvalResult,
    Diagnosis,
    EvalReport,
    TimingInfo,
    build_baseline_summary,
    build_review_queue,
    format_baseline_markdown,
    load_baseline,
    save_baseline,
)
from querypilot.eval.baseline import TARGET_EX


def _result(**kwargs) -> CaseEvalResult:
    base = dict(
        case_id="1",
        question="q",
        matched=False,
        score=0.0,
        ask_ok=True,
        gold_ok=True,
        stage="done",
        timing=TimingInfo(total_ms=1000.0),
    )
    base.update(kwargs)
    return CaseEvalResult(**base)


def _report() -> EvalReport:
    return EvalReport(
        total=7,
        matched_count=1,
        accuracy=1 / 7,
        failed_ids=["2", "3", "4", "5", "6", "7"],
        p50_ms=3000.0,
        p95_ms=4200.0,
        mean_ms=3100.0,
        results=[
            _result(
                case_id="1",
                question="ok",
                matched=True,
                score=1.0,
                timing=TimingInfo(total_ms=2000),
            ),
            _result(
                case_id="2",
                question="年龄段资产分布",
                error="column count mismatch: pred=3 gold=2",
                timing=TimingInfo(total_ms=3000),
            ),
            _result(
                case_id="3",
                question="盈亏",
                error="Table not allowed: x",
                ask_ok=False,
                stage="l1",
                timing=TimingInfo(total_ms=4200),
            ),
        ]
        + [
            _result(
                case_id=str(i),
                question=f"q{i}",
                error="row multiset mismatch",
                timing=TimingInfo(total_ms=3100),
            )
            for i in (4, 5, 6, 7)
        ],
    )


def test_target_ex_is_ninety():
    assert TARGET_EX == pytest.approx(0.90)


def test_build_baseline_summary_gap_and_types():
    report = _report()
    diagnoses = [
        Diagnosis(
            case_id="2",
            matched=False,
            confidence=0.7,
            error_types=["column_mismatch", "aggregation"],
        ),
        Diagnosis(
            case_id="3",
            matched=False,
            confidence=0.4,
            error_types=["schema_hallucination", "agent_failed"],
        ),
    ]
    queue = build_review_queue(report, diagnoses)
    summary = build_baseline_summary(report, diagnoses=diagnoses, queue=queue)

    assert summary["total"] == 7
    assert summary["matched_count"] == 1
    assert summary["accuracy"] == pytest.approx(1 / 7)
    assert summary["target_ex"] == TARGET_EX
    assert summary["gap_to_target"] == pytest.approx(TARGET_EX - 1 / 7)
    # 90% of 7 = 6.3 → need 7 matched → 6 additional
    assert summary["additional_matches_needed"] == 6
    assert summary["failed_ids"] == ["2", "3", "4", "5", "6", "7"]
    assert summary["latency_ms"]["p50"] == 3000.0
    assert summary["error_type_counts"]["column_mismatch"] == 1
    assert summary["error_type_counts"]["schema_hallucination"] == 1
    assert summary["review_buckets"]["auto_pass"] == ["1"]
    assert "2" in summary["review_buckets"]["needs_review"]
    assert summary["review_buckets"]["bad_case_share"] == pytest.approx(5 / 7)
    assert summary["review_buckets"]["review_share"] == pytest.approx(1 / 7)


def test_failed_cases_detail_excludes_matched():
    """P0: failed_cases lists only unmatched rows with stage/error fields."""
    summary = build_baseline_summary(_report())
    ids = [c["case_id"] for c in summary["failed_cases"]]
    assert "1" not in ids
    assert ids == ["2", "3", "4", "5", "6", "7"]
    case3 = next(c for c in summary["failed_cases"] if c["case_id"] == "3")
    assert case3["stage"] == "l1"
    assert case3["ask_ok"] is False
    assert "Table not allowed" in case3["error"]
    assert case3["total_ms"] == 4200


def test_gap_zero_when_already_at_or_above_target():
    """P0: meeting/exceeding 90% must not demand more matches."""
    results = [
        _result(case_id=str(i), matched=True, score=1.0) for i in range(1, 10)
    ] + [_result(case_id="10", matched=False, score=0.0, error="x")]
    at_target = EvalReport(
        total=10,
        matched_count=9,
        accuracy=0.9,
        failed_ids=["10"],
        results=results,
        p50_ms=1.0,
        p95_ms=1.0,
        mean_ms=1.0,
    )
    summary = build_baseline_summary(at_target)
    assert summary["gap_to_target"] == pytest.approx(0.0)
    assert summary["additional_matches_needed"] == 0

    perfect = EvalReport(
        total=5,
        matched_count=5,
        accuracy=1.0,
        failed_ids=[],
        results=[_result(case_id=str(i), matched=True, score=1.0) for i in range(5)],
        p50_ms=1.0,
        p95_ms=1.0,
        mean_ms=1.0,
    )
    summary2 = build_baseline_summary(perfect)
    assert summary2["gap_to_target"] == 0.0
    assert summary2["additional_matches_needed"] == 0
    assert summary2["failed_cases"] == []


def test_error_type_counts_skip_matched_and_empty_types():
    """P1: matched diagnoses ignored; empty error_types → unknown."""
    report = EvalReport(
        total=2,
        matched_count=1,
        accuracy=0.5,
        failed_ids=["2"],
        results=[
            _result(case_id="1", matched=True, score=1.0),
            _result(case_id="2", error="row multiset mismatch"),
        ],
        p50_ms=1.0,
        p95_ms=1.0,
        mean_ms=1.0,
    )
    summary = build_baseline_summary(
        report,
        diagnoses=[
            Diagnosis(case_id="1", matched=True, error_types=["column_mismatch"]),
            Diagnosis(case_id="2", matched=False, error_types=[], confidence=0.2),
        ],
    )
    assert summary["error_type_counts"] == {"unknown": 1}


def test_custom_target_ex():
    """P1: target_ex override changes gap / additional_matches_needed."""
    report = EvalReport(
        total=4,
        matched_count=1,
        accuracy=0.25,
        failed_ids=["2", "3", "4"],
        results=[
            _result(case_id="1", matched=True, score=1.0),
            _result(case_id="2"),
            _result(case_id="3"),
            _result(case_id="4"),
        ],
        p50_ms=1.0,
        p95_ms=1.0,
        mean_ms=1.0,
    )
    summary = build_baseline_summary(report, target_ex=0.5)
    assert summary["target_ex"] == pytest.approx(0.5)
    assert summary["gap_to_target"] == pytest.approx(0.25)
    assert summary["additional_matches_needed"] == 1  # ceil(2)-1


def test_format_and_save_baseline(tmp_path: Path):
    summary = build_baseline_summary(_report())
    md = format_baseline_markdown(summary)
    assert "**EX**" in md
    assert "14.3%" in md
    assert "gap_to_target" in md
    assert "Failed cases" in md

    stem = tmp_path / "phase3_baseline"
    json_path, md_path = save_baseline(summary, stem=stem, report=_report())
    assert json_path.exists() and md_path.exists()
    loaded = load_baseline(json_path)
    assert loaded["matched_count"] == 1
    assert (tmp_path / "phase3_baseline_report.json").exists()
    assert "1/7" in md_path.read_text(encoding="utf-8")


def test_save_baseline_without_report_skips_report_file(tmp_path: Path):
    """P1: omit report → only summary json/md."""
    summary = build_baseline_summary(_report())
    stem = tmp_path / "baseline_only"
    save_baseline(summary, stem=stem, report=None)
    assert (tmp_path / "baseline_only.json").exists()
    assert (tmp_path / "baseline_only.md").exists()
    assert not (tmp_path / "baseline_only_report.json").exists()


def test_save_baseline_default_stem(tmp_path: Path, monkeypatch):
    """P1: stem=None writes under logs/eval_reports/phase3_baseline."""
    monkeypatch.setattr(
        "querypilot.eval.baseline.default_baseline_stem",
        lambda: tmp_path / "logs" / "eval_reports" / "phase3_baseline",
    )
    summary = build_baseline_summary(
        EvalReport(total=0, matched_count=0, accuracy=0.0),
        label="phase3_baseline",
    )
    json_path, md_path = save_baseline(summary, stem=None)
    assert json_path == tmp_path / "logs" / "eval_reports" / "phase3_baseline.json"
    assert md_path.exists()
    assert load_baseline(json_path)["label"] == "phase3_baseline"


def test_markdown_includes_review_buckets_when_present():
    """P1: markdown renders review bucket section when queue provided."""
    report = _report()
    diagnoses = [
        Diagnosis(case_id="2", matched=False, confidence=0.7, error_types=["column_mismatch"]),
    ]
    queue = build_review_queue(report, diagnoses)
    summary = build_baseline_summary(report, diagnoses=diagnoses, queue=queue)
    md = format_baseline_markdown(summary)
    assert "## Review buckets" in md
    assert "auto_pass:" in md
    assert "## Error type counts" in md
    assert "`column_mismatch`" in md


def test_baseline_empty_report():
    summary = build_baseline_summary(
        EvalReport(total=0, matched_count=0, accuracy=0.0)
    )
    assert summary["additional_matches_needed"] == 0
    assert summary["failed_cases"] == []
    assert summary["review_buckets"] is None
    assert "0.0%" in format_baseline_markdown(summary)


def test_baseline_eval_script_dry_run(tmp_path: Path):
    """P1: scripts/baseline_eval.py --dry-run-summary writes artifacts without LLM."""
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "baseline_eval.py"
    stem = tmp_path / "phase3_baseline_dry"
    import subprocess

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--dry-run-summary",
            "--stem",
            str(stem),
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert stem.with_suffix(".json").exists()
    assert stem.with_suffix(".md").exists()
    data = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["total"] == 0
    assert "baseline saved" in proc.stdout
