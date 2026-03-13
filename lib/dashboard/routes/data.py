"""Data management routes — inventory, download, and HTMX partials."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

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
async def start_download(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        exchange = body.get("exchange", "kraken")
        symbol = body.get("symbol", "BTC/USD")
        timeframe = body.get("timeframe", "1h")

        state = request.app.state.app_state
        jobs: dict = state.setdefault("download_jobs", {})
        job_id = f"{exchange}_{symbol.replace('/', '_')}_{timeframe}"

        jobs[job_id] = {
            "status": "running",
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
        }

        thread = threading.Thread(
            target=_run_download,
            args=(_data_dir(request), exchange, symbol, timeframe, jobs, job_id),
            daemon=True,
        )
        thread.start()
        return JSONResponse({"job_id": job_id, "status": "started"})
    except Exception as exc:
        log.exception("Failed to start download")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# HTMX partial — inventory table
# ---------------------------------------------------------------------------

@router.get("/partials/inventory")
async def inventory_partial(request: Request):
    templates = request.app.state.templates
    try:
        store = MarketDataStore(_data_dir(request))
        inventory = store.inventory()
    except Exception:
        log.exception("Failed to get inventory for partial")
        inventory = []
    return templates.TemplateResponse(
        "partials/data_inventory.html",
        {"request": request, "inventory": inventory},
    )
