"""Build a small Extra2 fail-set xlsx for post-fix smoke eval."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from querypilot.eval.dataset import load_qa_cases

ROOT = Path(__file__).resolve().parent
ALL = ROOT / "Q&A_all.xlsx"
OUT = ROOT / "Q&A_failset.xlsx"
# Union of Extra2-A/B failures before P0-P1 fix
FAIL_IDS = ["FE01", "FE09", "FM05", "FM07", "FM08", "FH02", "FH04", "FH12"]


def main() -> None:
    by_id = {c.id: c for c in load_qa_cases(ALL)}
    wb = Workbook()
    ws = wb.active
    ws.title = "Q&A"
    ws.append(["序号", "问题", "SQL", "难度", "theme"])
    for cid in FAIL_IDS:
        c = by_id[cid]
        ws.append(
            [
                c.id,
                c.question,
                c.gold_sql,
                c.difficulty or "",
                c.extras.get("theme", ""),
            ]
        )
    wb.save(OUT)
    print(f"wrote {OUT} n={len(FAIL_IDS)}")


if __name__ == "__main__":
    main()
