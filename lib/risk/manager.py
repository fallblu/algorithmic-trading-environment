"""RiskManager — pre-trade validation and portfolio risk checks."""

import logging
from decimal import Decimal

from broker.base import Broker
from models.order import Order, OrderSide

log = logging.getLogger(__name__)


class RiskManager:
    """Pre-trade risk checks and portfolio-level monitoring.

    Thin-slice: max position size check only.
    Future: daily loss limit, max drawdown, exposure caps, kill switch.
    """

    def __init__(
        self,
        max_position_size: Decimal = Decimal("1.0"),      # Max quantity per instrument
        max_order_value: Decimal = Decimal("100000"),      # Max notional per order
        max_exposure: Decimal | None = None,               # Max total portfolio exposure
        daily_loss_limit: Decimal | None = None,           # Max daily loss before kill switch
    ):
        self.max_position_size = max_position_size
        self.max_order_value = max_order_value
        self.max_exposure = max_exposure
        self.daily_loss_limit = daily_loss_limit
        self.kill_switch = False

    def check(self, order: Order, broker: Broker) -> bool:
        """Validate an order against risk limits. Returns True if allowed."""
        if self.kill_switch:
            log.warning("Risk kill switch is active — rejecting order %s", order.id)
            return False

        # Check max position size
        current_pos = broker.get_position(order.instrument)
        current_qty = current_pos.quantity if current_pos is not None else Decimal("0")

        if order.side == OrderSide.BUY:
            new_qty = current_qty + order.quantity
        else:
            # Selling reduces long position; allow closes
            if current_pos is not None and current_pos.side == OrderSide.BUY:
                new_qty = current_qty - order.quantity
                if new_qty < 0:
                    new_qty = abs(new_qty)  # Reversing to short
            else:
                new_qty = current_qty + order.quantity

        if new_qty > self.max_position_size:
            log.warning(
                "Order %s rejected: position size %.4f exceeds max %.4f",
                order.id, new_qty, self.max_position_size,
            )
            return False

        # Check max order notional
        if order.price is not None:
            notional = order.quantity * order.price
        else:
            # For market orders, we don't have price yet; skip this check
            notional = None

        if notional is not None and notional > self.max_order_value:
            log.warning(
                "Order %s rejected: notional %.2f exceeds max %.2f",
                order.id, notional, self.max_order_value,
            )
            return False

        return True
