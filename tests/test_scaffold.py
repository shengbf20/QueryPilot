"""Smoke tests for project scaffold."""

from querypilot import __version__
from querypilot.config import get_settings


def test_version():
    assert __version__ == "0.1.0"


def test_settings_paths_exist():
    settings = get_settings()
    assert settings.root_dir.is_dir()
    assert settings.data_dir.is_dir()
    assert settings.metadata_dir.is_dir()
