"""Extra2 held-out isolation: no exact few-shot; no overlap with Extra36 questions."""

from __future__ import annotations

from pathlib import Path

from querypilot.agent.prompt import find_exact_few_shot, load_few_shots
from querypilot.eval.dataset import load_qa_cases

ROOT = Path(__file__).resolve().parents[1]
EXTRA2_ALL = ROOT / "data" / "extra2" / "Q&A_all.xlsx"
EXTRA36_ALL = ROOT / "data" / "extra" / "Q&A_all.xlsx"


def _norm(q: str) -> str:
    return " ".join(q.split())


def test_extra2_xlsx_shape_and_ids():
    cases = load_qa_cases(EXTRA2_ALL)
    assert len(cases) == 40
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))
    assert ids[:12] == [f"FE{i:02d}" for i in range(1, 13)]
    assert ids[12:28] == [f"FM{i:02d}" for i in range(1, 17)]
    assert ids[28:] == [f"FH{i:02d}" for i in range(1, 13)]
    assert all(c.extras.get("theme") for c in cases)
    assert sum(1 for c in cases if c.difficulty == "简单") == 12
    assert sum(1 for c in cases if c.difficulty == "中等") == 16
    assert sum(1 for c in cases if c.difficulty == "困难") == 12


def test_extra2_questions_have_no_exact_few_shot():
    shots = load_few_shots()
    hits: list[str] = []
    for case in load_qa_cases(EXTRA2_ALL):
        if find_exact_few_shot(case.question, shots) is not None:
            hits.append(case.id)
    assert hits == [], f"Extra2 exact few-shot hits: {hits}"


def test_extra2_questions_disjoint_from_extra36():
    e2 = {_norm(c.question) for c in load_qa_cases(EXTRA2_ALL)}
    e36 = {_norm(c.question) for c in load_qa_cases(EXTRA36_ALL)}
    overlap = sorted(e2 & e36)
    assert overlap == [], f"Extra2 intersect Extra36 questions: {overlap}"
