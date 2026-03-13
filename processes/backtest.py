"""Backtest process — run a portfolio backtest as an isolated Persistra job."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from persistra import process, state

log = logging.getLogger(__name__)


@process("job")
def backtest(portfolio_id: str = "", start: str = "", end: str = ""):
    """Run a portfolio backtest.

    Parameters:
        portfolio_id: The portfolio ID to backtest.
        start: Start date (ISO format, optional).
        end: End date (ISO format, optional).
    """
    from data.store import MarketDataStore
    from execution.backtest import BacktestContext
    from portfolio.portfolio import Portfolio

    s = state()

    # Load portfolio
    portfolios = s.get("portfolios", {})
    if portfolio_id not in portfolios:
        log.error("Portfolio %s not found", portfolio_id)
        return

    portfolio = Portfolio.from_dict(portfolios[portfolio_id])

    # Parse dates
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None

    # Set up data store
    base_dir = Path("data")
    store = MarketDataStore(base_dir)

    # Track progress in state
    def on_progress(bars_done: int, total: int):
        results = s.get("backtest_results", {})
        if portfolio_id in results:
            results[portfolio_id]["progress"] = {
                "bars_done": bars_done,
                "total": total,
                "pct": round(bars_done / total * 100, 1) if total > 0 else 0,
            }
            s["backtest_results"] = results

    # Run backtest
    ctx = BacktestContext(portfolio, store)
    ctx.set_progress_callback(on_progress)
    result = ctx.run(start=start_dt, end=end_dt)

    # Store results
    results = s.get("backtest_results", {})
    results[portfolio_id] = {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.name,
        "metrics": result.metrics,
        "bars_processed": result.bars_processed,
        "total_bars": result.total_bars,
        "errors": result.errors,
        "num_fills": len(result.fills),
        "completed_at": datetime.utcnow().isoformat(),
        "progress": {
            "bars_done": result.bars_processed,
            "total": result.total_bars,
            "pct": 100.0,
        },
    }
    s["backtest_results"] = results

    log.info(
        "Backtest complete: %d bars, %d fills, return=%.2f%%",
        result.bars_processed,
        len(result.fills),
        result.metrics.get("total_return", 0) * 100,
    )
