"""LiveContext — real market data with real Kraken broker execution, multi-symbol support."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from broker.base import Broker
from broker.kraken import KrakenBroker
from data.live import LiveFeed
from data.price_panel import PricePanel
from data.universe import Universe
from execution.context import ExecutionContext
from models.order import OrderStatus
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


class LiveContext(ExecutionContext):
    """Live trading: real market data with real broker execution.

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
    ):
        self._universe = universe
        self._feed = LiveFeed()
        self._broker = KrakenBroker()
        self._risk_manager = RiskManager(
            max_position_size=max_position_size,
            max_order_value=max_order_value,
            daily_loss_limit=daily_loss_limit,
        )
        self._current_time = datetime.now(timezone.utc)
        self._panel: PricePanel | None = None

    def get_universe(self) -> Universe:
        return self._universe

    def get_broker(self) -> Broker:
        return self._broker

    def get_risk_manager(self) -> RiskManager:
        return self._risk_manager

    def current_time(self) -> datetime:
        return self._current_time

    def subscribe_all(self, timeframe: str) -> None:
        instruments = list(self._universe.instruments.values())
        self._feed.subscribe_all(instruments, timeframe)

    def warmup(
        self,
        strategy: Strategy,
        timeframe: str,
        warmup_bars: int = 50,
    ) -> None:
        """Feed historical bars for all symbols to warm up indicators."""
        self._panel = PricePanel(self._universe, lookback=strategy.lookback())

        end = datetime.now(timezone.utc)
        tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30,
                      "1h": 60, "4h": 240, "1d": 1440}
        minutes = tf_minutes.get(timeframe, 60)
        start = end - timedelta(minutes=int(minutes * warmup_bars * 1.2))

        all_bars = []
        for instrument in self._universe.instruments.values():
            bars = self._feed.historical_bars(instrument, timeframe, start, end)
            all_bars.extend(bars[-warmup_bars:])

        all_bars.sort(key=lambda b: b.timestamp)
        groups: dict[datetime, list] = defaultdict(list)
        for bar in all_bars:
            groups[bar.timestamp].append(bar)

        log.info("Warming up strategy with %d bar groups across %d symbols",
                 len(groups), len(self._universe.symbols))

        for ts in sorted(groups.keys()):
            self._panel.append_bars(groups[ts])
            if self._panel.is_ready:
                strategy.on_bar(self._panel.get_window())

    def run_once(self, strategy: Strategy) -> dict:
        """Process bars and execute real orders against Kraken."""
        if self._panel is None:
            self._panel = PricePanel(self._universe, lookback=strategy.lookback())

        bars = self._feed.next_bars()
        if not bars:
            return {"bars_processed": 0, "account": self._broker.get_account().to_dict()}

        bars.sort(key=lambda b: b.timestamp)
        groups: dict[datetime, list] = defaultdict(list)
        for bar in bars:
            groups[bar.timestamp].append(bar)

        bars_processed = 0

        for ts in sorted(groups.keys()):
            group = groups[ts]
            self._current_time = ts

            # Check order statuses from exchange
            for order in list(self._broker._orders.values()):
                if order.status == OrderStatus.OPEN:
                    try:
                        self._broker.get_order(order.id)
                    except Exception:
                        log.exception("Failed to query order status: %s", order.id)

            # Append to panel and call strategy
            self._panel.append_bars(group)
            if self._panel.is_ready:
                orders = strategy.on_bar(self._panel.get_window())

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
