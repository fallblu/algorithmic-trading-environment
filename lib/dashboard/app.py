"""FastAPI application factory for the trading dashboard."""

from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError:
    raise ImportError(
        "Dashboard requires fastapi and jinja2. "
        "Install with: pip install fastapi[all] jinja2"
    )

from .routes import overview, backtests, batch, portfolio, market_data, signals, stress_test, analysis, runner

_DASHBOARD_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _DASHBOARD_DIR / "templates"
_STATIC_DIR = _DASHBOARD_DIR / "static"


def create_app(env=None, data_dir: Path | str | None = None) -> FastAPI:
    """Create and configure the dashboard FastAPI application.

    Args:
        env: Optional environment/config object with a data_dir attribute.
        data_dir: Explicit path to the data directory. If provided, takes
            precedence over env.data_dir.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(title="Algorithmic Trading Environment", docs_url="/api/docs")

    # Resolve data directory
    if data_dir is not None:
        resolved_data_dir = Path(data_dir)
    elif env is not None and hasattr(env, "data_dir"):
        resolved_data_dir = Path(env.data_dir)
    else:
        resolved_data_dir = Path.cwd() / "data"

    app.state.data_dir = resolved_data_dir
    app.state.env = env

    # Templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates = templates

    # Static files — only mount if the directory exists
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Include route routers
    app.include_router(overview.router)
    app.include_router(backtests.router)
    app.include_router(batch.router)
    app.include_router(portfolio.router)
    app.include_router(market_data.router)
    app.include_router(signals.router)
    app.include_router(stress_test.router)
    app.include_router(analysis.router)
    app.include_router(runner.router)

    return app
