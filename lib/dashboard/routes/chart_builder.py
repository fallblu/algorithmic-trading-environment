"""Chart builder routes — interactive chart composition and layout management."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from charts.builder import ChartBuilder, ChartConfig
from charts.registry import ChartRegistry
from data.store import MarketDataStore
from portfolio.storage import PortfolioStorage

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
# API — data inventory (exchanges / symbols / timeframes)
# ---------------------------------------------------------------------------

@router.get("/api/inventory")
async def get_inventory(request: Request) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    data_dir = lib_dir.parent / "data"
    try:
        store = MarketDataStore(data_dir)
        inventory = store.inventory()
        return JSONResponse({"inventory": inventory})
    except Exception as exc:
        log.exception("Failed to get data inventory")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# API — portfolio list (for overlay selector)
# ---------------------------------------------------------------------------

@router.get("/api/portfolios")
async def list_portfolios(request: Request) -> JSONResponse:
    state = request.app.state.app_state
    try:
        storage = PortfolioStorage(state)
        portfolios = [
            {"id": p.id, "name": p.name} for p in storage.list_all()
        ]
        return JSONResponse({"portfolios": portfolios})
    except Exception as exc:
        log.exception("Failed to list portfolios")
        return JSONResponse({"error": str(exc)}, status_code=500)


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

        start = None
        end = None
        if body.get("start"):
            start = datetime.fromisoformat(body["start"])
        if body.get("end"):
            end = datetime.fromisoformat(body["end"])

        df = store.read_dataframe(exchange, config.symbol, config.timeframe,
                                  start=start, end=end)
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
        fig = builder.build(config, df, equity_curve=equity_curve, fills=fills)
        fig_dict = json.loads(fig.to_json())
        return JSONResponse({
            "data": fig_dict["data"],
            "layout": fig_dict["layout"],
            "bars": len(df),
        })
    except Exception as exc:
        log.exception("Failed to build chart")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Series listing (indicators only — filter out chart types)
# ---------------------------------------------------------------------------

@router.get("/api/series")
async def list_series(request: Request) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    try:
        registry = ChartRegistry(lib_dir)
        all_series = registry.discover_all()
        hidden = {"price.candlestick", "price.line"}
        return JSONResponse({
            "series": [
                {
                    "key": info.key,
                    "name": info.name,
                    "type": info.series_type,
                    "subplot": info.subplot,
                    "description": info.description,
                    "source": info.source,
                }
                for info in all_series.values()
                if info.key not in hidden
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
