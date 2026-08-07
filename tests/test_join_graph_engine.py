"""Tests for join graph path finding engine."""

import pytest

from querypilot.metadata_engine import create_join_graph_engine, load_join_graph
from querypilot.metadata_engine.join_graph import JoinGraphEngine


@pytest.fixture
def engine() -> JoinGraphEngine:
    return create_join_graph_engine(load_join_graph())


def test_find_path_customer_to_asset(engine):
    path = engine.find_path("ads_cust_info_d", "dws_cust_aset_d")
    assert path is not None
    assert path.tables == ("ads_cust_info_d", "dws_cust_aset_d")
    assert len(path.edges) == 1
    assert path.edges[0].id == "customer_to_asset"


def test_find_path_customer_to_product_via_hold(engine):
    path = engine.find_path("ads_cust_info_d", "dim_product")
    assert path is not None
    assert path.tables == ("ads_cust_info_d", "dwd_cust_hold_d", "dim_product")
    assert [e.id for e in path.edges] == ["customer_to_hold", "hold_to_product"]


def test_find_path_same_table(engine):
    path = engine.find_path("dim_product", "dim_product")
    assert path.tables == ("dim_product",)
    assert path.edges == ()


def test_find_path_unknown_table(engine):
    with pytest.raises(KeyError):
        engine.find_path("ads_cust_info_d", "missing_table")


def test_expand_tables_single(engine):
    plan = engine.expand_tables(["ads_cust_info_d"])
    assert plan.tables == ["ads_cust_info_d"]
    assert plan.edges == []


def test_expand_tables_customer_asset_product(engine):
    plan = engine.expand_tables(["ads_cust_info_d", "dws_cust_aset_d", "dim_product"])
    assert plan.tables[0] == "ads_cust_info_d"
    assert set(plan.tables) == {"ads_cust_info_d", "dws_cust_aset_d", "dwd_cust_hold_d", "dim_product"}
    assert {e.id for e in plan.edges} == {"customer_to_asset", "customer_to_hold", "hold_to_product"}
    assert len(plan.join_clauses) == 3


def test_join_clause_dim_public_filter(engine):
    graph = load_join_graph()
    edge = graph.edges["customer_gender_lookup"]
    clause = engine.get_join_clause(
        edge,
        from_table="ads_cust_info_d",
        to_table="dim_public",
    )
    assert "gender_cd = gender_lookup.code" in clause
    assert "gender_lookup.code_type_id = '500'" in clause


def test_predefined_path(engine):
    path = engine.get_predefined_path("customer_to_product_via_tran")
    assert path is not None
    assert path.tables == ("ads_cust_info_d", "dwd_cust_tran_d", "dim_product")


def test_expand_hold_and_product_only(engine):
    plan = engine.expand_tables(["dwd_cust_hold_d", "dim_product"])
    assert plan.tables == ["dwd_cust_hold_d", "dim_product"]
    assert len(plan.edges) == 1
    assert plan.edges[0].id == "hold_to_product"
