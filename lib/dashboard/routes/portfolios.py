"""Portfolio routes — home page, CRUD, promote, and backtest endpoints."""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from portfolio.portfolio import ExecutionMode, Portfolio, StrategyAllocation
from portfolio.storage import PortfolioStorage

log = logging.getLogger(__name__)
router = APIRouter()

_PROMOTE_ORDER = [ExecutionMode.BACKTEST, ExecutionMode.PAPER, ExecutionMode.LIVE]


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@router.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse(url="/portfolios", status_code=302)


@router.get("/portfolios")
async def portfolios_page(request: Request):
    templates = request.app.state.templates
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    try:
        portfolios = [p.to_dict() for p in storage.list_all()]
    except Exception:
        log.exception("Failed to list portfolios")
        portfolios = []
    return templates.TemplateResponse(
        "portfolios.html",
        {"request": request, "portfolios": portfolios},
    )


# ---------------------------------------------------------------------------
# HTMX form handler — returns HTML partial for inline portfolio grid injection
# ---------------------------------------------------------------------------

@router.post("/portfolios", response_class=HTMLResponse)
async def create_portfolio_form(
    request: Request,
    name: str = Form(...),
    initial_cash: float = Form(100_000.0),
    exchange: str = Form("kraken"),
) -> HTMLResponse:
    templates = request.app.state.templates
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    try:
        portfolio = Portfolio(
            name=name,
            mode=ExecutionMode.BACKTEST,
            strategies=[],
            initial_cash=initial_cash,
            exchange=exchange,
        )
        storage.save(portfolio)
        return templates.TemplateResponse(
            "partials/portfolio_card.html",
            {"request": request, "portfolio": portfolio.to_dict()},
        )
    except Exception as exc:
        log.exception("Failed to create portfolio from form")
        return HTMLResponse(f"<div class='text-red-400 p-2'>{exc}</div>", status_code=400)


# ---------------------------------------------------------------------------
# CRUD API
# ---------------------------------------------------------------------------

