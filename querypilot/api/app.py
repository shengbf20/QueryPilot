"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from querypilot.api.catalog_routes import router as catalog_router
from querypilot.api.onboarding_routes import router as onboarding_router
from querypilot.api.routes import router

_BACKEND_ROOTS = {"api", "health", "docs", "redoc", "openapi.json"}


def frontend_dist() -> Path:
    """Built Chat UI. Absent until `npm run build` in frontend/."""
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _is_backend_path(path: str) -> bool:
    return path.split("/", 1)[0] in _BACKEND_ROOTS


def _file_in_dist(dist: Path, rel: str) -> Path | None:
    if not rel or rel.endswith("/"):
        return None
    root = dist.resolve()
    candidate = (root / rel).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    if candidate.is_file():
        return candidate
    return None


def _mount_frontend(app: FastAPI) -> None:
    dist = frontend_dist()
    index = dist / "index.html"
    if not index.is_file():
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        return FileResponse(index, media_type="text/html; charset=utf-8")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_spa(full_path: str) -> FileResponse:
        if _is_backend_path(full_path):
            raise HTTPException(status_code=404)
        found = _file_in_dist(dist, full_path)
        if found is not None:
            return FileResponse(found)
        return FileResponse(index, media_type="text/html; charset=utf-8")


def create_app() -> FastAPI:
    app = FastAPI(title="QueryPilot API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(catalog_router)
    app.include_router(onboarding_router)
    _mount_frontend(app)
    return app
