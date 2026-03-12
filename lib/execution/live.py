"""LiveContext — real market data with real broker execution, multi-symbol support."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from data.universe import Universe
from execution.realtime import RealtimeContext, _detect_exchange, create_live_feed, create_live_broker
from models.order import OrderStatus
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


class LiveContext(RealtimeContext):
    """Live trading: real market data with real broker execution.

    Supports spot (Kraken) and forex (OANDA) via exchange auto-detection
    or explicit exchange parameter.

    Same lifecycle as PaperContext:
        subscribe_all() -> warmup() -> run_once() per daemon tick -> shutdown()
    """

    mode = "live"

    def __init__(
        self,
        universe: Universe,
        max_position_size: Decimal = Decimal("1.0"),
        max_order_value: Decimal = Decimal("100000"),
        daily_loss_limit: Decimal | None = Decimal("-500"),
        exchange: str | None = None,
    ):
        self._universe = universe
        self._exchange = exchange if exchange else _detect_exchange(universe)

        self._feed = create_live_feed(self._exchange)
        self._broker = create_live_broker(self._exchange)
        self._risk_manager = RiskManager(
            max_position_size=max_position_size,
            max_order_value=max_order_value,
            daily_loss_limit=daily_loss_limit,
        )
        self._current_time = datetime.now(timezone.utc)
        self._panel = None

    def _process_fills(self, group: list, strategy: Strategy) -> list:
        """Check order statuses from exchange (no simulated fills in live mode)."""
        for order in list(self._broker._orders.values()):
            if order.status == OrderStatus.OPEN:
                try:
                    self._broker.get_order(order.id)
                except Exception:
                    log.exception("Failed to query order status: %s", order.id)
        return []

    def _submit_order(self, order, strategy: Strategy) -> None:
        """Submit order to live exchange broker with error handling."""
        try:
            self._broker.submit_order(order)
            log.info("LIVE order submitted: %s %s %s qty=%s",
                     order.side.value, order.type.value,
                     order.instrument.symbol, order.quantity)
        except Exception:
            log.exception("Failed to submit order: %s", order.id)

    def _empty_result(self) -> dict:
        return {
            "bars_processed": 0,
            "account": self._broker.get_account().to_dict(),
        }

    def _build_result(self, bars_processed: int, fills: list) -> dict:
        return {
            "bars_processed": bars_processed,
            "account": self._broker.get_account().to_dict(),
        }
