"""Monitoring routes — live status, backtest results, and HTMX partials."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from portfolio.storage import PortfolioStorage

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@router.get("/")
async def monitoring_page(request: Request):
    templates = request.app.state.templates
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    try:
        portfolios = [p.to_dict() for p in storage.list_all()]
    except Exception:
        log.exception("Failed to list portfolios for monitoring page")
        portfolios = []
    return templates.TemplateResponse(
        "monitoring.html",
        {"request": request, "portfolios": portfolios},
    )


# ---------------------------------------------------------------------------
# API — live status
# ---------------------------------------------------------------------------

@router.get("/api/status/{portfolio_id}")
async def live_status(portfolio_id: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    try:
        live_contexts: dict = state.get("live_contexts", {})
        ctx = live_contexts.get(portfolio_id)
        if ctx is None:
            return JSONResponse(
                {"error": "No live context for this portfolio"}, status_code=404,
            )
        broker = ctx.get_broker()
        account = broker.get_account()
        positions = [
            {
                "symbol": p.symbol,
                "side": p.side.value,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "unrealized_pnl": p.unrealized_pnl,
                "realized_pnl": p.realized_pnl,
            }
            for p in broker.position_manager.get_open_positions()
        ]
        fills = [
            {
                "order_id": f.order_id,
                "symbol": f.symbol,
                "side": f.side.value,
                "quantity": f.quantity,
                "price": f.price,
                "fee": f.fee,
                "timestamp": f.timestamp.isoformat(),
            }
            for f in getattr(broker, "fills", [])
        ]
        return JSONResponse({
            "portfolio_id": portfolio_id,
            "equity": getattr(account, "equity", 0.0),
            "cash": getattr(account, "cash", 0.0),
            "positions": positions,
            "fills": fills,
        })
    except Exception as exc:
        log.exception("Failed to get live status for %s", portfolio_id)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# API — backtest results
# ---------------------------------------------------------------------------

@router.get("/api/results")
async def list_results(request: Request) -> JSONResponse:
    state = request.app.state.app_state
    bt_results: dict = state.get("backtest_results", {})
    summary = []
    for pid, job in bt_results.items():
        entry: dict = {
            "portfolio_id": pid,
            "status": job.get("status", "unknown"),
            "bars_processed": job.get("bars_processed", 0),
            "total_bars": job.get("total_bars", 0),
        }
        result = job.get("result")
        if result:
            entry["metrics"] = result.get("metrics", {})
        summary.append(entry)
    return JSONResponse({"results": summary})


@router.get("/api/results/{portfolio_id}")
async def get_results(portfolio_id: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    bt_results: dict = state.get("backtest_results", {})
    job = bt_results.get(portfolio_id)
    if job is None:
        return JSONResponse({"error": "No results found"}, status_code=404)
    return JSONResponse({
        "portfolio_id": portfolio_id,
        "status": job.get("status", "unknown"),
        "bars_processed": job.get("bars_processed", 0),
        "total_bars": job.get("total_bars", 0),
        "error": job.get("error"),
        "result": job.get("result"),
    })


# ---------------------------------------------------------------------------
# HTMX partials
# ---------------------------------------------------------------------------

@router.get("/partials/positions/{portfolio_id}")
async def positions_partial(portfolio_id: str, request: Request):
    templates = request.app.state.templates
    state = request.app.state.app_state
    positions: list[dict] = []
    try:
        live_contexts: dict = state.get("live_contexts", {})
        ctx = live_contexts.get(portfolio_id)
        if ctx is not None:
            broker = ctx.get_broker()
            positions = [
                {
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "quantity": p.quantity,
                    "avg_entry_price": p.avg_entry_price,
                    "unrealized_pnl": p.unrealized_pnl,
                    "realized_pnl": p.realized_pnl,
                }
                for p in broker.position_manager.get_open_positions()
            ]
    except Exception:
        log.exception("Failed to get positions for %s", portfolio_id)
    return templates.TemplateResponse(
        "partials/positions.html",
        {"request": request, "positions": positions, "portfolio_id": portfolio_id},
    )


@router.get("/partials/fills/{portfolio_id}")
async def fills_partial(portfolio_id: str, request: Request):
    templates = request.app.state.templates
    state = request.app.state.app_state
    fills: list[dict] = []
    try:
        # Try live context first
        live_contexts: dict = state.get("live_contexts", {})
        ctx = live_contexts.get(portfolio_id)
        if ctx is not None:
            broker = ctx.get_broker()
            fills = [
                {
                    "order_id": f.order_id,
                    "symbol": f.symbol,
                    "side": f.side.value,
                    "quantity": f.quantity,
                    "price": f.price,
                    "fee": f.fee,
                    "timestamp": f.timestamp.isoformat(),
                }
                for f in getattr(broker, "fills", [])
            ]
        else:
            # Fall back to backtest results
            bt_results: dict = state.get("backtest_results", {})
            job = bt_results.get(portfolio_id)
            if job and job.get("result"):
                fills = job["result"].get("fills", [])
    except Exception:
        log.exception("Failed to get fills for %s", portfolio_id)
    return templates.TemplateResponse(
        "partials/fills.html",
        {"request": request, "fills": fills, "portfolio_id": portfolio_id},
    )


@router.get("/partials/metrics/{portfolio_id}")
async def metrics_partial(portfolio_id: str, request: Request):
    templates = request.app.state.templates
    state = request.app.state.app_state
    metrics: dict = {}
    try:
        bt_results: dict = state.get("backtest_results", {})
        job = bt_results.get(portfolio_id)
        if job and job.get("result"):
            metrics = job["result"].get("metrics", {})
    except Exception:
        log.exception("Failed to get metrics for %s", portfolio_id)
    return templates.TemplateResponse(
        "partials/metrics.html",
        {"request": request, "metrics": metrics, "portfolio_id": portfolio_id},
    )
