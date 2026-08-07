"""Tests for unified metadata bundle (Step 4)."""

import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import EXPECTED_TABLES, MetadataBundle, load_metadata


def test_load_metadata_structure():
    metadata = load_metadata(load_db_codes=False)
    assert isinstance(metadata, MetadataBundle)
    assert set(metadata.tables.keys()) == set(EXPECTED_TABLES)
    assert len(metadata.join_graph.edges) == 12
    assert metadata.engine is not None


def test_get_table_and_expand():
    metadata = load_metadata(load_db_codes=False)
    table = metadata.get_table("ads_cust_info_d")
    assert table.alias == "客户信息表"

    plan = metadata.expand_tables(["ads_cust_info_d", "dws_cust_aset_d"])
    assert plan.tables == ["ads_cust_info_d", "dws_cust_aset_d"]
    assert len(plan.join_clauses) == 1


def test_format_table_schema():
    metadata = load_metadata(load_db_codes=False)
    text = metadata.format_table_schema("ads_cust_info_d", include_values=False)
    assert "客户信息表" in text
    assert "gender_cd" in text


def test_validate_from_bundle():
    metadata = load_metadata(load_db_codes=False)
    result = metadata.validate(skip_db=True)
    assert result.ok, result.errors


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_load_metadata_with_db_codes():
    metadata = load_metadata()
    assert metadata.values.resolve("ads_cust_info_d", "gender_cd", "5000002") == "男"
    result = metadata.validate()
    assert result.ok, result.errors
