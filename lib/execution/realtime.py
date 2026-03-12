"""RealtimeContext — shared base for PaperContext and LiveContext.

Both paper and live trading share the same lifecycle:
    subscribe_all() -> warmup() -> run_once() per daemon tick -> shutdown()

This base class extracts the common bar grouping, warmup, and processing logic.
Subclasses override _create_feed(), _create_broker(), and _submit_order() to
customize the feed source, broker type, and order submission behavior.
"""

import logging
from abc import abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from broker.base import Broker
from constants import TIMEFRAME_MINUTES
from data.price_panel import PricePanel
from data.universe import Universe
from execution.context import ExecutionContext
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


def _detect_exchange(universe: Universe) -> str:
    """Auto-detect exchange from universe instruments."""
    first_inst = next(iter(universe.instruments.values()), None)
    return first_inst.exchange if first_inst else "kraken"


def create_live_feed(exchange: str):
    """Create the appropriate live data feed for the given exchange."""
    if exchange == "oanda":
        from data.live_oanda import LiveOandaFeed
        return LiveOandaFeed()
    else:
        from data.live import LiveFeed
        return LiveFeed()


def create_live_broker(exchange: str) -> Broker:
    """Create the appropriate live broker for the given exchange."""
    if exchange == "oanda":
        from broker.oanda import OandaBroker
        return OandaBroker()
    else:
        from broker.kraken import KrakenBroker
        return KrakenBroker()


def _group_bars_by_timestamp(bars: list) -> dict[datetime, list]:
    """Sort bars and group by timestamp."""
    bars.sort(key=lambda b: b.timestamp)
    groups: dict[datetime, list] = defaultdict(list)
    for bar in bars:
        groups[bar.timestamp].append(bar)
    return groups


class RealtimeContext(ExecutionContext):
    """Base class for live-data execution contexts (paper and live).

    Provides shared implementations for warmup, subscribe, and the
    bar-processing loop. Subclasses customize broker creation and
    order submission behavior.
    """

    _universe: Universe
    _exchange: str
    _feed: object  # LiveFeed or LiveOandaFeed
    _broker: Broker
    _risk_manager: RiskManager
    _current_time: datetime
    _panel: PricePanel | None

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

        all_bars = []
        for instrument in self._universe.instruments.values():
            bars = self._feed.historical_bars(instrument, timeframe, start, end)
            all_bars.extend(bars[-warmup_bars:])

        groups = _group_bars_by_timestamp(all_bars)

        log.info("Warming up strategy with %d bar groups across %d symbols",
                 len(groups), len(self._universe.symbols))

        for ts in sorted(groups.keys()):
            self._panel.append_bars(groups[ts])
            if self._panel.is_ready:
                strategy.on_bar(self._panel.get_window())

    @abstractmethod
    def _process_fills(self, group: list, strategy: Strategy) -> list:
        """Process pending orders against a bar group. Return new fills."""
        ...

    @abstractmethod
    def _submit_order(self, order, strategy: Strategy) -> None:
        """Submit an order through the broker (paper vs live differs)."""
        ...

    def _process_bar_group(
        self,
        group: list,
        strategy: Strategy,
    ) -> list:
        """Process a single timestamp's bar group: fills -> panel -> strategy -> orders.

        Returns list of new fills.
        """
        self._current_time = group[0].timestamp

        # 1. Process pending orders
        new_fills = self._process_fills(group, strategy)

        # 2. Append to panel and call strategy
        self._panel.append_bars(group)
        if self._panel.is_ready:
            orders = strategy.on_bar(self._panel.get_window())

            # 3. Risk check + submit
            for order in orders:
                if self._risk_manager.check(order, self._broker):
                    self._submit_order(order, strategy)
                else:
                    log.warning("Order rejected by risk manager: %s", order.id)

        return new_fills

    def run_once(self, strategy: Strategy) -> dict:
        """Process all available bars from the live feed.

        Called by the daemon on each tick.
        """
        if self._panel is None:
            self._panel = PricePanel(self._universe, lookback=strategy.lookback())

        bars = self._feed.next_bars()
        if not bars:
            return self._empty_result()

        groups = _group_bars_by_timestamp(bars)
        bars_processed = 0
        all_fills = []

        for ts in sorted(groups.keys()):
            fills = self._process_bar_group(groups[ts], strategy)
            all_fills.extend(fills)
            bars_processed += 1

        return self._build_result(bars_processed, all_fills)

    @abstractmethod
    def _empty_result(self) -> dict:
        """Return result dict when no bars are available."""
        ...

    @abstractmethod
    def _build_result(self, bars_processed: int, fills: list) -> dict:
        """Build the result dict after processing bars."""
        ...

    def shutdown(self) -> None:
        """Shut down the live feed."""
        self._feed.shutdown()
