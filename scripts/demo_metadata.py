"""Demo / smoke test for load_metadata()."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine import load_metadata


def main() -> int:
    print("=== QueryPilot load_metadata() Demo ===\n")

    metadata = load_metadata()
    print(f"Tables:   {len(metadata.tables)}")
    print(f"Edges:    {len(metadata.join_graph.edges)}")
    print(f"Paths:    {len(metadata.join_graph.paths)}")
    print(f"Code types loaded: {len(metadata.values.codes_by_type)}")

    print("\n--- expand_tables demo ---")
    plan = metadata.expand_tables(["ads_cust_info_d", "dws_cust_aset_d", "dim_product"])
    print(f"  tables: {plan.tables}")
    print(f"  joins:  {len(plan.join_clauses)}")

    print("\n--- prompt schema snippet ---")
    print(metadata.format_table_schema("ads_cust_info_d", include_values=True)[:500])
    print("  ...")

    print("\n--- validate ---")
    result = metadata.validate()
    print(f"  ok={result.ok}, sections={list(result.sections.keys())}")

    print("\nload_metadata() OK.")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
