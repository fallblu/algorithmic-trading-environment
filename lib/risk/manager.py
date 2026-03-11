"""RiskManager — comprehensive pre-trade validation and portfolio risk checks."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from broker.base import Broker
from config import RiskConfig
from events import RiskEvent, get_event_bus
from models.order import Order, OrderSide
from risk.exposure import ExposureManager

log = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    """Result of a single risk check."""
    passed: bool
    check_name: str
    reason: str = ""


class RiskManager:
    """Comprehensive pre-trade risk checks and portfolio-level monitoring.

    Check pipeline (in order):
        1. Kill switch
        2. Max position size
        3. Max order notional
        4. Daily loss limit
        5. Max drawdown limit
        6. Portfolio exposure / concentration (via ExposureManager)
    """

    def __init__(
        self,
        max_position_size: Decimal = Decimal("1.0"),
        max_order_value: Decimal = Decimal("100000"),
        max_exposure: Decimal | None = None,
        daily_loss_limit: Decimal | None = None,
        max_drawdown_limit: Decimal | None = None,
        max_leverage: Decimal | None = None,
        max_concentration_pct: Decimal = Decimal("0.25"),
        risk_config: RiskConfig | None = None,
    ):
        if risk_config is not None:
            self.max_position_size = risk_config.max_position_size
            self.max_order_value = risk_config.max_order_value
            self.daily_loss_limit = risk_config.daily_loss_limit
            self.max_drawdown_limit = risk_config.max_drawdown_limit
            self.max_leverage = risk_config.max_leverage
            max_exposure = risk_config.max_exposure
            max_concentration_pct = risk_config.max_concentration_pct
        else:
            self.max_position_size = max_position_size
            self.max_order_value = max_order_value
            self.daily_loss_limit = daily_loss_limit
            self.max_drawdown_limit = max_drawdown_limit
            self.max_leverage = max_leverage

        self.kill_switch = False

        # Daily PnL tracking
        self._session_start_equity: Decimal | None = None
        self._session_date: datetime | None = None

        # Drawdown tracking
        self._high_water_mark: Decimal = Decimal("0")

        # Exposure manager
        self._exposure_mgr = ExposureManager(
            max_gross_exposure=max_exposure,
            max_concentration_pct=max_concentration_pct,
        )

    def check(self, order: Order, broker: Broker) -> bool:
        """Validate an order against all risk limits. Returns True if allowed."""
        results = self.check_all(order, broker)
        return all(r.passed for r in results)

    def check_all(self, order: Order, broker: Broker) -> list[RiskCheckResult]:
        """Run all risk checks and return individual results."""
        results = []

        results.append(self._check_kill_switch(order))
        if not results[-1].passed:
            self._emit_risk_event(results[-1])
            return results

        results.append(self._check_position_size(order, broker))
        results.append(self._check_order_notional(order))
        results.append(self._check_daily_loss(broker))
        results.append(self._check_drawdown(broker))
        results.append(self._check_exposure(order, broker))

        for result in results:
            if not result.passed:
                self._emit_risk_event(result)

        return results

    def _check_kill_switch(self, order: Order) -> RiskCheckResult:
        if self.kill_switch:
            return RiskCheckResult(
                passed=False,
                check_name="kill_switch",
                reason=f"Kill switch active — rejecting order {order.id}",
            )
        return RiskCheckResult(passed=True, check_name="kill_switch")

    def _check_position_size(self, order: Order, broker: Broker) -> RiskCheckResult:
        current_pos = broker.get_position(order.instrument)
        current_qty = current_pos.quantity if current_pos is not None else Decimal("0")

        if order.side == OrderSide.BUY:
            new_qty = current_qty + order.quantity
        else:
            if current_pos is not None and current_pos.side == OrderSide.BUY:
                new_qty = current_qty - order.quantity
                if new_qty < 0:
                    new_qty = abs(new_qty)
            else:
                new_qty = current_qty + order.quantity

        if new_qty > self.max_position_size:
            return RiskCheckResult(
                passed=False,
                check_name="position_size",
                reason=f"Position size {new_qty:.4f} exceeds max {self.max_position_size:.4f}",
            )
        return RiskCheckResult(passed=True, check_name="position_size")

    def _check_order_notional(self, order: Order) -> RiskCheckResult:
        if order.price is not None:
            notional = order.quantity * order.price
            if notional > self.max_order_value:
                return RiskCheckResult(
                    passed=False,
                    check_name="order_notional",
                    reason=f"Order notional {notional:.2f} exceeds max {self.max_order_value:.2f}",
                )
        return RiskCheckResult(passed=True, check_name="order_notional")

    def _check_daily_loss(self, broker: Broker) -> RiskCheckResult:
        if self.daily_loss_limit is None:
            return RiskCheckResult(passed=True, check_name="daily_loss")

        account = broker.get_account()
        now = datetime.now(timezone.utc)

        if self._session_date is None or now.date() != self._session_date.date():
            self._session_start_equity = account.equity
            self._session_date = now
            return RiskCheckResult(passed=True, check_name="daily_loss")

        daily_pnl = account.equity - self._session_start_equity

        if daily_pnl < self.daily_loss_limit:
            self.kill_switch = True
            return RiskCheckResult(
                passed=False,
                check_name="daily_loss",
                reason=f"Daily loss {daily_pnl:.2f} exceeds limit {self.daily_loss_limit:.2f} — kill switch engaged",
            )
        return RiskCheckResult(passed=True, check_name="daily_loss")

    def _check_drawdown(self, broker: Broker) -> RiskCheckResult:
        if self.max_drawdown_limit is None:
            return RiskCheckResult(passed=True, check_name="drawdown")

        account = broker.get_account()
        equity = account.equity

        if equity > self._high_water_mark:
            self._high_water_mark = equity

        if self._high_water_mark <= 0:
            return RiskCheckResult(passed=True, check_name="drawdown")

        drawdown = (self._high_water_mark - equity) / self._high_water_mark

        if drawdown > self.max_drawdown_limit:
            return RiskCheckResult(
                passed=False,
                check_name="drawdown",
                reason=f"Drawdown {drawdown:.2%} exceeds limit {self.max_drawdown_limit:.2%}",
            )
        return RiskCheckResult(passed=True, check_name="drawdown")

    def _check_exposure(self, order: Order, broker: Broker) -> RiskCheckResult:
        result = self._exposure_mgr.check_order(order, broker)
        if not result.passed:
            return RiskCheckResult(
                passed=False,
                check_name="exposure",
                reason=result.reason,
            )
        return RiskCheckResult(passed=True, check_name="exposure")

    def _emit_risk_event(self, result: RiskCheckResult) -> None:
        try:
            bus = get_event_bus()
            bus.publish(RiskEvent(reason=f"[{result.check_name}] {result.reason}"))
        except Exception:
            log.debug("Could not emit risk event", exc_info=True)

    def reset_daily(self) -> None:
        """Reset daily PnL tracking. Call at start of each trading day."""
        self._session_start_equity = None
        self._session_date = None
        log.info("Daily risk counters reset")

    def reset_kill_switch(self) -> None:
        """Manually reset the kill switch."""
        self.kill_switch = False
        log.info("Risk kill switch disengaged")

    def update_high_water_mark(self, equity: Decimal) -> None:
        """Manually set high-water mark (e.g., at session start)."""
        self._high_water_mark = equity
