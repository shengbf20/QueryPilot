"""Step 5: Extra paraphrased few-shots must not short-circuit Extra eval questions."""

from __future__ import annotations

from pathlib import Path

import yaml

from querypilot.agent.prompt import find_exact_few_shot, load_few_shots
from querypilot.config import get_settings
from querypilot.eval.dataset import load_qa_cases_many

ROOT = Path(__file__).resolve().parents[1]
EXTRA_PATHS = [
    ROOT / "data/extra/Q&A_easy.xlsx",
    ROOT / "data/extra/Q&A_medium.xlsx",
    ROOT / "data/extra/Q&A_hard.xlsx",
]
CANDIDATES = ROOT / "metadata/few_shots/candidates_extra.yaml"


def test_extra_eval_questions_have_no_exact_few_shot():
    shots = load_few_shots()
    assert shots, "examples.yaml should not be empty"
    hits = []
    for case in load_qa_cases_many(EXTRA_PATHS):
        if find_exact_few_shot(case.question, shots) is not None:
            hits.append(case.id)
    assert hits == [], f"Extra eval exact few-shot pollution: {hits}"


def test_approved_candidates_are_paraphrases_not_eval_verbatim():
    raw = yaml.safe_load(CANDIDATES.read_text(encoding="utf-8")) or {}
    candidates = list(raw.get("candidates") or [])
    approved = [c for c in candidates if str(c.get("status", "")).lower() == "approved"]
    assert 5 <= len(approved) <= 8, f"expect 5–8 approved candidates, got {len(approved)}"

    eval_questions = {
        " ".join(c.question.strip().split()) for c in load_qa_cases_many(EXTRA_PATHS)
    }
    for item in approved:
        q = " ".join(str(item["question"]).strip().split())
        assert q not in eval_questions, (
            f"candidate from {item.get('source_case_id')} uses Extra eval verbatim question"
        )
        assert str(item.get("sql", "")).strip()


def test_approved_candidates_present_in_examples_after_reflux():
    """After Step 5 reflux, paraphrases should live in the official few-shot corpus."""
    raw = yaml.safe_load(CANDIDATES.read_text(encoding="utf-8")) or {}
    approved = [
        c
        for c in (raw.get("candidates") or [])
        if str(c.get("status", "")).lower() == "approved"
    ]
    shots = load_few_shots()
    missing = []
    for item in approved:
        if find_exact_few_shot(str(item["question"]), shots) is None:
            missing.append(item.get("source_case_id"))
    assert missing == [], f"approved candidates not yet in examples.yaml: {missing}"


def test_candidates_path_under_metadata():
    assert CANDIDATES.exists()
    assert get_settings().metadata_dir.name == "metadata"
