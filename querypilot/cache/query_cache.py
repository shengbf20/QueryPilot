"""SQL / optional rows cache for repeated ask() questions (phase-4 step 3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from querypilot.cache.keys import metadata_version, normalize_question
from querypilot.cache.memory import LRUStore
from querypilot.config import get_settings

_store: LRUStore[str, "CachedQuery"] | None = None


@dataclass
class CachedQuery:
    """Fence-approved SQL payload; rows optional (L2 result cache)."""

    sql: str
    tables: list[str]
    rationale: str = ""
    uses_cte: bool = False
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    row_count: int = 0
    has_rows: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # tuples → lists for JSON/Redis
        d["rows"] = [list(r) for r in self.rows]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedQuery:
        rows_raw = data.get("rows") or []
        rows = [tuple(r) for r in rows_raw]
        return cls(
            sql=str(data.get("sql") or ""),
            tables=list(data.get("tables") or []),
            rationale=str(data.get("rationale") or ""),
            uses_cte=bool(data.get("uses_cte", False)),
            columns=list(data.get("columns") or []),
            rows=rows,
            row_count=int(data.get("row_count") or len(rows)),
            has_rows=bool(data.get("has_rows", False)),
        )


def few_shot_version(path: Path | None = None) -> str:
    """Fingerprint examples.yaml (size + mtime) for cache invalidation after reflux."""
    settings = get_settings()
    p = path or (settings.metadata_dir / "few_shots" / "examples.yaml")
    if not p.is_file():
        return "missing"
    try:
        st = p.stat()
    except OSError:
        return "missing"
    return f"{st.st_size}:{st.st_mtime_ns}"


def make_query_key(
    question: str,
    *,
    max_rows: int,
    max_few_shots: int,
    include_values: bool,
    allow_exact_few_shot: bool,
    cache_rows: bool,
) -> str:
    """生成查询缓存键"""
    settings = get_settings()
    meta_ver = metadata_version(settings.metadata_dir) # 获取元数据版本
    fs_ver = few_shot_version() # 获取few shot版本
    qn = normalize_question(question) # 规范化问题
    return (
        f"q={qn}|rows={max_rows}|fs={max_few_shots}|vals={int(include_values)}"
        f"|exact={int(allow_exact_few_shot)}|cacherows={int(cache_rows)}"
        f"|meta={meta_ver}|few={fs_ver}"
    )


def _resolve_use_cache(use_cache: bool | None) -> bool:
    if use_cache is not None:
        return bool(use_cache)
    return bool(get_settings().cache_enabled)


def _get_store() -> Any:
    global _store
    settings = get_settings()
    backend = (settings.cache_backend or "memory").strip().lower()
    if backend == "redis":
        try:
            from querypilot.cache.redis_store import RedisQueryStore

            return RedisQueryStore(settings.redis_url)
        except Exception:
            pass
    if _store is None:
        _store = LRUStore(maxsize=settings.query_cache_maxsize)
    return _store


def get_cached_query(key: str, *, use_cache: bool | None = None) -> CachedQuery | None:
    if not _resolve_use_cache(use_cache):
        return None
    hit = _get_store().get(key)
    if hit is None:
        return None
    if isinstance(hit, CachedQuery):
        return hit
    if isinstance(hit, dict):
        return CachedQuery.from_dict(hit)
    return None


def put_cached_query(key: str, entry: CachedQuery, *, use_cache: bool | None = None) -> None:
    if not _resolve_use_cache(use_cache):
        return
    if not entry.sql:
        return
    _get_store().set(key, entry)


def invalidate_query() -> None:
    global _store
    store = _get_store()
    store.clear()
    # Drop memory singleton so maxsize/backend changes apply next time
    if store is _store:
        _store = None


def clear_query_cache() -> None:
    invalidate_query()
