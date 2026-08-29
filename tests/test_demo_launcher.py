"""Demo launcher must stay ASCII so cmd.exe does not split UTF-8 as commands."""

from __future__ import annotations

from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "QueryPilot-demo"
BAT = DEMO / "启动演示.bat"


def test_demo_bat_exists() -> None:
    assert BAT.is_file()


def test_demo_bat_is_ascii() -> None:
    raw = BAT.read_bytes()
    raw.decode("ascii")
    assert b"\xef\xbb\xbf" not in raw[:4]


def test_demo_bat_wires_venv_and_server() -> None:
    text = BAT.read_text(encoding="ascii")
    assert "demo_server.py" in text
    assert "pip install" in text
    assert ".venv\\Scripts\\python.exe" in text
    assert "mshta" not in text
