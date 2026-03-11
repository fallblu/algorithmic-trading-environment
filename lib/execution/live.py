"""LiveContext — real market data with real Kraken broker execution."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from broker.base import Broker
from broker.kraken import KrakenBroker
from data.feed import DataFeed
from data.live import LiveFeed
from execution.context import ExecutionContext
from models.instrument import Instrument
from models.order import OrderStatus
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


class LiveContext(ExecutionContext):
    """Live trading: real market data with real broker execution.

    Same lifecycle as PaperContext:
        subscribe() -> warmup() -> run_once() per daemon tick -> shutdown()
    """

    mode = "live"

    def __init__(
        self,
        max_position_size: Decimal = Decimal("1.0"),
        max_order_value: Decimal = Decimal("100000"),
        daily_loss_limit: Decimal | None = Decimal("-500"),
    ):
        self._feed = LiveFeed()
        self._broker = KrakenBroker()
        self._risk_manager = RiskManager(
            max_position_size=max_position_size,
            max_order_value=max_order_value,
            daily_loss_limit=daily_loss_limit,
        )
        self._current_time = datetime.now(timezone.utc)

    def get_feed(self, instrument: Instrument) -> DataFeed:
        return self._feed

    def get_broker(self) -> Broker:
        return self._broker

    def get_risk_manager(self) -> RiskManager:
        return self._risk_manager

    def current_time(self) -> datetime:
        return self._current_time

    def subscribe(self, instrument: Instrument, timeframe: str) -> None:
        self._feed.subscribe(instrument, timeframe)

    def warmup(
        self,
        strategy: Strategy,
        instrument: Instrument,
        timeframe: str,
        warmup_bars: int = 50,
    ) -> None:
        """Feed historical bars to the strategy to warm up indicators."""
        end = datetime.now(timezone.utc)
        tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30,
                      "1h": 60, "4h": 240, "1d": 1440}
        minutes = tf_minutes.get(timeframe, 60)
        start = end - timedelta(minutes=int(minutes * warmup_bars * 1.2))

        bars = self._feed.historical_bars(instrument, timeframe, start, end)
        log.info("Warming up strategy with %d historical bars", len(bars))

        for bar in bars[-warmup_bars:]:
            strategy.on_bar(bar)

    def run_once(self, strategy: Strategy, instrument: Instrument) -> dict:
        """Process bars and execute real orders against Kraken."""
        bars_processed = 0

        while True:
            bar = self._feed.next_bar()
            if bar is None:
                break

            self._current_time = bar.timestamp

            # In live mode, check order statuses from exchange
            for order in list(self._broker._orders.values()):
                if order.status == OrderStatus.OPEN:
                    try:
                        self._broker.get_order(order.id)
                    except Exception:
                        log.exception("Failed to query order status: %s", order.id)

            # Call strategy
            orders = strategy.on_bar(bar)

            # Risk check + submit
            for order in orders:
                if self._risk_manager.check(order, self._broker):
                    try:
                        self._broker.submit_order(order)
                        log.info("LIVE order submitted: %s %s %s qty=%s",
                                 order.side.value, order.type.value,
                                 order.instrument.symbol, order.quantity)
                    except Exception:
                        log.exception("Failed to submit order to Kraken: %s", order.id)
                else:
                    log.warning("Order rejected by risk manager: %s", order.id)

            bars_processed += 1

        return {
            "bars_processed": bars_processed,
            "account": self._broker.get_account().to_dict(),
        }

    def shutdown(self) -> None:
        self._feed.shutdown()
