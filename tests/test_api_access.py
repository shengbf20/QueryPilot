"""Shared access keys gate /api/* when configured."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from querypilot.api.access import access_keys
from querypilot.api.app import create_app


def test_open_when_no_keys_configured() -> None:
    client = TestClient(create_app())
    assert client.get("/api/access").json() == {"required": False}
    assert client.post("/api/access").json() == {"ok": True}
    assert client.get("/health").status_code == 200


def test_rejects_missing_and_wrong_key(monkeypatch) -> None:
    monkeypatch.setattr("querypilot.api.access.access_keys", lambda: {"alpha", "beta"})
    client = TestClient(create_app())
    assert client.get("/api/access").json() == {"required": True}
    assert client.get("/health").status_code == 200
    denied = client.get("/api/catalog/tables")
    assert denied.status_code == 401
    assert denied.json()["detail"] == "访问密钥不正确"
    assert client.post("/api/access", headers={"X-Access-Key": "nope"}).status_code == 401
    assert client.post("/api/access", headers={"X-Access-Key": "beta"}).json() == {"ok": True}


def test_loads_keys_from_file_and_env(tmp_path, monkeypatch) -> None:
    path = tmp_path / "access_keys.txt"
    path.write_text("# comment\n\none\ntwo\n", encoding="utf-8")
    monkeypatch.setattr("querypilot.api.access.keys_path", lambda: path)
    monkeypatch.setenv("QUERYPPILOT_ACCESS_KEYS", "three, two")
    assert access_keys() == {"one", "two", "three"}


def test_missing_file_is_ignored(monkeypatch) -> None:
    monkeypatch.setattr("querypilot.api.access.keys_path", lambda: Path("does-not-exist.txt"))
    monkeypatch.delenv("QUERYPPILOT_ACCESS_KEYS", raising=False)
    assert access_keys() == set()
