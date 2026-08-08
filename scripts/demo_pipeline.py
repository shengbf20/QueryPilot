"""End-to-end demo for the QueryPilot ask() pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.agent import ask
from querypilot.cli import format_pipeline_result
from querypilot.metadata_engine import load_metadata

SAMPLES = [
    "有多少年龄大于30岁的女性客户？",
    "总资产超过100万的客户有多少人？",
    "买入交易额合计是多少？",
    "各营业部的客户数量",
    "200岁以上的女性客户有多少",  # expect probe on zero/empty
]


def main() -> int:
    metadata = load_metadata()
    failed = 0
    for q in SAMPLES:
        print("=" * 60)
        result = ask(q, metadata=metadata, max_rows=10, max_few_shots=2)
        print(format_pipeline_result(result, max_print_rows=10))
        if not result.ok:
            failed += 1
    print("=" * 60)
    print(f"done: {len(SAMPLES) - failed}/{len(SAMPLES)} ok")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
