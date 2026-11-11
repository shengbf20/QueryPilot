"""Built Chat UI is served by the API when frontend/dist exists."""

from __future__ import annotations

from fastapi.testclient import TestClient

from querypilot.api.app import create_app


def test_serves_built_ui(tmp_path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>QueryPilot</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr("querypilot.api.app.frontend_dist", lambda: dist)

    client = TestClient(create_app())
    page = client.get("/")
    assert page.status_code == 200
    assert "QueryPilot" in page.text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "QueryPilot" in client.get("/tables").text
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/missing").status_code == 404
    escaped = client.get("/../secret.txt")
    assert "secret" not in escaped.text


def test_missing_frontend_leaves_api_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("querypilot.api.app.frontend_dist", lambda: tmp_path / "absent")
    client = TestClient(create_app())
    assert client.get("/").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}
