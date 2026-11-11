"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from querypilot.cache.query_cache import invalidate_query
from querypilot.config import get_settings


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(autouse=True)
def _disable_access_keys(monkeypatch):
    """A local access_keys.txt must not lock the test client."""
    monkeypatch.setenv("QUERYPPILOT_ACCESS_KEYS", "")
    monkeypatch.setattr("querypilot.api.access.keys_path", lambda: Path("access_keys.txt.missing"))


@pytest.fixture(autouse=True)
def _isolate_query_cache():
    """Prevent SQL query-cache hits from leaking across tests."""
    invalidate_query()
    yield
    invalidate_query()
