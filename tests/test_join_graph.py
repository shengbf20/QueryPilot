"""Tests for join graph metadata."""

from querypilot.metadata_engine import load_join_graph, validate_join_graph_only

# Business keys allowed on edges tagged no_default_data_dt
_ALLOWED_NO_DATA_DT_KEYS = {"pty_id", "org_id"}

_EXPECTED_LOOKUP_COLUMNS = {
    ("ads_cust_info_d", "gender_cd", "500"),
    ("ads_cust_info_d", "edu_cd", "600"),
    ("ads_cust_info_d", "prof_cd", "700"),
    ("ads_cust_info_d", "cust_lvl_cd", "100"),
    ("ads_cust_info_d", "cust_status", "200"),
}


def test_join_graph_loads():
    graph = load_join_graph()
    assert len(graph.tables) == 8
    assert len(graph.edges) == 12
    assert len(graph.paths) == 8


def test_no_default_data_dt_rule_and_edge_keys():
    """Hard rule: tagged edges join only on pty_id/org_id, never data_dt."""
    graph = load_join_graph()
    assert "no_default_data_dt" in graph.rules
    assert "pty_id" in graph.rules["no_default_data_dt"].description
    assert "data_dt" in graph.rules["no_default_data_dt"].description

    tagged = [e for e in graph.edges.values() if "no_default_data_dt" in e.rules]
    assert tagged, "expected edges tagged with no_default_data_dt"
    for edge in tagged:
        keys = set(edge.join.keys()) | set(edge.join.values())
        assert "data_dt" not in keys, f"{edge.id} join includes data_dt: {edge.join}"
        assert keys <= _ALLOWED_NO_DATA_DT_KEYS, f"{edge.id} unexpected keys: {keys}"


def test_dim_public_edges_complete():
    graph = load_join_graph()
    lookup_edges = [e for e in graph.edges.values() if e.edge_type == "lookup"]
    assert len(lookup_edges) == 5
    code_types = {e.filter["code_type_id"] for e in lookup_edges}
    assert code_types == {"100", "200", "500", "600", "700"}


def test_dim_public_lookup_columns_match_coded_fields():
    """Each lookup edge maps a customer coded column with matching code_type_id."""
    graph = load_join_graph()
    actual = set()
    for edge in graph.edges.values():
        if edge.edge_type != "lookup" or edge.to_table != "dim_public":
            continue
        from_col = next(iter(edge.join))
        assert edge.join[from_col] == "code"
        actual.add((edge.from_table, from_col, edge.filter["code_type_id"]))
    assert actual == _EXPECTED_LOOKUP_COLUMNS


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
