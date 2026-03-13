"""Chart builder routes — interactive chart composition and layout management."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from charts.builder import ChartBuilder, ChartConfig
from charts.registry import ChartRegistry
from data.store import MarketDataStore

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@router.get("/")
async def charts_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("chart_builder.html", {"request": request})


# ---------------------------------------------------------------------------
# Build chart
# ---------------------------------------------------------------------------

@router.post("/api/build")
async def build_chart(request: Request) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    data_dir = lib_dir.parent / "data"
    try:
        body = await request.json()
        config = ChartConfig(
            symbol=body.get("symbol", "BTC/USD"),
            timeframe=body.get("timeframe", "1h"),
            main_chart=body.get("main_chart", "candlestick"),
            overlays=body.get("overlays", []),
            subplots=body.get("subplots", []),
            portfolio_id=body.get("portfolio_id"),
        )

        store = MarketDataStore(data_dir)
        exchange = body.get("exchange", "kraken")
        df = store.read_dataframe(exchange, config.symbol, config.timeframe)
        if df.empty:
            return JSONResponse(
                {"error": "No data available for the requested symbol/timeframe"},
                status_code=404,
            )
        df = df.set_index("timestamp")

        # Optionally attach equity curve and fills from backtest results
        equity_curve = None
        fills = None
        if config.portfolio_id:
            state = request.app.state.app_state
            bt_results: dict = state.get("backtest_results", {})
            job = bt_results.get(config.portfolio_id)
            if job and job.get("result"):
                result = job["result"]
                equity_curve = result.get("equity_curve")
                fills = result.get("fills")

        registry = ChartRegistry(lib_dir)
        registry.discover_all()
        builder = ChartBuilder(registry)
        html = builder.build(config, df, equity_curve=equity_curve, fills=fills)
        return JSONResponse({"html": html})
    except Exception as exc:
        log.exception("Failed to build chart")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Series listing
# ---------------------------------------------------------------------------

@router.get("/api/series")
async def list_series(request: Request) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    try:
        registry = ChartRegistry(lib_dir)
        all_series = registry.discover_all()
        return JSONResponse({
            "series": [
                {
                    "key": s.key,
                    "name": s.name,
                    "type": s.series_type,
                    "subplot": s.subplot,
                    "description": s.description,
                    "source": s.source,
                }
                for s in all_series.values()
            ],
        })
    except Exception as exc:
        log.exception("Failed to list chart series")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Layout persistence  (in-memory via app_state)
# ---------------------------------------------------------------------------

def _layouts(state: dict) -> dict:
    return state.setdefault("chart_layouts", {})


@router.post("/api/layouts")
async def save_layout(request: Request) -> JSONResponse:
    state = request.app.state.app_state
    try:
        body = await request.json()
        name = body.get("name")
        if not name:
            return JSONResponse({"error": "name is required"}, status_code=400)
        _layouts(state)[name] = body
        return JSONResponse({"ok": True, "name": name})
    except Exception as exc:
        log.exception("Failed to save layout")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/layouts")
async def list_layouts(request: Request) -> JSONResponse:
    state = request.app.state.app_state
    layouts = _layouts(state)
    return JSONResponse({"layouts": list(layouts.keys())})


@router.get("/api/layouts/{name}")
async def get_layout(name: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    layout = _layouts(state).get(name)
    if layout is None:
        return JSONResponse({"error": "Layout not found"}, status_code=404)
    return JSONResponse(layout)
