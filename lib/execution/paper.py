"""PaperContext — live data feed with simulated broker, multi-symbol support."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from broker.base import Broker
from broker.simulated import SimulatedBroker
from constants import TIMEFRAME_MINUTES
from data.price_panel import PricePanel
from data.universe import Universe
from execution.context import ExecutionContext
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


def _create_feed(exchange: str):
    """Create the appropriate live feed for the given exchange."""
    if exchange == "oanda":
        from data.live_oanda import LiveOandaFeed
        return LiveOandaFeed()
    else:
        from data.live import LiveFeed
        return LiveFeed()


class PaperContext(ExecutionContext):
    """Paper trading: live market data with simulated execution.

    Supports spot (Kraken) and forex (OANDA) via exchange auto-detection
    from universe instruments.

    Lifecycle:
        1. __init__() — creates LiveFeed and SimulatedBroker
        2. subscribe_all() — subscribes the feed to all universe instruments
        3. warmup() — feeds historical bars for indicator warmup
        4. run_once() — called by daemon each tick; drains bar queue
        5. shutdown() — stops the WebSocket feed
    """

    mode = "paper"

    def __init__(
        self,
        universe: Universe,
        initial_cash: Decimal = Decimal("10000"),
        fee_rate: Decimal = Decimal("0.0026"),
        slippage_pct: Decimal = Decimal("0.0001"),
        max_position_size: Decimal = Decimal("1.0"),
        exchange: str | None = None,
        margin_mode: bool = False,
        leverage: Decimal = Decimal("1"),
        spread_pips: Decimal = Decimal("0"),
    ):
        self._universe = universe

        # Auto-detect exchange from universe
        if exchange is None:
            first_inst = next(iter(universe.instruments.values()), None)
            exchange = first_inst.exchange if first_inst else "kraken"
        self._exchange = exchange

        self._feed = _create_feed(exchange)

        self._broker = SimulatedBroker(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_pct=slippage_pct,
            margin_mode=margin_mode,
            leverage=leverage,
            spread_pips=spread_pips,
        )
        self._risk_manager = RiskManager(max_position_size=max_position_size)
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
        """Subscribe to live data for all instruments in the universe."""
        instruments = list(self._universe.instruments.values())
        self._feed.subscribe_all(instruments, timeframe)

    def warmup(
        self,
        strategy: Strategy,
        timeframe: str,
        warmup_bars: int = 50,
    ) -> None:
        """Feed historical bars for all symbols to warm up indicators.

        Warmup bars are NOT processed through the broker (no orders).
        """
        self._panel = PricePanel(self._universe, lookback=strategy.lookback())

        end = datetime.now(timezone.utc)
        minutes = TIMEFRAME_MINUTES.get(timeframe, 60)
        start = end - timedelta(minutes=int(minutes * warmup_bars * 1.2))

        # Fetch historical bars for each symbol
        all_bars = []
        for instrument in self._universe.instruments.values():
            bars = self._feed.historical_bars(instrument, timeframe, start, end)
            all_bars.extend(bars[-warmup_bars:])

        # Sort by timestamp and group
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
        """Process all available bars from the live feed.

        Called by the daemon on each tick.
        """
        if self._panel is None:
            self._panel = PricePanel(self._universe, lookback=strategy.lookback())

        bars = self._feed.next_bars()
        if not bars:
            return {
                "bars_processed": 0,
                "fills": 0,
                "equity": self._broker.get_account().equity,
                "positions": len(self._broker.get_positions()),
            }

        # Sort by timestamp and group
        bars.sort(key=lambda b: b.timestamp)
        groups: dict[datetime, list] = defaultdict(list)
        for bar in bars:
            groups[bar.timestamp].append(bar)

        bars_processed = 0
        fills_this_tick = []

        for ts in sorted(groups.keys()):
            group = groups[ts]
            self._current_time = ts

            # 1. Process pending orders against all bars at this timestamp
            new_fills = self._broker.process_bars(group)
            fills_this_tick.extend(new_fills)

            for fill in new_fills:
                strategy.on_fill(fill)
                log.info("Fill: %s %s %s @ %s", fill.side.value,
                         fill.quantity, fill.instrument.symbol, fill.price)

            # 2. Append to panel and call strategy
            self._panel.append_bars(group)
            if self._panel.is_ready:
                orders = strategy.on_bar(self._panel.get_window())

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
