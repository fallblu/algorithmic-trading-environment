"""Paper trader process — run paper trading as a Persistra daemon."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)


@process("daemon")
def run(env, portfolio_id: str = "", api_key: str = "", account_id: str = ""):
    """Run paper trading for a portfolio.

    Parameters:
        portfolio_id: The portfolio ID to paper trade.
        api_key: Exchange API key (for OANDA).
        account_id: Exchange account ID (for OANDA).
    """
    from execution.paper import PaperContext
    from portfolio.portfolio import Portfolio

    s = env.state

    portfolios = s.get("portfolios", {})
    if portfolio_id not in portfolios:
        log.error("Portfolio %s not found", portfolio_id)
        return

    portfolio = Portfolio.from_dict(portfolios[portfolio_id])

    def on_fill(fill):
        log.info("Paper fill: %s %s %s @ %.2f", fill.side, fill.quantity, fill.symbol, fill.price)
        active = s.get("active_processes", {})
        if portfolio_id in active:
            fills = active[portfolio_id].get("recent_fills", [])
            fills.append({
                "symbol": fill.symbol,
                "side": fill.side.value,
                "quantity": fill.quantity,
                "price": fill.price,
                "timestamp": fill.timestamp.isoformat(),
            })
            active[portfolio_id]["recent_fills"] = fills[-50:]  # keep last 50
            s.set("active_processes", active)

    def on_error(msg):
        log.error("Paper trading error: %s", msg)
        active = s.get("active_processes", {})
        if portfolio_id in active:
            errors = active[portfolio_id].get("errors", [])
            errors.append(msg)
            active[portfolio_id]["errors"] = errors[-20:]
            s.set("active_processes", active)

    def on_status_change(status):
        active = s.get("active_processes", {})
        if portfolio_id in active:
            active[portfolio_id]["connection_status"] = status
            s.set("active_processes", active)

    # Register in active processes
    active = s.get("active_processes", {})
    active[portfolio_id] = {
        "mode": "paper",
        "connection_status": "connecting",
        "recent_fills": [],
        "errors": [],
    }
    s["active_processes"] = active

    ctx = PaperContext(
        portfolio=portfolio,
        api_key=api_key,
        account_id=account_id,
        on_fill=on_fill,
        on_error=on_error,
        on_status_change=on_status_change,
    )

    asyncio.run(ctx.run())
