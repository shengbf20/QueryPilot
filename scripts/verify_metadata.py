"""Verify table metadata YAML files."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine import EXPECTED_TABLES, load_all_tables, validate_all


def main() -> int:
    print("=== QueryPilot Metadata Verification ===\n")

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
        print("\n全部元数据校验通过。")
        return 0

    print(f"\n校验失败，共 {len(result.errors)} 个错误。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
