"""Phase-4 cache tests: metadata/prune (step 2) + query SQL (step 3)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from querypilot.agent import ask
from querypilot.cache import clear_caches
from querypilot.cache.metadata_cache import (
    get_metadata,
    get_pruned_schema,
    invalidate_metadata,
    invalidate_prune,
)
from querypilot.cache.query_cache import (
    CachedQuery,
    get_cached_query,
    invalidate_query,
    make_query_key,
    put_cached_query,
)
from querypilot.config import get_settings
from querypilot.metadata_engine.bundle import load_metadata, load_metadata_uncached


requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)


@pytest.fixture(autouse=True)
def _isolate_caches():
    clear_caches()
    yield
    clear_caches()


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.calls = 0

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        content = (
            self._contents.pop(0)
            if self._contents
            else '{"sql":"SELECT 1","rationale":"","uses_cte":false}'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


class _FakeClient:
    def __init__(self, contents: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(contents))
        self.completions = self.chat.completions


# --- step 2: metadata / prune ---


def test_metadata_cache_returns_same_object():
    a = get_metadata(load_db_codes=False)
    b = get_metadata(load_db_codes=False)
    assert a is b


def test_metadata_cache_separates_db_codes_flag():
    a = get_metadata(load_db_codes=False)
    b = get_metadata(load_db_codes=False, use_cache=False)
    assert set(a.tables) == set(b.tables)
    c = load_metadata(load_db_codes=False)
    assert c is a


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


# --- step 3: query SQL cache ---


def test_query_key_includes_versions_and_normalize():
    k1 = make_query_key(
        "  客户有多少  ",
        max_rows=20,
        max_few_shots=2,
        include_values=False,
        allow_exact_few_shot=True,
        cache_rows=False,
    )
    k2 = make_query_key(
        "客户有多少",
        max_rows=20,
        max_few_shots=2,
        include_values=False,
        allow_exact_few_shot=True,
        cache_rows=False,
    )
    k3 = make_query_key(
        "客户有多少",
        max_rows=50,
        max_few_shots=2,
        include_values=False,
        allow_exact_few_shot=True,
        cache_rows=False,
    )
    assert k1 == k2
    assert k1 != k3
    assert "meta=" in k1 and "few=" in k1


def test_put_get_cached_query_roundtrip():
    key = make_query_key(
        "x",
        max_rows=10,
        max_few_shots=0,
        include_values=False,
        allow_exact_few_shot=False,
        cache_rows=False,
    )
    entry = CachedQuery(sql="SELECT 1 AS n", tables=["ads_cust_info_d"], rationale="t")
    put_cached_query(key, entry)
    hit = get_cached_query(key)
    assert hit is not None
    assert hit.sql == "SELECT 1 AS n"
    invalidate_query()
    assert get_cached_query(key) is None


@requires_db
def test_ask_query_cache_hit_skips_llm():
    md = get_metadata(load_db_codes=False)
    sql_json = (
        '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 30",'
        '"rationale":"统计","uses_cte":false}'
    )
    client = _FakeClient([sql_json])
    q = "年龄大于30的客户有多少_cache_test"
    cold = ask(
        q,
        metadata=md,
        client=client,
        include_values=False,
        max_few_shots=0,
        max_rows=20,
        allow_exact_few_shot=False,
    )
    assert cold.ok, cold.message
    assert cold.timing.cache_hit is False
    assert client.completions.calls == 1

    warm_client = _FakeClient([sql_json])
    warm = ask(
        q,
        metadata=md,
        client=warm_client,
        include_values=False,
        max_few_shots=0,
        max_rows=20,
        allow_exact_few_shot=False,
    )
    assert warm.ok, warm.message
    assert warm.timing.cache_hit is True
    assert warm_client.completions.calls == 0
    assert warm.sql == cold.sql
    assert warm.timing.generate_ms == 0.0
    assert warm.timing.total_ms < cold.timing.total_ms or warm.timing.total_ms < 200.0


@requires_db
def test_ask_no_cache_does_not_write_or_hit():
    md = get_metadata(load_db_codes=False)
    sql_json = (
        '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d",'
        '"rationale":"计数","uses_cte":false}'
    )
    client = _FakeClient([sql_json, sql_json])
    q = "客户总数_nocache_test"
    a = ask(
        q,
        metadata=md,
        client=client,
        include_values=False,
        max_few_shots=0,
        use_cache=False,
        allow_exact_few_shot=False,
    )
    b = ask(
        q,
        metadata=md,
        client=client,
        include_values=False,
        max_few_shots=0,
        use_cache=False,
        allow_exact_few_shot=False,
    )
    assert a.ok and b.ok
    assert a.timing.cache_hit is False
    assert b.timing.cache_hit is False
    assert client.completions.calls == 2


@requires_db
def test_ask_cache_rows_skips_execute_on_hit():
    md = get_metadata(load_db_codes=False)
    sql_json = (
        '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 40",'
        '"rationale":"统计","uses_cte":false}'
    )
    client = _FakeClient([sql_json])
    q = "年龄大于40的客户有多少_rows_cache"
    cold = ask(
        q,
        metadata=md,
        client=client,
        include_values=False,
        max_few_shots=0,
        allow_exact_few_shot=False,
        cache_rows=True,
    )
    assert cold.ok
    warm = ask(
        q,
        metadata=md,
        client=_FakeClient([sql_json]),
        include_values=False,
        max_few_shots=0,
        allow_exact_few_shot=False,
        cache_rows=True,
    )
    assert warm.ok
    assert warm.timing.cache_hit is True
    assert warm.extras.get("cache") == "rows"
    assert warm.rows == cold.rows
