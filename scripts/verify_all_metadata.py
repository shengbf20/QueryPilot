"""Verify all metadata layers (Step 1 / 2 / 3) in one run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine.metadata_validator import validate_metadata_all


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify QueryPilot metadata (Step 1 + 2 + 3)")
    parser.add_argument("--skip-db", action="store_true", help="Skip dim_public DB checks")
    args = parser.parse_args()

    print("=== QueryPilot Unified Metadata Verification ===\n")
    result = validate_metadata_all(skip_db=args.skip_db)

    print("=== Section Summary ===")
    for name, section in result.sections.items():
        status = "PASS" if section.ok else "FAIL"
        print(f"  [{status}] {name}: {len(section.errors)} errors, {len(section.warnings)} warnings")

    if result.stats:
        print("\n=== Stats ===")
        for key, value in result.stats.items():
            print(f"  {key}: {value}")

    if result.warnings:
        print("\n=== Warnings ===")
        for warning in result.warnings:
            print(f"  [WARN] {warning}")

    if result.errors:
        print("\n=== Errors ===")
        for error in result.errors:
            print(f"  [FAIL] {error}")

    if result.ok:
        print("\n全部元数据层校验通过（Step 1 + 2 + 3 + cross-check）。")
        return 0

    print(f"\n校验失败，共 {len(result.errors)} 个错误。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
