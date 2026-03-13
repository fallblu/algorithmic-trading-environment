"""Data management routes — inventory and download."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter()


def _get_store(request: Request):
    from data.store import MarketDataStore
    lib_dir = request.app.state.lib_dir
    data_dir = lib_dir.parent / "data"
    return MarketDataStore(data_dir)


@router.get("/")
async def data_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("data.html", {"request": request})


@router.get("/api/inventory")
async def get_inventory(request: Request):
    try:
        store = _get_store(request)
        inventory = store.inventory()
        return JSONResponse({"inventory": inventory})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/download")
async def start_download(request: Request):
    try:
        body = await request.json()
        exchange = body.get("exchange", "kraken")
        symbol = body.get("symbol", "BTC/USD")
        timeframe = body.get("timeframe", "1h")
        days = int(body.get("days", 30))

        app_state = request.app.state.app_state
        job_id = f"download_{exchange}_{symbol}_{timeframe}"

        if "download_jobs" not in app_state:
            app_state["download_jobs"] = {}

        app_state["download_jobs"][job_id] = {
            "status": "running",
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
        }

        def run_download():
            try:
                store = MarketDataStore(request.app.state.lib_dir.parent / "data")
                if exchange == "oanda":
                    from data.oanda_api import OandaAPI
                    api = OandaAPI(api_key="", account_id="")
                    bars = api.backfill_candles(symbol, timeframe, days=days)
                else:
                    from data.kraken_api import KrakenAPI
                    api = KrakenAPI()
                    bars = api.backfill_ohlcv(symbol, timeframe, days=days)

                from data.store import MarketDataStore
                store.write_bars(exchange, symbol, timeframe, bars)
                app_state["download_jobs"][job_id]["status"] = "complete"
                app_state["download_jobs"][job_id]["rows"] = len(bars)
            except Exception as e:
                app_state["download_jobs"][job_id]["status"] = "error"
                app_state["download_jobs"][job_id]["error"] = str(e)

        thread = threading.Thread(target=run_download, daemon=True)
        thread.start()

        return JSONResponse({"job_id": job_id, "status": "started"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/download/{job_id}/status")
async def download_status(job_id: str, request: Request):
    app_state = request.app.state.app_state
    jobs = app_state.get("download_jobs", {})
    job = jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse(job)


@router.get("/partials/inventory")
async def inventory_partial(request: Request):
    try:
        store = _get_store(request)
        inventory = store.inventory()
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "partials/data_inventory.html",
            {"request": request, "inventory": inventory},
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
