"""PaperContext — live data feed with simulated broker."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from broker.base import Broker
from broker.simulated import SimulatedBroker
from data.feed import DataFeed
from data.live import LiveFeed
from execution.context import ExecutionContext
from models.instrument import Instrument
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


class PaperContext(ExecutionContext):
    """Paper trading: live market data with simulated execution.

    Lifecycle:
        1. __init__() — creates LiveFeed and SimulatedBroker
        2. subscribe() — subscribes the feed to instruments
        3. warmup() — feeds historical bars for indicator warmup
        4. run_once() — called by daemon each tick; drains bar queue
        5. shutdown() — stops the WebSocket feed
    """

    mode = "paper"

    def __init__(
        self,
        initial_cash: Decimal = Decimal("10000"),
        fee_rate: Decimal = Decimal("0.0026"),
        slippage_pct: Decimal = Decimal("0.0001"),
        max_position_size: Decimal = Decimal("1.0"),
    ):
        self._feed = LiveFeed()
        self._broker = SimulatedBroker(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_pct=slippage_pct,
        )
        self._risk_manager = RiskManager(max_position_size=max_position_size)
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
        """Subscribe to live data for an instrument."""
        self._feed.subscribe(instrument, timeframe)

    def warmup(
        self,
        strategy: Strategy,
        instrument: Instrument,
        timeframe: str,
        warmup_bars: int = 50,
    ) -> None:
        """Feed historical bars to the strategy to warm up indicators.

        Warmup bars are NOT processed through the broker (no orders).
        """
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
        """Process all available bars from the live feed.

        Called by the daemon on each tick.
        """
        bars_processed = 0
        fills_this_tick = []

        while True:
            bar = self._feed.next_bar()
            if bar is None:
                break

            self._current_time = bar.timestamp

            # 1. Process pending orders against this bar
            new_fills = self._broker.process_bar(bar)
            fills_this_tick.extend(new_fills)

            for fill in new_fills:
                strategy.on_fill(fill)
                log.info("Fill: %s %s %s @ %s", fill.side.value,
                         fill.quantity, fill.instrument.symbol, fill.price)

            # 2. Call strategy
            orders = strategy.on_bar(bar)

            # 3. Risk check + submit
            for order in orders:
                if self._risk_manager.check(order, self._broker):
                    self._broker.submit_order(order)
                    log.info("Order submitted: %s %s %s qty=%s",
                             order.side.value, order.type.value,
                             order.instrument.symbol, order.quantity)
                else:
                    log.warning("Order rejected by risk manager: %s", order.id)

            bars_processed += 1

        return {
            "bars_processed": bars_processed,
            "fills": len(fills_this_tick),
            "equity": self._broker.get_account().equity,
            "positions": len(self._broker.get_positions()),
        }

    def shutdown(self) -> None:
        """Shut down the live feed."""
        self._feed.shutdown()
