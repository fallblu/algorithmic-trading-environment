"""BacktestContext — bar-by-bar replay engine with simulated broker."""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from broker.base import Broker
from broker.simulated import SimulatedBroker
from data.feed import DataFeed
from data.historical import HistoricalFeed
from data.store import MarketDataStore
from execution.context import ExecutionContext
from models.bar import Bar
from models.instrument import Instrument
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


class BacktestContext(ExecutionContext):
    """Drives bar-by-bar replay for backtesting.

    Owns the replay loop: loads bars from HistoricalFeed, processes them
    through the SimulatedBroker, then calls strategy.on_bar().
    """

    mode = "backtest"

    def __init__(
        self,
        instrument: Instrument,
        timeframe: str = "1h",
        start: datetime | None = None,
        end: datetime | None = None,
        initial_cash: Decimal = Decimal("10000"),
        fee_rate: Decimal = Decimal("0.0026"),
        slippage_pct: Decimal = Decimal("0.0001"),
        max_position_size: Decimal = Decimal("1.0"),
        data_dir: Path | None = None,
    ):
        self.instrument = instrument
        self.timeframe = timeframe
        self.start = start
        self.end = end

        if data_dir is None:
            data_dir = Path(".persistra/market_data")

        self._store = MarketDataStore(data_dir)
        self._feed = HistoricalFeed(self._store, exchange=instrument.exchange)
        self._broker = SimulatedBroker(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_pct=slippage_pct,
        )
        self._risk_manager = RiskManager(max_position_size=max_position_size)
        self._current_time = datetime.now(timezone.utc)
        self._equity_curve: list[tuple[datetime, Decimal]] = []
        self._bars_processed: int = 0

    def get_feed(self, instrument: Instrument) -> DataFeed:
        return self._feed

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
        """Execute the backtest replay loop.

        Returns a results dict with equity curve, fills, and summary stats.
        """
        bars = self._feed.historical_bars(
            self.instrument, self.timeframe, self.start, self.end,
        )

        if not bars:
            log.warning("No bars found for %s %s", self.instrument.symbol, self.timeframe)
            return {"equity_curve": [], "fills": [], "bars_processed": 0}

        log.info(
            "Starting backtest: %s %s, %d bars from %s to %s",
            self.instrument.symbol,
            self.timeframe,
            len(bars),
            bars[0].timestamp,
            bars[-1].timestamp,
        )

        # Record initial equity
        initial_equity = self._broker.get_account().equity
        self._equity_curve.append((bars[0].timestamp, initial_equity))

        for bar in bars:
            self._current_time = bar.timestamp

            # 1. Process pending orders against this bar
            self._broker.process_bar(bar)

            # 2. Call strategy
            orders = strategy.on_bar(bar)

            # 3. Risk check + submit orders
            for order in orders:
                if self._risk_manager.check(order, self._broker):
                    self._broker.submit_order(order)
                else:
                    log.info("Order rejected by risk manager: %s", order.id)

            # 4. Record equity snapshot
            account = self._broker.get_account()
            self._equity_curve.append((bar.timestamp, account.equity))
            self._bars_processed += 1

        log.info(
            "Backtest complete: %d bars, %d fills, final equity: %s",
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
