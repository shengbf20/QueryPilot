"""Tests for value descriptor loading and validation."""

from __future__ import annotations

import duckdb
import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine.value_descriptors import (
    load_codes_from_db,
    load_value_descriptor_config,
    load_value_descriptors,
)
from querypilot.metadata_engine.value_validator import (
    validate_value_descriptor_config,
    validate_value_descriptors_against_db,
)


@pytest.fixture
def sample_registry():
    return load_value_descriptor_config()


@pytest.fixture
def sample_db():
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE dim_public (
            code VARCHAR,
            code_type_id VARCHAR,
            "describe" VARCHAR
        )
        """
    )
    con.executemany(
        """
        INSERT INTO dim_public VALUES (?, ?, ?)
        """,
        [
            ("5000002", "500", "男"),
            ("5000003", "500", "女"),
            ("6000004", "600", "学士"),
            ("6000005", "600", "大专"),
            ("1000003", "100", "紫金理财金卡客户"),
            ("1000004", "100", "紫金理财银卡客户"),
            ("2000001", "200", "正常"),
            ("7000020", "700", "学生"),
            ("7000041", "700", "自由职业者"),
        ],
    )
    con.execute(
        """
        CREATE TABLE ads_cust_info_d (
            gender_cd VARCHAR,
            edu_cd VARCHAR,
            cust_lvl_cd VARCHAR,
            cust_status VARCHAR,
            prof_cd VARCHAR
        )
        """
    )
    con.executemany(
        """
        INSERT INTO ads_cust_info_d VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("5000002", "6000004", "1000003", "2000001", "7000020"),
            ("5000003", "6000005", "1000004", "2000001", "7000041"),
        ],
    )
    yield con
    con.close()


def test_config_loads_code_type_mappings(sample_registry):
    assert sample_registry.get_code_type_id("ads_cust_info_d", "gender_cd") == "500"
    assert sample_registry.get_code_type_id("ads_cust_info_d", "cust_status") == "200"
    assert sample_registry.get_code_type_id("ads_cust_info_d", "unknown") is None


def test_static_enum_resolve(sample_registry):
    assert sample_registry.resolve_static("sys_source", "nm") == "普通账户"
    assert sample_registry.resolve_static("ccy", "0") == "人民币"
    assert sample_registry.resolve_static("cust_type", "P") == "个人客户"


def test_db_codes_loaded(sample_registry, sample_db):
    load_codes_from_db(sample_registry, sample_db)
    assert sample_registry.resolve("ads_cust_info_d", "gender_cd", "5000002") == "男"
    assert len(sample_registry.get_codes_for_column("ads_cust_info_d", "gender_cd")) == 2


def test_resolve_requires_matching_code_type_id(sample_registry):
    """Codes are keyed by code_type_id; wrong type must not resolve via gender_cd."""
    # Same code string only under edu type (600), not gender (500)
    sample_registry.codes_by_type = {
        "600": {"5000002": "学士"},
        "500": {"5000003": "女"},
    }
    assert sample_registry.resolve("ads_cust_info_d", "gender_cd", "5000002") is None
    assert sample_registry.resolve("ads_cust_info_d", "edu_cd", "5000002") == "学士"
    assert sample_registry.resolve("ads_cust_info_d", "gender_cd", "5000003") == "女"
    # edu must not pick up a gender-only code
    assert sample_registry.resolve("ads_cust_info_d", "edu_cd", "5000003") is None


def test_format_for_prompt(sample_registry, sample_db):
    load_codes_from_db(sample_registry, sample_db)
    text = sample_registry.format_for_prompt("ads_cust_info_d", "gender_cd")
    assert "男(5000002)" in text
    assert "女(5000003)" in text


def test_format_for_prompt_pins_priority_codes(sample_registry):
    """Truncation must keep YAML priority_codes (e.g. 非公职 离/退休)."""
    assert sample_registry.priority_codes.get("700") == ["7000032"]
    # Many codes; without pinning, 7000032 alone may fall outside first 8 items
    other = {f"70000{i:02d}": f"工种{i}" for i in range(10, 30)}
    sample_registry.codes_by_type = {"700": {**other, "7000032": "非公职 离/退休"}}
    text = sample_registry.format_for_prompt(
        "ads_cust_info_d", "prof_cd", max_items=8
    )
    assert "7000032" in text
    assert "非公职 离/退休" in text
    body = text.split(": ", 1)[1]
    assert body.startswith("非公职 离/退休(7000032)")


def test_config_validation_passes(sample_registry):
    result = validate_value_descriptor_config(sample_registry)
    assert result.ok, result.errors


def test_db_validation_passes(sample_registry, sample_db):
    load_codes_from_db(sample_registry, sample_db)
    result = validate_value_descriptors_against_db(sample_registry, sample_db)
    assert result.ok, result.errors


def test_db_validation_fails_on_orphan_gender_cd(sample_registry, sample_db):
    """Customer codes missing from dim_public (for that code_type_id) must fail."""
    sample_db.execute(
        "INSERT INTO ads_cust_info_d VALUES (?, ?, ?, ?, ?)",
        ["9999999", "6000004", "1000003", "2000001", "7000020"],
    )
    load_codes_from_db(sample_registry, sample_db)
    result = validate_value_descriptors_against_db(sample_registry, sample_db)
    assert not result.ok
    assert any("gender_cd" in e and "not found in dim_public" in e for e in result.errors), (
        result.errors
    )


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_integration_with_project_db():
    registry = load_value_descriptors()
    assert registry.resolve("ads_cust_info_d", "gender_cd", "5000002") == "男"
    con = duckdb.connect(str(get_settings().db_path), read_only=True)
    try:
        result = validate_value_descriptors_against_db(registry, con)
    finally:
        con.close()
    assert result.ok, result.errors
