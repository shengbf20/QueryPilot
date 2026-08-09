"""Phase-4 cache tests (step 2: metadata/prune; step 3 will extend)."""

from __future__ import annotations

import time

import pytest

from querypilot.cache.metadata_cache import (
    clear_caches,
    get_metadata,
    get_pruned_schema,
    invalidate_metadata,
    invalidate_prune,
)
from querypilot.metadata_engine.bundle import load_metadata, load_metadata_uncached


@pytest.fixture(autouse=True)
def _isolate_caches():
    clear_caches()
    yield
    clear_caches()


def test_metadata_cache_returns_same_object():
    a = get_metadata(load_db_codes=False)
    b = get_metadata(load_db_codes=False)
    assert a is b


def test_metadata_cache_separates_db_codes_flag():
    a = get_metadata(load_db_codes=False)
    b = get_metadata(load_db_codes=False, use_cache=False)
    # uncached path still returns equivalent tables; may be different object
    assert set(a.tables) == set(b.tables)
    c = load_metadata(load_db_codes=False)
    assert c is a  # default load_metadata uses cache


def test_metadata_use_cache_false_bypasses_store():
    a = get_metadata(load_db_codes=False, use_cache=True)
    b = get_metadata(load_db_codes=False, use_cache=False)
    assert a is not b
    assert set(a.tables) == set(b.tables)


def test_invalidate_metadata_forces_reload():
    a = get_metadata(load_db_codes=False)
    invalidate_metadata()
    b = get_metadata(load_db_codes=False)
    assert a is not b
    assert set(a.tables) == set(b.tables)


def test_metadata_second_load_much_faster_than_uncached():
    clear_caches()
    t0 = time.perf_counter()
    get_metadata(load_db_codes=False)
    first_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    get_metadata(load_db_codes=False)
    second_ms = (time.perf_counter() - t0) * 1000.0

    # Cached hit should be near-instant vs YAML parse
    assert second_ms < first_ms
    assert second_ms < 5.0


def test_prune_cache_returns_same_object():
    md = get_metadata(load_db_codes=False)
    q = "有多少年龄大于30岁的女性客户？"
    a = get_pruned_schema(q, md)
    b = get_pruned_schema("  有多少年龄大于30岁的女性客户？  ", md)
    assert a is b
    assert a.tables


def test_prune_use_cache_false_new_object():
    md = get_metadata(load_db_codes=False)
    q = "总资产超过100万的客户有多少人？"
    a = get_pruned_schema(q, md, use_cache=True)
    b = get_pruned_schema(q, md, use_cache=False)
    assert a is not b
    assert list(a.tables) == list(b.tables)


def test_invalidate_prune_clears_hits():
    md = get_metadata(load_db_codes=False)
    q = "买入交易额合计是多少？"
    a = get_pruned_schema(q, md)
    invalidate_prune()
    b = get_pruned_schema(q, md)
    assert a is not b
    assert list(a.tables) == list(b.tables)


def test_load_metadata_uncached_never_hits_store():
    a = load_metadata_uncached(load_db_codes=False)
    b = load_metadata_uncached(load_db_codes=False)
    assert a is not b
