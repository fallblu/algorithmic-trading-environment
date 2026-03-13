"""BacktestContext — historical replay with SimulatedBroker."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from analytics.metrics import compute_metrics
from broker.simulated import SimulatedBroker
from data.feed import HistoricalFeed
from data.store import MarketDataStore
from execution.context import BacktestResult, ExecutionContext
from models.bar import Bar
from models.order import Order
from portfolio.orchestrator import PortfolioOrchestrator
from portfolio.portfolio import Portfolio, StrategyAllocation
from risk.manager import RiskManager
from strategy.function_adapter import FunctionStrategy, compile_strategy_source
from strategy.registry import get_strategy

log = logging.getLogger(__name__)


class BacktestContext(ExecutionContext):
    """Runs a portfolio backtest over historical data."""

    def __init__(self, portfolio: Portfolio, store: MarketDataStore) -> None:
        self._portfolio = portfolio
        self._store = store
        self._broker = SimulatedBroker(initial_cash=portfolio.initial_cash)
        self._risk_mgr = RiskManager(portfolio.risk_config)
        self._orchestrator = PortfolioOrchestrator(portfolio.orchestration_code)
        self._current_ts = datetime.now(timezone.utc)
        self._strategies: dict[str, FunctionStrategy] = {}
        self._progress_callback = None

    @property
    def mode(self) -> str:
        return "backtest"

    def get_broker(self) -> SimulatedBroker:
        return self._broker

    def current_time(self) -> datetime:
        return self._current_ts

    def set_progress_callback(self, callback) -> None:
        """Set a callback(bars_done, total_bars) for progress reporting."""
        self._progress_callback = callback

    def run(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> BacktestResult:
        """Execute the full backtest and return results."""
        result = BacktestResult(portfolio_id=self._portfolio.id)

        # Build strategies
        self._build_strategies(result)
        if not self._strategies:
            result.errors.append("No valid strategies to backtest")
            return result

        # Collect all symbols and load feed
        all_symbols = self._collect_symbols()
        timeframe = self._portfolio.strategies[0].timeframe if self._portfolio.strategies else "1h"

        feed = HistoricalFeed(self._store, self._portfolio.exchange)
        feed.load(all_symbols, timeframe, start, end)
        result.total_bars = feed.total_groups

        if feed.total_groups == 0:
            result.errors.append(f"No data found for symbols {all_symbols}")
            return result

        # Load DataFrames for lookback
        dfs = feed.get_dataframes(all_symbols, timeframe, start, end)

        # Replay loop
        bars_so_far: dict[str, list[dict]] = {s: [] for s in all_symbols}

        while True:
            bar_group = feed.next_bar_group()
            if bar_group is None:
                break

            self._current_ts = bar_group[0].timestamp

            # Process bars through broker (updates positions, fills limits)
            fills_from_broker = self._broker.process_bars(bar_group)
            result.fills.extend(fills_from_broker)

            # Accumulate bars for DataFrame construction
            for bar in bar_group:
                bars_so_far[bar.symbol].append({
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                })

            # Run strategies
            strategy_signals: dict[str, list[Order]] = {}
            positions_by_strategy: dict[str, dict[str, float]] = {}

            for alloc in self._portfolio.strategies:
                sid = alloc.strategy_id
                strategy = self._strategies.get(sid)
                if strategy is None:
                    continue

                # Build per-strategy positions dict
                qty_map = self._broker.position_manager.get_all_quantities(
                    strategy_id=sid
                )
                positions_by_strategy[sid] = qty_map

                # Build bars DataFrame for this strategy's symbols
                strat_symbols = alloc.symbols or all_symbols
                bar_df = self._build_strategy_bars(bars_so_far, strat_symbols)
                if bar_df is None or len(bar_df) < 1:
                    strategy_signals[sid] = []
                    continue

                try:
                    orders = strategy.on_bar(bar_df, qty_map)
                    for order in orders:
                        order.strategy_id = sid
                    strategy_signals[sid] = orders
                except Exception as e:
                    result.errors.append(f"Strategy {sid} error at {self._current_ts}: {e}")
                    strategy_signals[sid] = []

            # Run orchestrator
            allocations = {
                a.strategy_id: a.allocation_pct for a in self._portfolio.strategies
            }
            market_dfs = {s: self._bars_to_df(bars_so_far[s]) for s in all_symbols}
            adjusted_allocs = self._orchestrator.run(
                strategy_signals, allocations, positions_by_strategy, market_dfs
            )

            # Submit orders (respecting allocations and risk)
            for alloc in self._portfolio.strategies:
                sid = alloc.strategy_id
                if adjusted_allocs.get(sid, 0) == 0:
                    continue  # paused by orchestrator

                for order in strategy_signals.get(sid, []):
                    allowed, reason = self._risk_mgr.check_order(order, self._broker)
                    if allowed:
                        self._broker.submit_order(order)
                    else:
                        log.debug("Order rejected by risk: %s", reason)

            # Check portfolio-level risk
            self._risk_mgr.check_portfolio(self._broker)

            # Record equity
            account = self._broker.get_account()
            result.equity_curve.append((self._current_ts, account.equity))
            result.bars_processed = feed.current_index

            if self._progress_callback:
                self._progress_callback(feed.current_index, feed.total_groups)

        # Compute final metrics
        result.fills = self._broker.fills
        result.metrics = compute_metrics(
            result.equity_curve,
            result.fills,
            initial_cash=self._portfolio.initial_cash,
        )

        return result

    def _build_strategies(self, result: BacktestResult) -> None:
        """Instantiate strategy objects from portfolio allocations."""
        for alloc in self._portfolio.strategies:
            try:
                if alloc.source_code:
                    strategy = FunctionStrategy(
                        source_code=alloc.source_code,
                        name=alloc.strategy_name,
                        symbols=alloc.symbols,
                        params=alloc.params,
                    )
                else:
                    cls = get_strategy(alloc.strategy_name)
                    strategy = cls(params=alloc.params)
                self._strategies[alloc.strategy_id] = strategy
            except Exception as e:
                result.errors.append(
                    f"Failed to build strategy '{alloc.strategy_name}': {e}"
                )

    def _collect_symbols(self) -> list[str]:
        """Collect unique symbols across all strategies."""
        symbols: set[str] = set()
        for alloc in self._portfolio.strategies:
            symbols.update(alloc.symbols)
        return sorted(symbols)

    def _build_strategy_bars(
        self, bars_so_far: dict[str, list[dict]], symbols: list[str]
    ) -> pd.DataFrame | None:
        """Build a DataFrame from accumulated bars for a strategy's symbols."""
        if len(symbols) == 1:
            rows = bars_so_far.get(symbols[0], [])
            if not rows:
                return None
            df = pd.DataFrame(rows)
            df.set_index("timestamp", inplace=True)
            return df

        # Multi-symbol: use first symbol for primary DataFrame
        rows = bars_so_far.get(symbols[0], [])
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        return df

    def _bars_to_df(self, rows: list[dict]) -> pd.DataFrame:
        """Convert accumulated bar dicts to a DataFrame."""
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        return df
