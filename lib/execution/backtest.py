"""BacktestContext — multi-symbol bar-by-bar replay engine with simulated broker."""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from broker.base import Broker
from broker.simulated import SimulatedBroker
from data.historical import HistoricalFeed
from data.price_panel import PricePanel
from data.store import MarketDataStore
from data.universe import Universe
from execution.context import ExecutionContext
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


class BacktestContext(ExecutionContext):
    """Drives multi-symbol bar-by-bar replay for backtesting.

    Owns the replay loop: loads bars for all symbols from HistoricalFeed,
    groups them by timestamp, processes through SimulatedBroker, then
    calls strategy.on_bar() with a PricePanel window.

    Supports spot and forex (spread simulation).
    """

    mode = "backtest"

    def __init__(
        self,
        universe: Universe,
        start: datetime | None = None,
        end: datetime | None = None,
        initial_cash: Decimal = Decimal("10000"),
        fee_rate: Decimal = Decimal("0.0026"),
        slippage_pct: Decimal = Decimal("0.0001"),
        max_position_size: Decimal = Decimal("1.0"),
        data_dir: Path | None = None,
        exchange: str | None = None,
        margin_mode: bool = False,
        leverage: Decimal = Decimal("1"),
        spread_pips: Decimal = Decimal("0"),
    ):
        self._universe = universe
        self.start = start
        self.end = end

        if data_dir is None:
            data_dir = Path(".persistra/market_data")

        # Auto-detect exchange from universe
        if exchange is None:
            first_inst = next(iter(universe.instruments.values()), None)
            exchange = first_inst.exchange if first_inst else "kraken"

        self._exchange = exchange
        self._store = MarketDataStore(data_dir)
        self._feed = HistoricalFeed(self._store, exchange=exchange)
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
        self._equity_curve: list[tuple[datetime, Decimal]] = []
        self._bars_processed: int = 0

    def get_universe(self) -> Universe:
        return self._universe

    def get_broker(self) -> Broker:
        return self._broker

    def get_risk_manager(self) -> RiskManager:
        return self._risk_manager

    def current_time(self) -> datetime:
        return self._current_time

    @property
    def equity_curve(self) -> list[tuple[datetime, Decimal]]:
        return list(self._equity_curve)

    @property
    def fills(self):
        return self._broker.fills

    def run(self, strategy: Strategy) -> dict:
        """Execute the multi-symbol backtest replay loop."""
        panel = PricePanel(self._universe, lookback=strategy.lookback())

        # Load bars for all symbols
        self._feed.load_universe(self._universe, self.start, self.end)

        if self._feed.total_groups == 0:
            log.warning("No bars found for universe %s", self._universe.symbols)
            return {"equity_curve": [], "fills": [], "bars_processed": 0}

        log.info(
            "Starting backtest: %s %s, %d timestamp groups",
            self._universe.symbols,
            self._universe.timeframe,
            self._feed.total_groups,
        )

        # Record initial equity
        initial_equity = self._broker.get_account().equity
        first_group = True

        while True:
            bar_group = self._feed.next_bar_group()
            if bar_group is None:
                break

            self._current_time = bar_group[0].timestamp

            if first_group:
                self._equity_curve.append((self._current_time, initial_equity))
                first_group = False

            # 1. Process pending orders against all bars at this timestamp
            self._broker.process_bars(bar_group)

            # 2. Append bars to panel
            panel.append_bars(bar_group)

            # 3. Call strategy if panel is ready
            if panel.is_ready:
                orders = strategy.on_bar(panel.get_window())

                # 4. Risk check + submit orders
                for order in orders:
                    if self._risk_manager.check(order, self._broker):
                        self._broker.submit_order(order)
                    else:
                        log.info("Order rejected by risk manager: %s", order.id)

            # 5. Record equity snapshot
            account = self._broker.get_account()
            self._equity_curve.append((self._current_time, account.equity))
            self._bars_processed += 1

        log.info(
            "Backtest complete: %d groups, %d fills, final equity: %s",
            self._bars_processed,
            len(self._broker.fills),
            self._broker.get_account().equity,
        )

        return {
            "equity_curve": self._equity_curve,
            "fills": self._broker.fills,
            "bars_processed": self._bars_processed,
            "final_equity": self._broker.get_account().equity,
            "initial_equity": initial_equity,
        }
