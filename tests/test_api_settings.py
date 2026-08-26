"""GET/PUT /api/settings: mask key, update env, do not echo secrets."""

from __future__ import annotations

from fastapi.testclient import TestClient

from querypilot.api.app import create_app
from querypilot.api.llm_settings import mask_api_key, write_env_keys


def test_mask_api_key() -> None:
    assert mask_api_key("") == ""
    assert mask_api_key("short") == "••••"
    assert mask_api_key("sk-abcdefghijklmnop") == "sk-••••mnop"


def test_write_env_keys_upsert(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text("DEEPSEEK_MODEL=old\n# keep\nDUCKDB_PATH=db/x.duckdb\n", encoding="utf-8")
    write_env_keys({"DEEPSEEK_MODEL": "new", "DEEPSEEK_API_KEY": "sk-x"}, path)
    text = path.read_text(encoding="utf-8")
    assert "DEEPSEEK_MODEL=new" in text
    assert "DEEPSEEK_API_KEY=sk-x" in text
    assert "DUCKDB_PATH=db/x.duckdb" in text
    assert "# keep" in text


def test_settings_get_masks_key(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-abcdefghijklmnop")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "demo-model")
    client = TestClient(create_app())
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_key_set"] is True
    assert body["api_key_masked"] == "sk-••••mnop"
    assert "abcdefghijklmnop" not in resp.text
    assert body["base_url"] == "https://example.test/v1"
    assert body["model"] == "demo-model"


def test_settings_put_updates_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("querypilot.api.llm_settings.ROOT_DIR", tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-oldkeyxxxx")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://old.example/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "old-model")
    client = TestClient(create_app())
    resp = client.put(
        "/api/settings",
        json={
            "api_key": "sk-newkeyyyyyyyyy",
            "base_url": "https://new.example/v1/",
            "model": "new-model",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "new-model"
    assert body["base_url"] == "https://new.example/v1"
    assert "newkeyyyyyyyyy" not in resp.text
    assert body["api_key_masked"].endswith("yyyy")
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DEEPSEEK_MODEL=new-model" in env
    assert "sk-newkeyyyyyyyyy" in env
