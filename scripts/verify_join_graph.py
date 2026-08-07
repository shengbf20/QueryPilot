"""Verify join graph metadata."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine import load_join_graph, validate_join_graph_only


def main() -> int:
    print("=== QueryPilot Join Graph Verification ===\n")

    graph = load_join_graph()
    print(f"Rules: {len(graph.rules)} | Tables: {len(graph.tables)} | "
          f"Edges: {len(graph.edges)} | Paths: {len(graph.paths)}\n")

    print("=== Join Rules ===")
    for rule in graph.rules.values():
        print(f"  [{rule.id}] {rule.description}")

    print("\n=== Edges ===")
    for edge in graph.edges.values():
        join_expr = ", ".join(f"{l}={r}" for l, r in edge.join.items())
        filt = f" filter={edge.filter}" if edge.filter else ""
        print(f"  {edge.id}: {edge.from_table} -> {edge.to_table} ({edge.edge_type}) ON {join_expr}{filt}")

    print("\n=== Paths ===")
    for path in graph.paths.values():
        print(f"  {path.id}: {' -> '.join(path.tables)}")
        print(f"    {path.description}")

    print("\n=== Validation ===")
    result = validate_join_graph_only()
    for warning in result.warnings:
        print(f"  [WARN] {warning}")
    for error in result.errors:
        print(f"  [FAIL] {error}")

    if result.ok:
        print("\nJoin graph 校验通过。")
        return 0

    print(f"\n校验失败，共 {len(result.errors)} 个错误。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
