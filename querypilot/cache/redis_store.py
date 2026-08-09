"""Optional Redis backend for query cache; import failure → caller falls back to memory."""

from __future__ import annotations

import json
from typing import Any


class RedisQueryStore:
    """Minimal get/set/clear using redis-py if installed."""

    def __init__(self, url: str, *, prefix: str = "querypilot:q:") -> None:
        import redis  # type: ignore[import-untyped]

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = prefix
        # ping once so misconfig fails fast and caller can fall back
        self._client.ping()

    def _k(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Any:
        from querypilot.cache.query_cache import CachedQuery

        raw = self._client.get(self._k(key))
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return CachedQuery.from_dict(data)

    def set(self, key: str, value: Any) -> None:
        from querypilot.cache.query_cache import CachedQuery

        entry = value if isinstance(value, CachedQuery) else CachedQuery.from_dict(value)
        self._client.set(self._k(key), json.dumps(entry.to_dict(), ensure_ascii=False))

    def clear(self) -> None:
        keys = list(self._client.scan_iter(match=f"{self._prefix}*"))
        if keys:
            self._client.delete(*keys)
