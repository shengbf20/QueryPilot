"""Tests for unified metadata validation (Step 3c)."""

import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import validate_metadata_all
from querypilot.metadata_engine.join_graph_loader import load_join_graph
from querypilot.metadata_engine.loader import load_all_tables


def test_validate_metadata_all_skip_db():
    result = validate_metadata_all(skip_db=True)
    assert result.sections.keys() == {"tables", "value_descriptors", "join_graph"}
    assert result.ok, result.errors


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_validate_metadata_all_with_db():
    result = validate_metadata_all()
    assert result.ok, result.errors
    assert result.stats.get("db_checked") is True
    assert result.stats.get("dim_public_codes", 0) > 0


def test_validate_metadata_all_cross_checks_and_graph_stats():
    """Assert graph size + coded columns have dim_public lookup edges with matching type."""
    result = validate_metadata_all(skip_db=True)
    assert result.ok, result.errors
    assert not any(e.startswith("[cross]") for e in result.errors)
    assert result.stats.get("edges") == 12
    assert result.stats.get("paths") == 8
    assert result.stats.get("tables") == 8

    tables = load_all_tables()
    graph = load_join_graph()
    lookup_by_col = {
        (edge.from_table, next(iter(edge.join))): edge
        for edge in graph.edges.values()
        if edge.edge_type == "lookup" and edge.to_table == "dim_public"
    }

    coded = [
        ("ads_cust_info_d", "gender_cd", "500"),
        ("ads_cust_info_d", "edu_cd", "600"),
        ("ads_cust_info_d", "prof_cd", "700"),
        ("ads_cust_info_d", "cust_lvl_cd", "100"),
        ("ads_cust_info_d", "cust_status", "200"),
    ]
    for table, column, code_type_id in coded:
        assert tables[table].get_column(column).code_type_id == code_type_id
        edge = lookup_by_col.get((table, column))
        assert edge is not None, f"missing lookup edge for {table}.{column}"
        assert edge.filter.get("code_type_id") == code_type_id
