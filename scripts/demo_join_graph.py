"""Demo / verify join graph path finding."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine import create_join_graph_engine


def main() -> int:
    engine = create_join_graph_engine()

    print("=== QueryPilot Join Graph Engine Demo ===\n")

    demos = [
        ("ads_cust_info_d", "dws_cust_aset_d"),
        ("ads_cust_info_d", "dim_product"),
        ("dwd_cust_hold_d", "dim_product"),
    ]

    print("--- find_path ---")
    for start, end in demos:
        path = engine.find_path(start, end)
        if path is None:
            print(f"  {start} -> {end}: NOT FOUND")
        else:
            chain = " -> ".join(path.tables)
            print(f"  {start} -> {end}: {chain}")
            print(f"    edges: {[e.id for e in path.edges]}")

    print("\n--- expand_tables ---")
    seeds = ["ads_cust_info_d", "dws_cust_aset_d", "dim_product"]
    plan = engine.expand_tables(seeds)
    print(f"  seeds: {seeds}")
    print(f"  tables: {plan.tables}")
    print(f"  edges: {[e.id for e in plan.edges]}")
    for clause in plan.join_clauses:
        print(f"    {clause}")

    print("\n--- predefined path ---")
    predefined = engine.get_predefined_path("customer_asset_and_product_via_hold")
    if predefined:
        print(f"  tables: {' -> '.join(predefined.tables)}")
        print(f"  edges: {[e.id for e in predefined.edges]}")

    print("\nJoin graph engine OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
