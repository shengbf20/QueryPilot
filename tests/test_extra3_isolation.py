"""Extra3 isolation: shape, no overlap, safety_refuse gold, no exact few-shot."""

from __future__ import annotations

from pathlib import Path

from querypilot.agent.prompt import find_exact_few_shot, load_few_shots
from querypilot.eval.dataset import load_qa_cases
from querypilot.eval.safety_match import is_safety_refuse_case

ROOT = Path(__file__).resolve().parents[1]
EXTRA3_ALL = ROOT / "data" / "extra3" / "Q&A_all.xlsx"
EXTRA36_ALL = ROOT / "data" / "extra" / "Q&A_all.xlsx"
EXTRA2_ALL = ROOT / "data" / "extra2" / "Q&A_all.xlsx"
OFFICIAL = ROOT / "data" / "Q&A.xlsx"


def _norm(q: str) -> str:
    return " ".join(q.split())


def test_extra3_xlsx_shape_and_ids():
    cases = load_qa_cases(EXTRA3_ALL)
    assert len(cases) == 24
    ids = [c.id for c in cases]
    assert ids == [f"SE{i:02d}" for i in range(1, 9)] + [f"SM{i:02d}" for i in range(1, 9)] + [
        f"SH{i:02d}" for i in range(1, 9)
    ]
    assert all(c.extras.get("theme") for c in cases)
    assert all(str(c.extras.get("eval_mode")) == "safety_refuse" for c in cases)
    assert all(c.gold_sql.strip() == "SAFETY_REFUSE" for c in cases)
    assert all(is_safety_refuse_case(c) for c in cases)
    assert sum(1 for c in cases if c.difficulty == "简单") == 8
    assert sum(1 for c in cases if c.difficulty == "中等") == 8
    assert sum(1 for c in cases if c.difficulty == "困难") == 8


def test_extra3_questions_have_no_exact_few_shot():
    shots = load_few_shots()
    hits = [c.id for c in load_qa_cases(EXTRA3_ALL) if find_exact_few_shot(c.question, shots)]
    assert hits == [], hits


def test_extra3_questions_disjoint_from_other_sets():
    e3 = {_norm(c.question) for c in load_qa_cases(EXTRA3_ALL)}
    others: set[str] = set()
    for path in (OFFICIAL, EXTRA36_ALL, EXTRA2_ALL):
        if path.exists():
            others |= {_norm(c.question) for c in load_qa_cases(path)}
    overlap = sorted(e3 & others)
    assert overlap == [], overlap
