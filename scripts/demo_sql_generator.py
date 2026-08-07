"""Demo Prompt + SQL generator on sample questions."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.agent import generate_sql
from querypilot.db import explain
from querypilot.metadata_engine import load_metadata

SAMPLES = [
    "有多少年龄大于30岁的女性客户？",
    "总资产超过100万的客户有多少人？",
    "买入交易额合计是多少？",
]


def main() -> int:
    metadata = load_metadata()
    for q in SAMPLES:
        print("=" * 60)
        print(f"Q: {q}")
        result = generate_sql(q, metadata=metadata, max_few_shots=2)
        print(f"tables: {result.pruned.tables if result.pruned else []}")
        print(f"uses_cte: {result.uses_cte}")
        print(f"rationale: {result.rationale}")
        print(f"SQL:\n{result.sql}")
        plan = explain(result.sql)
        print(f"EXPLAIN ok: {plan.ok}" + (f" err={plan.error}" if not plan.ok else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
