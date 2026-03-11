"""ExposureManager — portfolio-level exposure limits and concentration checks."""

import logging
from dataclasses import dataclass
from decimal import Decimal

from broker.base import Broker
from models.order import Order, OrderSide

log = logging.getLogger(__name__)


@dataclass
class ExposureCheckResult:
    """Result of an exposure check."""
    passed: bool
    reason: str = ""


class ExposureManager:
    """Tracks and enforces portfolio-level exposure limits.

    Checks:
        - Total gross exposure (sum of all position notionals)
        - Net exposure (long - short notional)
        - Per-asset concentration (no single position > X% of equity)
    """

    def __init__(
        self,
        max_gross_exposure: Decimal | None = None,
        max_net_exposure: Decimal | None = None,
        max_concentration_pct: Decimal = Decimal("0.25"),
    ):
        self.max_gross_exposure = max_gross_exposure
        self.max_net_exposure = max_net_exposure
        self.max_concentration_pct = max_concentration_pct

    def check_order(self, order: Order, broker: Broker) -> ExposureCheckResult:
        """Check if an order would breach exposure limits.

        Args:
            order: The proposed order.
            broker: Current broker state for position/account info.

        Returns:
            ExposureCheckResult with passed=True if acceptable.
        """
        account = broker.get_account()
        equity = account.equity

        if equity <= 0:
            return ExposureCheckResult(passed=False, reason="Zero or negative equity")

        positions = broker.get_positions()

        # Estimate order notional (use price if available, otherwise skip notional checks)
        order_price = order.price
        if order_price is None:
            # Market order — we can't compute exact notional without current price
            # Allow it through exposure checks (position size check still applies)
            return ExposureCheckResult(passed=True)

        order_notional = order.quantity * order_price

        # 1. Concentration check — single position shouldn't exceed max % of equity
        max_position_notional = equity * self.max_concentration_pct
        existing_pos = broker.get_position(order.instrument)
        existing_notional = Decimal("0")
        if existing_pos is not None:
            existing_notional = existing_pos.quantity * existing_pos.entry_price

        if order.side == (existing_pos.side if existing_pos else order.side):
            # Adding to position
            new_notional = existing_notional + order_notional
        else:
            # Reducing position — always allowed from concentration perspective
            return ExposureCheckResult(passed=True)

        if new_notional > max_position_notional:
            reason = (
                f"Concentration limit: {order.instrument.symbol} notional "
                f"{new_notional:.2f} exceeds {self.max_concentration_pct*100:.0f}% "
                f"of equity ({max_position_notional:.2f})"
            )
            log.warning(reason)
            return ExposureCheckResult(passed=False, reason=reason)

        # 2. Gross exposure check
        if self.max_gross_exposure is not None:
            current_gross = sum(
                p.quantity * p.entry_price for p in positions
            )
            new_gross = current_gross + order_notional
            if new_gross > self.max_gross_exposure:
                reason = (
                    f"Gross exposure {new_gross:.2f} exceeds limit {self.max_gross_exposure:.2f}"
                )
                log.warning(reason)
                return ExposureCheckResult(passed=False, reason=reason)

        # 3. Net exposure check
        if self.max_net_exposure is not None:
            long_notional = sum(
                p.quantity * p.entry_price for p in positions if p.side == OrderSide.BUY
            )
            short_notional = sum(
                p.quantity * p.entry_price for p in positions if p.side == OrderSide.SELL
            )

            if order.side == OrderSide.BUY:
                long_notional += order_notional
            else:
                short_notional += order_notional

            net = abs(long_notional - short_notional)
            if net > self.max_net_exposure:
                reason = (
                    f"Net exposure {net:.2f} exceeds limit {self.max_net_exposure:.2f}"
                )
                log.warning(reason)
                return ExposureCheckResult(passed=False, reason=reason)

        return ExposureCheckResult(passed=True)
