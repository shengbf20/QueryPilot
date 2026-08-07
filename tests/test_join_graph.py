"""Tests for join graph metadata."""

from querypilot.metadata_engine import load_join_graph, validate_join_graph_only


def test_join_graph_loads():
    graph = load_join_graph()
    assert len(graph.tables) == 8
    assert len(graph.edges) == 12
    assert len(graph.paths) == 8


def test_dim_public_edges_complete():
    graph = load_join_graph()
    lookup_edges = [e for e in graph.edges.values() if e.edge_type == "lookup"]
    assert len(lookup_edges) == 5
    code_types = {e.filter["code_type_id"] for e in lookup_edges}
    assert code_types == {"100", "200", "500", "600", "700"}


def test_customer_to_asset_path():
    graph = load_join_graph()
    path = graph.paths["customer_to_product_via_hold"]
    assert path.tables == ("ads_cust_info_d", "dwd_cust_hold_d", "dim_product")
    assert path.edges == ("customer_to_hold", "hold_to_product")


def test_neighbors():
    graph = load_join_graph()
    neighbors = graph.get_neighbors("ads_cust_info_d")
    assert "dws_cust_aset_d" in neighbors
    assert "dim_public" in neighbors
    assert "dim_branch" in neighbors


def test_join_graph_validation_passes():
    result = validate_join_graph_only()
    assert result.ok, result.errors
