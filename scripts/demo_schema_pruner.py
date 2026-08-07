"""Demo Schema Pruner on sample marketing questions."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine import SchemaPruner, load_metadata

SAMPLES = [
    "筛选30岁以上的女性客户",
    "总资产超过100万的客户有多少",
    "买过基金产品的客户买入交易额",
    "客户持仓市值排名",
    "各营业部的客户数量",
    "客户入金与出金情况",
    "购买过某产品的30岁以上女性",
]


def main() -> int:
    metadata = load_metadata(load_db_codes=False)
    pruner = SchemaPruner(metadata)

    for q in SAMPLES:
        result = pruner.prune(q)
        print("=" * 60)
        print(f"Q: {q}")
        print(f"seeds: {result.seed_tables}")
        print(f"tables: {result.tables}")
        print(f"joins: {result.join_plan.join_clauses}")
        top = result.table_hits[:5]
        print("scores:", ", ".join(f"{h.table}={h.score}" for h in top))

    return 0


if __name__ == "__main__":
    sys.exit(main())
