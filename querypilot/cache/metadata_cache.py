"""Process-local caches for MetadataBundle and PrunedSchema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from querypilot.cache.keys import metadata_version, normalize_question
from querypilot.cache.memory import LRUStore, MemoryStore
from querypilot.config import get_settings

_bundle_store: MemoryStore[str, Any] = MemoryStore()
_prune_store: LRUStore[tuple[Any, ...], Any] = LRUStore(maxsize=256)


def _resolve_use_cache(use_cache: bool | None) -> bool:
    if use_cache is not None:
        return bool(use_cache)
    return bool(get_settings().cache_enabled)


def _default_paths_only(
    tables_dir: Path | None,
    join_graph_path: Path | None,
    value_config_path: Path | None,
    metrics_path: Path | None,
    db_con: duckdb.DuckDBPyConnection | None,
) -> bool:
    """Custom paths / injected connections are not cached (key would be ambiguous)."""
    return (
        tables_dir is None
        and join_graph_path is None
        and value_config_path is None
        and metrics_path is None
        and db_con is None
    )


def _bundle_key(*, load_db_codes: bool) -> str:
    settings = get_settings()
    ver = metadata_version(settings.metadata_dir)
    return f"{settings.metadata_dir.resolve()}|{ver}|db_codes={int(load_db_codes)}"


def get_metadata(
    *,
    tables_dir: Path | None = None,
    join_graph_path: Path | None = None,
    value_config_path: Path | None = None,
    metrics_path: Path | None = None,
    load_db_codes: bool = True,
    db_con: duckdb.DuckDBPyConnection | None = None,
    use_cache: bool | None = None,
):
    """Return MetadataBundle, optionally from process-local cache."""
    from querypilot.metadata_engine.bundle import load_metadata_uncached

    cache_on = _resolve_use_cache(use_cache) and _default_paths_only(
        tables_dir,
        join_graph_path,
        value_config_path,
        metrics_path,
        db_con,
    )
    if cache_on:
        key = _bundle_key(load_db_codes=load_db_codes)
        hit = _bundle_store.get(key)
        if hit is not None:
            return hit

    bundle = load_metadata_uncached(
        tables_dir=tables_dir,
        join_graph_path=join_graph_path,
        value_config_path=value_config_path,
        metrics_path=metrics_path,
        load_db_codes=load_db_codes,
        db_con=db_con,
    )
    if cache_on:
        _bundle_store.set(_bundle_key(load_db_codes=load_db_codes), bundle)
    return bundle


def get_pruned_schema(
    question: str,
    metadata,
    *,
    use_cache: bool | None = None,
    **kwargs: Any,
):
    """Prune with optional process-local LRU keyed by question + bundle identity."""
    from querypilot.metadata_engine.schema_pruner import SchemaPruner

    cache_on = _resolve_use_cache(use_cache)
    qn = normalize_question(question)
    # Stable kwargs key (defaults match SchemaPruner.prune)
    top_k = int(kwargs.get("top_k", 4))
    min_score = float(kwargs.get("min_score", 1.5))
    expand = bool(kwargs.get("expand", True))
    fallback_table = kwargs.get("fallback_table", "ads_cust_info_d")
    key = (qn, id(metadata), top_k, min_score, expand, fallback_table)

    if cache_on:
        hit = _prune_store.get(key)
        if hit is not None:
            return hit

    pruned = SchemaPruner(metadata).prune(
        question,
        top_k=top_k,
        min_score=min_score,
        expand=expand,
        fallback_table=fallback_table,
    )
    if cache_on:
        _prune_store.set(key, pruned)
    return pruned


def invalidate_metadata() -> None:
    _bundle_store.clear()


def invalidate_prune() -> None:
    _prune_store.clear()


def clear_caches() -> None:
    invalidate_metadata()
    invalidate_prune()
