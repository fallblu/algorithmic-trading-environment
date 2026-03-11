"""Risk monitor daemon — portfolio-level risk checks."""

import logging
from decimal import Decimal

from persistra import process

log = logging.getLogger(__name__)


@process("daemon", interval="10s")
def run(env):
    """Monitor portfolio risk and activate kill switch if limits breached."""
    risk_ns = env.state.ns("risk")
    portfolio_ns = env.state.ns("portfolio")

    # Read current state
    kill_switch = risk_ns.get("kill_switch", False)
    if kill_switch:
        log.warning("Kill switch is already active")
        return

    from config import RISK_DEFAULTS

    daily_pnl = portfolio_ns.get("daily_pnl", 0.0)
    max_drawdown = portfolio_ns.get("max_drawdown", 0.0)

    # Check daily loss limit (configurable via risk.* state, fallback to config)
    default_loss = float(RISK_DEFAULTS["daily_loss_limit"])
    daily_loss_limit = float(risk_ns.get("daily_loss_limit", default_loss))
    if daily_pnl < daily_loss_limit:
        log.critical("DAILY LOSS LIMIT BREACHED: %.2f < %.2f", daily_pnl, daily_loss_limit)
        risk_ns.set("kill_switch", True)
        return

    # Check max drawdown limit (configurable via risk.* state, fallback to config)
    default_dd = float(RISK_DEFAULTS["max_drawdown_limit"])
    max_dd_limit = float(risk_ns.get("max_drawdown_limit", default_dd))
    if max_drawdown > max_dd_limit:
        log.critical("MAX DRAWDOWN LIMIT BREACHED: %.4f > %.4f", max_drawdown, max_dd_limit)
        risk_ns.set("kill_switch", True)
        return

    log.debug("Risk check OK: daily_pnl=%.2f, max_dd=%.4f", daily_pnl, max_drawdown)
