"""Demo app: Chat UI + /api on one port. Local copy; not the main-repo factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from querypilot.api.routes import router
from querypilot.config import ROOT_DIR

UI_DIR = ROOT_DIR / "ui"


def create_app() -> FastAPI:
    app = FastAPI(title="QueryPilot Demo", version="0.1.0")
    app.include_router(router)
    if UI_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
    return app
