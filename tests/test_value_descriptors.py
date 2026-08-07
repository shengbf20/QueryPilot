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


def test_format_for_prompt(sample_registry, sample_db):
    load_codes_from_db(sample_registry, sample_db)
    text = sample_registry.format_for_prompt("ads_cust_info_d", "gender_cd")
    assert "男(5000002)" in text
    assert "女(5000003)" in text


def test_config_validation_passes(sample_registry):
    result = validate_value_descriptor_config(sample_registry)
    assert result.ok, result.errors


def test_db_validation_passes(sample_registry, sample_db):
    load_codes_from_db(sample_registry, sample_db)
    result = validate_value_descriptors_against_db(sample_registry, sample_db)
    assert result.ok, result.errors


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
