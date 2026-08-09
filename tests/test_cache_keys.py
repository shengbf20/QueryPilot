"""Tests for phase-4 cache key helpers."""

from querypilot.cache.keys import metadata_version, normalize_question
from querypilot.config import get_settings


def test_normalize_question_collapses_whitespace():
    assert normalize_question("  有多少  客户  \n") == "有多少 客户"
    assert normalize_question("") == ""


def test_metadata_version_stable_for_unchanged_tree():
    root = get_settings().metadata_dir
    a = metadata_version(root)
    b = metadata_version(root)
    assert a == b
    assert len(a) == 16
