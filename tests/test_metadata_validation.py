"""Tests for unified metadata validation (Step 3c)."""

import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import validate_metadata_all


def test_validate_metadata_all_skip_db():
    result = validate_metadata_all(skip_db=True)
    assert result.sections.keys() == {"tables", "value_descriptors", "join_graph"}
    assert result.ok, result.errors


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_validate_metadata_all_with_db():
    result = validate_metadata_all()
    assert result.ok, result.errors
    assert result.stats.get("db_checked") is True
    assert result.stats.get("dim_public_codes", 0) > 0
