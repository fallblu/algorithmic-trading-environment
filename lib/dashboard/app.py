"""Dashboard app — FastAPI factory for the trading dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.auth import TokenAuthMiddleware

log = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).parent
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"


def create_app(
    state: dict | None = None,
    auth_token: str = "",
    lib_dir: Path | None = None,
) -> FastAPI:
    """Create and configure the FastAPI dashboard application."""
    app = FastAPI(title="Trading Dashboard", docs_url=None, redoc_url=None)

    # Store shared state on app
    app.state.app_state = state or {}
    app.state.lib_dir = lib_dir or Path("lib")
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Auth middleware
    if auth_token:
        app.add_middleware(TokenAuthMiddleware, auth_token=auth_token)

    # Static files
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Register routes
    from dashboard.routes.portfolios import router as portfolios_router
    from dashboard.routes.editor import router as editor_router
    from dashboard.routes.chart_builder import router as chart_router
    from dashboard.routes.monitoring import router as monitoring_router
    from dashboard.routes.data import router as data_router

    app.include_router(portfolios_router)
    app.include_router(editor_router, prefix="/editor")
    app.include_router(chart_router, prefix="/charts")
    app.include_router(monitoring_router, prefix="/monitoring")
    app.include_router(data_router, prefix="/data")

    return app
