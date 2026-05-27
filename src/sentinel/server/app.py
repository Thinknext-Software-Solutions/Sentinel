"""FastAPI app for Sentinel Studio.

Single ASGI app:
  /api/auth/*        login, logout, current-user
  /api/users/*       admin user management
  /api/projects/*    project CRUD
  /api/projects/{id}/runs  trigger run
  /api/runs/*        run history + detail
  /api/health        liveness probe
  /                  React SPA (in 0.2.x; not present yet)

Auth: session cookie (sentinel_session). No CSRF in v1; we rely on
SameSite=Lax + the cookie not being readable from JS. CORS is disabled
for the SPA path; the SPA is served from the same origin so no preflight
is needed. When developing the SPA on a separate dev server (Vite on
5173), set SENTINEL_DEV_CORS_ORIGIN to enable a single-origin CORS shim.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .api import auth as auth_api
from .api import projects as projects_api
from .api import runs as runs_api
from .api import users as users_api
from .db import Base, get_engine
from .runner import shutdown_pool


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Create tables on first boot. For Alembic-managed migrations later,
    # this stays as a safety net for fresh installs that skip migrate.
    Base.metadata.create_all(bind=get_engine())
    try:
        yield
    finally:
        shutdown_pool()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sentinel Studio",
        version=__version__,
        description="Self-hosted multi-user UI for sentinel-agent.",
        lifespan=_lifespan,
    )

    dev_origin = os.environ.get("SENTINEL_DEV_CORS_ORIGIN")
    if dev_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[dev_origin],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(auth_api.router)
    app.include_router(users_api.router)
    app.include_router(projects_api.router)
    app.include_router(runs_api.router)

    @app.get("/api/health", tags=["meta"])
    def _health():
        return {"status": "ok", "version": __version__}

    _mount_spa_if_present(app)

    return app


def _mount_spa_if_present(app: FastAPI) -> None:
    """Mount the pre-built React SPA if its static assets are packaged.

    The SPA is built into src/sentinel/server/static/ at release time
    (next session). If the dir is missing (dev install before frontend
    build), we expose a placeholder at / so the API stays usable.
    """
    try:
        static_root = resources.files("sentinel.server").joinpath("static")
        static_path = str(static_root)
    except (ModuleNotFoundError, FileNotFoundError):
        static_path = None

    if static_path and (static_root.joinpath("index.html").is_file()):
        app.mount("/", StaticFiles(directory=static_path, html=True), name="spa")
        return

    @app.get("/", include_in_schema=False)
    def _placeholder():
        return JSONResponse(
            {
                "ok": True,
                "service": "sentinel-studio",
                "version": __version__,
                "note": "Frontend SPA not bundled in this install. API is live at /api/*.",
                "docs": "/docs",
            }
        )
