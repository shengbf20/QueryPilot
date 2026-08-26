"""Process-local caches for metadata, prune, and query SQL/results."""

from querypilot.cache.keys import metadata_version, normalize_question
from querypilot.cache.metadata_cache import (
    get_metadata,
    get_pruned_schema,
    invalidate_metadata,
    invalidate_prune,
)
from querypilot.cache.metadata_cache import clear_caches as clear_metadata_caches
from querypilot.cache.query_cache import (
    CachedQuery,
    clear_query_cache,
    few_shot_version,
    get_cached_query,
    invalidate_query,
    make_query_key,
    put_cached_query,
)


def clear_caches() -> None:
    """Clear metadata, prune, and query caches."""
    clear_metadata_caches()
    clear_query_cache()


__all__ = [
    "CachedQuery",
    "clear_caches",
    "clear_query_cache",
    "few_shot_version",
    "get_cached_query",
    "get_metadata",
    "get_pruned_schema",
    "invalidate_metadata",
    "invalidate_prune",
    "invalidate_query",
    "make_query_key",
    "metadata_version",
    "normalize_question",
    "put_cached_query",
]
