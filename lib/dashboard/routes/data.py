"""Data management routes — inventory, download, and HTMX partials."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from data.store import MarketDataStore

log = logging.getLogger(__name__)
router = APIRouter()


def _data_dir(request: Request) -> Path:
    lib_dir: Path = request.app.state.lib_dir
    return lib_dir.parent / "data"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@router.get("/")
async def data_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("data.html", {"request": request})


# ---------------------------------------------------------------------------
# API — inventory
# ---------------------------------------------------------------------------

@router.get("/api/inventory")
async def get_inventory(request: Request) -> JSONResponse:
    try:
        store = MarketDataStore(_data_dir(request))
        inventory = store.inventory()
        return JSONResponse({"inventory": inventory})
    except Exception as exc:
        log.exception("Failed to get data inventory")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# API — download
# ---------------------------------------------------------------------------

def _run_download(
    data_dir: Path,
    exchange: str,
    symbol: str,
    timeframe: str,
    jobs: dict,
    job_id: str,
) -> None:
    """Download market data in a background thread."""
    try:
        if exchange == "oanda":
            from data.oanda_api import backfill_candles

            bars = backfill_candles(symbol, timeframe)
        else:
            from data.kraken_api import backfill_ohlcv

            bars = backfill_ohlcv(symbol, timeframe)

        store = MarketDataStore(data_dir)
        count = store.write_bars(bars, exchange, timeframe)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["rows"] = count
    except Exception as exc:
        log.exception("Download failed for %s %s %s", exchange, symbol, timeframe)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(exc)


@router.post("/api/download")
async def start_download(
    request: Request,
    exchange: str = Form("kraken"),
    symbols: str = Form("BTC/USD"),
    timeframe: str = Form("1h"),
) -> HTMLResponse:
    try:
        state = request.app.state.app_state
        jobs: dict = state.setdefault("download_jobs", {})
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

        if not symbol_list:
            return HTMLResponse(
                '<p class="text-red-400">No symbols provided</p>',
                status_code=400,
            )

        data_dir = _data_dir(request)
        for symbol in symbol_list:
            job_id = f"{exchange}_{symbol.replace('/', '_')}_{timeframe}"
            jobs[job_id] = {
                "status": "running",
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
            }
            thread = threading.Thread(
                target=_run_download,
                args=(data_dir, exchange, symbol, timeframe, jobs, job_id),
                daemon=True,
            )
            thread.start()

        sym_display = ", ".join(symbol_list)
        return HTMLResponse(
            f'<p class="text-green-400">Download started for '
            f'{exchange} {sym_display} {timeframe}...</p>'
        )
    except Exception as exc:
        log.exception("Failed to start download")
        return HTMLResponse(
            f'<p class="text-red-400">Error: {exc}</p>',
            status_code=500,
        )


# ---------------------------------------------------------------------------
# HTMX partial — inventory tree
# ---------------------------------------------------------------------------

def _build_inventory_tree(inventory: list[dict]) -> dict:
    """Group flat inventory list into {exchange: {symbol: [items]}}."""
    tree: dict[str, dict[str, list[dict]]] = {}
    for item in inventory:
        ex = item["exchange"]
        sym = item["symbol"]
        tree.setdefault(ex, {}).setdefault(sym, []).append(item)
    return tree


@router.get("/partials/inventory")
async def inventory_partial(request: Request):
    templates = request.app.state.templates
    try:
        store = MarketDataStore(_data_dir(request))
        inventory = store.inventory()
    except Exception:
        log.exception("Failed to get inventory for partial")
        inventory = []
    tree = _build_inventory_tree(inventory)
    return templates.TemplateResponse(
        "partials/data_inventory.html",
        {"request": request, "inventory": inventory, "tree": tree},
    )
