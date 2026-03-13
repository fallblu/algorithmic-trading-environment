"""RiskManager — enforced risk check pipeline for portfolios."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from broker.base import Account, Broker
from models.order import Order, OrderSide
from models.position import Position
from risk.rules import RiskConfig, RiskEvent, RiskLevel

log = logging.getLogger(__name__)


class RiskManager:
    """Enforced risk management for portfolio trading.

    All checks are blocking — orders that violate constraints are rejected.
    The kill switch halts all trading when max drawdown is breached.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._kill_switch = False
        self._peak_equity: float = 0.0
        self._daily_start_equity: float = 0.0
        self._current_day: str = ""
        self._events: list[RiskEvent] = []

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch

    @property
    def events(self) -> list[RiskEvent]:
        return list(self._events)

    @property
    def config(self) -> RiskConfig:
        return self._config

    def reset_kill_switch(self) -> None:
        self._kill_switch = False

    def check_order(self, order: Order, broker: Broker) -> tuple[bool, str]:
        """Check if an order passes all risk rules.

        Returns (allowed, reason). If not allowed, reason explains why.
        """
        if self._kill_switch:
            return False, "Kill switch active — trading halted"

        account = broker.get_account()

        # Update peak equity and daily tracking
        self._update_tracking(account)

        # 1. Max position size check
        if account.equity > 0:
            order_notional = (order.price or 0) * order.quantity
            if order.price is None:
                # Market order — estimate using current equity as proxy
                order_notional = account.equity * 0.1  # rough estimate
            position_pct = order_notional / account.equity
            if position_pct > self._config.max_position_pct:
                reason = (
                    f"Position size {position_pct:.1%} exceeds max "
                    f"{self._config.max_position_pct:.1%}"
                )
                self._add_event("max_position", reason, RiskLevel.WARNING)
                return False, reason

        # 2. Exposure checks
        positions = broker.get_positions()
        if account.equity > 0:
            gross, net = self._compute_exposure(positions, account.equity)

            if gross > self._config.max_gross_exposure:
                reason = (
                    f"Gross exposure {gross:.2f}x exceeds max "
                    f"{self._config.max_gross_exposure:.2f}x"
                )
                self._add_event("max_gross_exposure", reason, RiskLevel.WARNING)
                return False, reason

            if abs(net) > self._config.max_net_exposure:
                reason = (
                    f"Net exposure {net:.2f}x exceeds max "
                    f"{self._config.max_net_exposure:.2f}x"
                )
                self._add_event("max_net_exposure", reason, RiskLevel.WARNING)
                return False, reason

        return True, ""

    def check_portfolio(self, broker: Broker) -> list[RiskEvent]:
        """Run portfolio-level risk checks. Returns list of violations.

        Triggers kill switch if max drawdown is breached.
        """
        violations: list[RiskEvent] = []
        account = broker.get_account()
        self._update_tracking(account)

        # Max drawdown check
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - account.equity) / self._peak_equity
            if drawdown >= self._config.max_drawdown_pct:
                event = RiskEvent(
                    rule="max_drawdown",
                    message=(
                        f"Drawdown {drawdown:.1%} exceeds max "
                        f"{self._config.max_drawdown_pct:.1%} — KILL SWITCH ACTIVATED"
                    ),
                    level=RiskLevel.CRITICAL,
                )
                violations.append(event)
                self._events.append(event)
                self._kill_switch = True
                log.critical("Kill switch activated: drawdown %.1f%%", drawdown * 100)

        # Daily loss check
        if self._daily_start_equity > 0:
            daily_loss = (self._daily_start_equity - account.equity) / self._daily_start_equity
            if daily_loss >= self._config.max_daily_loss_pct:
                event = RiskEvent(
                    rule="max_daily_loss",
                    message=(
                        f"Daily loss {daily_loss:.1%} exceeds max "
                        f"{self._config.max_daily_loss_pct:.1%} — KILL SWITCH ACTIVATED"
                    ),
                    level=RiskLevel.CRITICAL,
                )
                violations.append(event)
                self._events.append(event)
                self._kill_switch = True
                log.critical("Kill switch activated: daily loss %.1f%%", daily_loss * 100)

        return violations

    def _update_tracking(self, account: Account) -> None:
        """Update peak equity and daily tracking."""
        if account.equity > self._peak_equity:
            self._peak_equity = account.equity

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_day:
            self._current_day = today
            self._daily_start_equity = account.equity

        if self._daily_start_equity == 0:
            self._daily_start_equity = account.equity

    def _compute_exposure(
        self, positions: list[Position], equity: float
    ) -> tuple[float, float]:
        """Compute gross and net exposure as multiples of equity."""
        long_notional = 0.0
        short_notional = 0.0

        for pos in positions:
            notional = pos.quantity * pos.avg_entry_price
            from models.position import PositionSide
            if pos.side == PositionSide.LONG:
                long_notional += notional
            else:
                short_notional += notional

        gross = (long_notional + short_notional) / equity if equity > 0 else 0
        net = (long_notional - short_notional) / equity if equity > 0 else 0
        return gross, net

    def _add_event(self, rule: str, message: str, level: RiskLevel) -> None:
        event = RiskEvent(rule=rule, message=message, level=level)
        self._events.append(event)
        log.warning("Risk violation [%s]: %s", rule, message)