@router.post("/api/portfolios")
async def create_portfolio(request: Request) -> JSONResponse:
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    try:
        body = await request.json()
        strategies = [
            StrategyAllocation(
                strategy_id=s.get("strategy_id", str(uuid.uuid4())),
                strategy_name=s["strategy_name"],
                allocation_pct=s.get("allocation_pct", 1.0),
                symbols=s.get("symbols", []),
                timeframe=s.get("timeframe", "1h"),
                params=s.get("params", {}),
                source_code=s.get("source_code"),
            )
            for s in body.get("strategies", [])
        ]
        portfolio = Portfolio(
            name=body.get("name", "Untitled Portfolio"),
            mode=ExecutionMode(body.get("mode", "backtest")),
            strategies=strategies,
            initial_cash=float(body.get("initial_cash", 10_000.0)),
            orchestration_code=body.get("orchestration_code"),
            orchestration_params=body.get("orchestration_params", {}),
            exchange=body.get("exchange", "kraken"),
            profile=body.get("profile", "default"),
        )
        storage.save(portfolio)
        return JSONResponse(portfolio.to_dict(), status_code=201)
    except Exception as exc:
        log.exception("Failed to create portfolio")
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/api/portfolios/{portfolio_id}")
async def get_portfolio(portfolio_id: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    try:
        portfolio = storage.get(portfolio_id)
        if portfolio is None:
            return JSONResponse({"error": "Portfolio not found"}, status_code=404)
        return JSONResponse(portfolio.to_dict())
    except Exception as exc:
        log.exception("Failed to get portfolio %s", portfolio_id)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.put("/api/portfolios/{portfolio_id}")
async def update_portfolio(portfolio_id: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    try:
        existing = storage.get(portfolio_id)
        if existing is None:
            return JSONResponse({"error": "Portfolio not found"}, status_code=404)
        body = await request.json()
        merged = {**existing.to_dict(), **body, "id": portfolio_id}
        portfolio = Portfolio.from_dict(merged)
        storage.save(portfolio)
        return JSONResponse(portfolio.to_dict())
    except Exception as exc:
        log.exception("Failed to update portfolio %s", portfolio_id)
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.delete("/api/portfolios/{portfolio_id}")
async def delete_portfolio(portfolio_id: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    try:
        if storage.delete(portfolio_id):
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "Portfolio not found"}, status_code=404)
    except Exception as exc:
        log.exception("Failed to delete portfolio %s", portfolio_id)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Promote mode  (BACKTEST -> PAPER -> LIVE)
# ---------------------------------------------------------------------------

@router.post("/api/portfolios/{portfolio_id}/promote")
async def promote_portfolio(portfolio_id: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    try:
        portfolio = storage.get(portfolio_id)
        if portfolio is None:
            return JSONResponse({"error": "Portfolio not found"}, status_code=404)
        idx = _PROMOTE_ORDER.index(portfolio.mode)
        if idx >= len(_PROMOTE_ORDER) - 1:
            return JSONResponse(
                {"error": "Portfolio is already in LIVE mode"}, status_code=400,
            )
        portfolio.mode = _PROMOTE_ORDER[idx + 1]
        storage.save(portfolio)
        return JSONResponse({"mode": portfolio.mode.value, "portfolio": portfolio.to_dict()})
    except Exception as exc:
        log.exception("Failed to promote portfolio %s", portfolio_id)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def _run_backtest(state: dict, portfolio: Portfolio, data_dir: Path) -> None:
    """Execute a backtest in a background thread."""
    from data.store import MarketDataStore
    from execution.backtest import BacktestContext

    results_store: dict = state.setdefault("backtest_results", {})
    pid = portfolio.id
    results_store[pid] = {
        "status": "running",
        "bars_processed": 0,
        "total_bars": 0,
        "result": None,
        "error": None,
    }

    def _progress(done: int, total: int) -> None:
        results_store[pid]["bars_processed"] = done
        results_store[pid]["total_bars"] = total

    try:
        store = MarketDataStore(data_dir)
        ctx = BacktestContext(portfolio, store)
        ctx.set_progress_callback(_progress)
        result = ctx.run()
        results_store[pid]["status"] = "completed"
        results_store[pid]["result"] = {
            "metrics": result.metrics,
            "errors": result.errors,
            "bars_processed": result.bars_processed,
            "total_bars": result.total_bars,
            "equity_curve": [
                {"ts": ts.isoformat(), "equity": eq}
                for ts, eq in result.equity_curve
            ],
            "fills": [
                {
                    "order_id": f.order_id,
                    "symbol": f.symbol,
                    "side": f.side.value,
                    "quantity": f.quantity,
                    "price": f.price,
                    "fee": f.fee,
                    "timestamp": f.timestamp.isoformat(),
                }
                for f in result.fills
            ],
        }
    except Exception:
        log.exception("Backtest failed for portfolio %s", pid)
        results_store[pid]["status"] = "error"
        results_store[pid]["error"] = traceback.format_exc()


@router.post("/api/backtest/run")
async def start_backtest(request: Request) -> JSONResponse:
    state = request.app.state.app_state
    lib_dir: Path = request.app.state.lib_dir
    data_dir = lib_dir.parent / "data"
    try:
        body = await request.json()
        portfolio_id = body.get("portfolio_id")
        if not portfolio_id:
            return JSONResponse({"error": "portfolio_id required"}, status_code=400)

        storage = PortfolioStorage(state)
        portfolio = storage.get(portfolio_id)
        if portfolio is None:
            return JSONResponse({"error": "Portfolio not found"}, status_code=404)

        thread = threading.Thread(
            target=_run_backtest,
            args=(state, portfolio, data_dir),
            daemon=True,
        )
        thread.start()
        return JSONResponse({"status": "started", "portfolio_id": portfolio_id})
    except Exception as exc:
        log.exception("Failed to start backtest")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/backtest/{portfolio_id}/status")
async def backtest_status(portfolio_id: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    results: dict = state.get("backtest_results", {})
    job = results.get(portfolio_id)
    if job is None:
        return JSONResponse({"error": "No backtest found"}, status_code=404)
    return JSONResponse({
        "status": job["status"],
        "bars_processed": job["bars_processed"],
        "total_bars": job["total_bars"],
        "error": job.get("error"),
        "result": job.get("result"),
    })
