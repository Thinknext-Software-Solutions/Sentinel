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

    SPA routing needs a catch-all that returns index.html for any path
    that is not /api/* and not a real static file. We mount the assets
    bundle at /assets, then register a catch-all that resolves to
    index.html so the React Router can take over client-side. If the
    static dir is missing (dev install before `npm run build:install`),
    we expose a JSON placeholder.
    """
    from pathlib import Path

    try:
        static_root = resources.files("sentinel.server").joinpath("static")
        static_path = Path(str(static_root))
    except (ModuleNotFoundError, FileNotFoundError):
        static_path = None

    index_html = static_path / "index.html" if static_path else None

    if static_path and index_html and index_html.is_file():
        from fastapi.responses import FileResponse

        assets_dir = static_path / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="spa-assets",
            )

        @app.get("/", include_in_schema=False)
        def _spa_root():
            return FileResponse(str(index_html))

        # Catch-all for SPA client routes (e.g. /projects, /runs/abc).
        # Excludes anything starting with /api or /assets via the route
        # registration order (those routers come first).
        @app.get("/{full_path:path}", include_in_schema=False)
        def _spa_fallback(full_path: str):
            # If a real static file at the top level exists, serve it
            # (favicon.svg, robots.txt, etc.)
            candidate = static_path / full_path
            if candidate.is_file() and static_path.resolve() in candidate.resolve().parents:
                return FileResponse(str(candidate))
            return FileResponse(str(index_html))

        return

    @app.get("/", include_in_schema=False)
    def _placeholder():
        return JSONResponse(
            {
                "ok": True,
                "service": "sentinel-studio",
                "version": __version__,
                "note": (
                    "Frontend SPA not bundled in this install. "
                    "Run `npm --prefix web run build:install` from the source "
                    "tree, or install a release that includes the prebuilt UI."
                ),
                "api_root": "/api",
                "docs": "/docs",
            }
        )
