"""Verify table metadata YAML files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine import EXPECTED_TABLES, load_all_tables, validate_all
from querypilot.metadata_engine.metadata_validator import validate_metadata_all


def _print_unified_result(result) -> int:
    print("=== Section Summary ===")
    for name, section in result.sections.items():
        status = "PASS" if section.ok else "FAIL"
        print(f"  [{status}] {name}: {len(section.errors)} errors, {len(section.warnings)} warnings")

    if result.stats:
        print("\n=== Stats ===")
        for key, value in result.stats.items():
            print(f"  {key}: {value}")

    for warning in result.warnings:
        print(f"  [WARN] {warning}")
    for error in result.errors:
        print(f"  [FAIL] {error}")

    if result.ok:
        print("\n全部元数据层校验通过（Step 1 + 2 + 3 + cross-check）。")
        return 0

    print(f"\n校验失败，共 {len(result.errors)} 个错误。")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify QueryPilot metadata")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run unified Step 1/2/3 validation",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="When using --all, skip dim_public DB checks",
    )
    args = parser.parse_args()

    if args.all:
        print("=== QueryPilot Unified Metadata Verification ===\n")
        result = validate_metadata_all(skip_db=args.skip_db)
        return _print_unified_result(result)

    print("=== QueryPilot Metadata Verification (Step 1 + 3 partial) ===\n")
    print("Tip: use --all for full Step 1/2/3 cross-validation.\n")

    tables = load_all_tables()
    print(f"Loaded {len(tables)} table metadata files.\n")

    print("=== Table Summary ===")
    for name in EXPECTED_TABLES:
        meta = tables[name]
        print(f"  [{meta.layer}] {name} ({meta.alias}) — {len(meta.columns)} columns")

    print("\n=== Validation ===")
    result = validate_all()

    for warning in result.warnings:
        print(f"  [WARN] {warning}")
    for error in result.errors:
        print(f"  [FAIL] {error}")

    if result.ok:
        print("\n表元数据与 Join-Graph 校验通过。")
        return 0

    print(f"\n校验失败，共 {len(result.errors)} 个错误。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
