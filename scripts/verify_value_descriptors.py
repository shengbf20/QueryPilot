"""Verify value descriptor mappings and dim_public integration."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.metadata_engine import load_value_descriptors, validate_value_descriptors


def main() -> int:
    print("=== QueryPilot Value Descriptor Verification ===\n")

    registry = load_value_descriptors()
    print(f"Loaded {len(registry.code_types)} code type mappings.")
    print(f"Loaded {sum(len(v) for v in registry.codes_by_type.values())} codes from dim_public.\n")

    print("=== Code Type Summary ===")
    for code_type_id, mapping in sorted(registry.code_types.items()):
        count = len(registry.get_codes_for_type(code_type_id))
        refs = ", ".join(f"{r.table}.{r.column}" for r in mapping.column_refs)
        print(f"  [{code_type_id}] {mapping.label}: {count} codes -> {refs}")

    print("\n=== Static Enums ===")
    for name in registry.static_enums:
        print(f"  {registry.format_static_for_prompt(name)}")

    print("\n=== Sample Resolves ===")
    samples = [
        ("ads_cust_info_d", "gender_cd", "5000002"),
        ("ads_cust_info_d", "edu_cd", "6000004"),
        ("ads_cust_info_d", "cust_lvl_cd", "1000003"),
    ]
    for table, column, code in samples:
        desc = registry.resolve(table, column, code)
        print(f"  {table}.{column} = {code} -> {desc}")

    print("\n=== Prompt Snippet (gender, top 5) ===")
    print(f"  {registry.format_for_prompt('ads_cust_info_d', 'gender_cd', max_items=5)}")

    print("\n=== Validation ===")
    result = validate_value_descriptors()
    for key, value in result.stats.items():
        print(f"  {key}: {value}")
    for warning in result.warnings:
        print(f"  [WARN] {warning}")
    for error in result.errors:
        print(f"  [FAIL] {error}")

    if result.ok:
        print("\nValue descriptor 校验通过。")
        return 0

    print(f"\n校验失败，共 {len(result.errors)} 个错误。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
