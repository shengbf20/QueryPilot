"""Tests for Execution Match comparison (phase-3 step 1)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from querypilot.db.connection import QueryResult
from querypilot.eval import compare_results, execution_match


def test_exact_match_same_table():
    result = compare_results(
        ["id", "name"],
        [(1, "a"), (2, "b")],
        ["id", "name"],
        [(1, "a"), (2, "b")],
    )
    assert result.matched
    assert result.score == 1.0
    assert result.reason == ""
    assert result.pred_rows == 2
    assert result.gold_rows == 2


def test_match_ignores_row_order_by_default():
    result = compare_results(
        ["id", "name"],
        [(2, "b"), (1, "a")],
        ["id", "name"],
        [(1, "a"), (2, "b")],
    )
    assert result.matched
    assert result.score == 1.0


def test_ordered_compare_detects_permutation():
    result = compare_results(
        ["id"],
        [(2,), (1,)],
        ["id"],
        [(1,), (2,)],
        ignore_order=False,
    )
    assert not result.matched
    assert result.score == 0.0
    assert "ordered" in result.reason


def test_column_name_alignment_reorders():
    result = compare_results(
        ["name", "id"],
        [("a", 1), ("b", 2)],
        ["id", "name"],
        [(1, "a"), (2, "b")],
    )
    assert result.matched
    assert set(result.aligned_columns) == {"id", "name"}


def test_ignore_column_names_positional():
    result = compare_results(
        ["x", "y"],
        [(1, "a")],
        ["id", "name"],
        [(1, "a")],
        ignore_column_names=True,
    )
    assert result.matched


def test_column_count_mismatch():
    result = compare_results(
        ["id"],
        [(1,)],
        ["id", "name"],
        [(1, "a")],
    )
    assert not result.matched
    assert result.score == 0.0
    assert "column count mismatch" in result.reason


def test_both_empty_match():
    result = compare_results(["id"], [], ["id"], [])
    assert result.matched
    assert result.score == 1.0


def test_value_mismatch_soft_score():
    result = compare_results(
        ["id"],
        [(1,), (2,), (3,)],
        ["id"],
        [(1,), (2,), (9,)],
    )
    assert not result.matched
    # multiset Jaccard: inter={1,2} union={1,2,3,9} → 2/4
    assert result.score == 0.5


def test_numeric_tolerance_match():
    result = compare_results(
        ["v"],
        [(1.0000001,)],
        ["v"],
        [(1.0,)],
        atol=1e-5,
        rtol=1e-5,
    )
    assert result.matched


def test_numeric_tolerance_mismatch():
    result = compare_results(
        ["v"],
        [(1.1,)],
        ["v"],
        [(1.0,)],
        atol=1e-6,
        rtol=1e-6,
    )
    assert not result.matched


def test_null_and_nan_treated_equal():
    result = compare_results(
        ["v"],
        [(None,), (float("nan"),)],
        ["v"],
        [(None,), (None,)],
    )
    # Two null-like rows vs two nulls → multiset of {None: 2}
    assert result.matched


def test_string_strip_normalization():
    result = compare_results(
        ["name"],
        [("  alice ",)],
        ["name"],
        [("alice",)],
    )
    assert result.matched


def test_duplicate_rows_multiset():
    ok = compare_results(["id"], [(1,), (1,)], ["id"], [(1,), (1,)])
    bad = compare_results(["id"], [(1,), (1,)], ["id"], [(1,)])
    assert ok.matched
    assert not bad.matched


def test_execution_match_query_result_objects():
    pred = QueryResult(columns=["id", "n"], rows=[(1, 10), (2, 20)], row_count=2)
    gold = QueryResult(columns=["n", "id"], rows=[(20, 2), (10, 1)], row_count=2)
    result = execution_match(pred, gold)
    assert result.matched
    assert result.score == 1.0


def test_positional_fallback_when_names_differ():
    result = compare_results(
        ["a", "b"],
        [(1, 2)],
        ["x", "y"],
        [(1, 2)],
    )
    assert result.matched


def test_one_sided_empty_is_mismatch():
    """P1: empty pred vs non-empty gold must not match (EX accuracy)."""
    result = compare_results(["id"], [], ["id"], [(1,)])
    assert not result.matched
    assert result.score == 0.0
    assert result.pred_rows == 0
    assert result.gold_rows == 1
    assert "row count" in result.reason


def test_ordered_compare_row_count_mismatch():
    """P1: ordered mode fails fast on unequal lengths."""
    result = compare_results(
        ["id"],
        [(1,)],
        ["id"],
        [(1,), (2,)],
        ignore_order=False,
    )
    assert not result.matched
    assert result.score == 0.0
    assert "row count" in result.reason


def test_column_name_case_and_whitespace_alignment():
    """P1: column alignment is case-insensitive and strips whitespace."""
    result = compare_results(
        [" ID ", "Name"],
        [(1, "a")],
        ["id", "name"],
        [(1, "a")],
    )
    assert result.matched
    assert result.aligned_columns == ("id", "name")


def test_decimal_and_thousands_separator_numeric_match():
    """P1: Decimal / formatted numeric strings compare as numbers."""
    result = compare_results(
        ["v", "w"],
        [(Decimal("1.5"), "1,000")],
        ["v", "w"],
        [(1.5, 1000)],
    )
    assert result.matched


def test_bool_does_not_match_integer_one():
    """P0: True must not equal 1 under EX (avoid Python bool==int leak)."""
    result = compare_results(["v"], [(True,)], ["v"], [(1,)])
    assert not result.matched
    assert result.score == 0.0


def test_soft_score_row_count_mismatch():
    """P1: partial overlap with unequal lengths uses multiset Jaccard."""
    result = compare_results(
        ["id"],
        [(1,), (2,)],
        ["id"],
        [(1,), (2,), (3,)],
    )
    assert not result.matched
    # inter=2, union=2+3-2=3 → 2/3
    assert result.score == pytest.approx(2 / 3)
    assert "row count" in result.reason


def test_execution_match_passes_tolerance_kwargs():
    """P1: execution_match forwards compare_results kwargs."""
    pred = QueryResult(columns=["v"], rows=[(1.0001,)], row_count=1)
    gold = QueryResult(columns=["v"], rows=[(1.0,)], row_count=1)
    assert not execution_match(pred, gold, atol=1e-6, rtol=0.0).matched
    assert execution_match(pred, gold, atol=1e-3, rtol=0.0).matched
