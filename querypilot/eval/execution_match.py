"""Execution Match (EX): compare predicted vs gold query result sets."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from querypilot.eval.models import MatchResult

try:
    from querypilot.db.connection import QueryResult
except ImportError:  # pragma: no cover
    QueryResult = None  # type: ignore[misc, assignment]


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def normalize_cell(value: Any) -> Any:
    """Canonical non-numeric form (nulls / trimmed strings / bytes)."""
    if _is_null(value):
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return value.strip()
    return value


def cells_equal(left: Any, right: Any, *, atol: float, rtol: float) -> bool:
    if _is_null(left) and _is_null(right):
        return True
    # bool is a subclass of int; never treat True/False as 1/0 for EX.
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    lf = _to_float(left)
    rf = _to_float(right)
    if lf is not None and rf is not None:
        if not math.isfinite(lf) and not math.isfinite(rf):
            return True
        if not math.isfinite(lf) or not math.isfinite(rf):
            return False
        return math.isclose(lf, rf, rel_tol=rtol, abs_tol=atol)
    return normalize_cell(left) == normalize_cell(right)


def rows_equal(
    left: Sequence[Any],
    right: Sequence[Any],
    *,
    atol: float,
    rtol: float,
) -> bool:
    if len(left) != len(right):
        return False
    return all(cells_equal(a, b, atol=atol, rtol=rtol) for a, b in zip(left, right, strict=True))


def _as_table(
    columns: Sequence[str] | None,
    rows: Sequence[Sequence[Any]] | None,
    result: Any | None,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    if result is not None:
        if QueryResult is not None and isinstance(result, QueryResult):
            return list(result.columns), [tuple(r) for r in result.rows]
        if hasattr(result, "columns") and hasattr(result, "rows"):
            return list(result.columns), [tuple(r) for r in result.rows]
        raise TypeError(f"Unsupported result type: {type(result)!r}")
    cols = list(columns or [])
    out_rows = [tuple(r) for r in (rows or [])]
    return cols, out_rows


def _align_columns(
    pred_columns: list[str],
    gold_columns: list[str],
    *,
    ignore_column_names: bool,
) -> tuple[list[int] | None, list[int] | None, list[str], str | None]:
    """Return pred_index_order, gold_index_order, aligned names, or error reason."""
    if len(pred_columns) != len(gold_columns):
        return None, None, [], (
            f"column count mismatch: pred={len(pred_columns)} gold={len(gold_columns)}"
        )

    n = len(gold_columns)
    if n == 0:
        return [], [], [], None

    if ignore_column_names:
        return list(range(n)), list(range(n)), [f"c{i}" for i in range(n)], None

    gold_map = {c.strip().casefold(): i for i, c in enumerate(gold_columns)}
    if len(gold_map) != n:
        return list(range(n)), list(range(n)), list(gold_columns), None

    pred_order: list[int] = []
    gold_order: list[int] = []
    aligned: list[str] = []
    for i, name in enumerate(pred_columns):
        key = name.strip().casefold()
        j = gold_map.get(key)
        if j is None:
            return list(range(n)), list(range(n)), list(gold_columns), None
        pred_order.append(i)
        gold_order.append(j)
        aligned.append(gold_columns[j])
    return pred_order, gold_order, aligned, None


def _project(rows: list[tuple[Any, ...]], order: list[int]) -> list[tuple[Any, ...]]:
    if not order:
        return [() for _ in rows]
    return [tuple(row[i] for i in order) for row in rows]


def _sort_key(row: Sequence[Any]) -> tuple[Any, ...]:
    keys: list[Any] = []
    for value in row:
        if _is_null(value):
            keys.append((0, ""))
            continue
        number = _to_float(value)
        if number is not None and math.isfinite(number):
            keys.append((1, number))
        else:
            keys.append((2, repr(normalize_cell(value))))
    return tuple(keys)


def _multiset_match(
    pred_rows: list[tuple[Any, ...]],
    gold_rows: list[tuple[Any, ...]],
    *,
    atol: float,
    rtol: float,
) -> tuple[bool, float]:
    """Greedy multiset match under cell-wise tolerance; Jaccard soft score."""
    if not pred_rows and not gold_rows:
        return True, 1.0

    unused_gold = list(gold_rows)
    matched = 0
    for pred in pred_rows:
        hit_idx = None
        for j, gold in enumerate(unused_gold):
            if rows_equal(pred, gold, atol=atol, rtol=rtol):
                hit_idx = j
                break
        if hit_idx is None:
            continue
        matched += 1
        unused_gold.pop(hit_idx)

    union = len(pred_rows) + len(gold_rows) - matched
    score = (matched / union) if union else 1.0
    exact = matched == len(pred_rows) == len(gold_rows)
    return exact, score


def compare_results(
    pred_columns: Sequence[str] | None = None,
    pred_rows: Sequence[Sequence[Any]] | None = None,
    gold_columns: Sequence[str] | None = None,
    gold_rows: Sequence[Sequence[Any]] | None = None,
    *,
    pred: Any | None = None,
    gold: Any | None = None,
    ignore_order: bool = True,
    ignore_column_names: bool = False,
    atol: float = 1e-6,
    rtol: float = 1e-5,
) -> MatchResult:
    """
    Compare two execution result sets (Execution Match).

    Rules (defaults):
    - Align columns by name (case-insensitive); if names diverge, use positional order.
    - Null / NaN treated as equal; floats compared with ``math.isclose``.
    - Row order ignored by default (multiset equality via greedy matching).
    - Both empty → match.
    - ``score`` is 1.0 on full match, else multiset Jaccard under the same tolerance.
    """
    p_cols, p_rows = _as_table(pred_columns, pred_rows, pred)
    g_cols, g_rows = _as_table(gold_columns, gold_rows, gold)

    pred_idx, gold_idx, aligned, err = _align_columns(
        p_cols,
        g_cols,
        ignore_column_names=ignore_column_names,
    )
    if err is not None:
        return MatchResult(
            matched=False,
            score=0.0,
            reason=err,
            pred_rows=len(p_rows),
            gold_rows=len(g_rows),
        )

    assert pred_idx is not None and gold_idx is not None
    p_proj = _project(p_rows, pred_idx)
    g_proj = _project(g_rows, gold_idx)

    if not ignore_order:
        if len(p_proj) != len(g_proj):
            return MatchResult(
                matched=False,
                score=0.0,
                reason=f"row count pred={len(p_proj)} gold={len(g_proj)}",
                pred_rows=len(p_rows),
                gold_rows=len(g_rows),
                aligned_columns=tuple(aligned),
            )
        matched = all(
            rows_equal(a, b, atol=atol, rtol=rtol) for a, b in zip(p_proj, g_proj, strict=True)
        )
        return MatchResult(
            matched=matched,
            score=1.0 if matched else 0.0,
            reason="" if matched else "ordered row mismatch",
            pred_rows=len(p_rows),
            gold_rows=len(g_rows),
            aligned_columns=tuple(aligned),
        )

    # Stable traversal order (does not affect multiset semantics).
    p_sorted = sorted(p_proj, key=_sort_key)
    g_sorted = sorted(g_proj, key=_sort_key)
    exact, score = _multiset_match(p_sorted, g_sorted, atol=atol, rtol=rtol)
    if exact:
        return MatchResult(
            matched=True,
            score=1.0,
            reason="",
            pred_rows=len(p_rows),
            gold_rows=len(g_rows),
            aligned_columns=tuple(aligned),
        )

    reason_parts = []
    if len(p_rows) != len(g_rows):
        reason_parts.append(f"row count pred={len(p_rows)} gold={len(g_rows)}")
    else:
        reason_parts.append("row multiset mismatch")
    return MatchResult(
        matched=False,
        score=score,
        reason="; ".join(reason_parts),
        pred_rows=len(p_rows),
        gold_rows=len(g_rows),
        aligned_columns=tuple(aligned),
    )


def execution_match(
    pred: Any,
    gold: Any,
    **kwargs: Any,
) -> MatchResult:
    """Convenience wrapper: compare two QueryResult-like objects."""
    return compare_results(pred=pred, gold=gold, **kwargs)
