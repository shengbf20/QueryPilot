"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from querypilot.config import get_settings


@pytest.fixture(scope="session")
def settings():
    return get_settings()
