"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from querypilot.cache.query_cache import invalidate_query
from querypilot.config import get_settings


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(autouse=True)
def _isolate_query_cache():
    """Prevent SQL query-cache hits from leaking across tests."""
    invalidate_query()
    yield
    invalidate_query()
