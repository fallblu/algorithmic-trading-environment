"""LiveContext — live feeds with real broker execution."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd

from broker.base import Broker
from data.kraken_ws import KrakenWebSocket
from data.oanda_stream import OandaStream
from execution.context import ExecutionContext
from models.bar import Bar
from models.fill import Fill
from models.order import Order
from portfolio.orchestrator import PortfolioOrchestrator
from portfolio.portfolio import Portfolio
from risk.manager import RiskManager
from strategy.function_adapter import FunctionStrategy
from strategy.registry import get_strategy

log = logging.getLogger(__name__)


class LiveContext(ExecutionContext):
    """Live trading — real market data + real broker execution.

    Error handling: log + skip bar + continue.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        broker: Broker,
        api_key: str = "",
        account_id: str = "",
        on_fill: callable | None = None,
        on_error: callable | None = None,
        on_status_change: callable | None = None,
    ) -> None:
        self._portfolio = portfolio
        self._broker = broker
        self._risk_mgr = RiskManager(portfolio.risk_config)
        self._orchestrator = PortfolioOrchestrator(portfolio.orchestration_code)
        self._current_ts = datetime.now(timezone.utc)
        self._strategies: dict[str, FunctionStrategy] = {}
        self._bars_history: dict[str, list[dict]] = {}
        self._equity_curve: list[tuple[datetime, float]] = []
        self._api_key = api_key
        self._account_id = account_id
        self._on_fill = on_fill
        self._on_error = on_error
        self._on_status_change = on_status_change
        self._running = False

        self._build_strategies()

    @property
    def mode(self) -> str:
        return "live"

    def get_broker(self) -> Broker:
        return self._broker

    def current_time(self) -> datetime:
        return self._current_ts

    @property
    def equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._equity_curve)

    @property
    def connection_status(self) -> str:
        if hasattr(self, "_feed"):
            return self._feed.connection_status
        return "disconnected"

    async def run(self) -> None:
        """Start live trading with real feeds and broker."""
        self._running = True
        all_symbols = self._collect_symbols()
        timeframe = self._portfolio.strategies[0].timeframe if self._portfolio.strategies else "1m"

        if self._portfolio.exchange == "oanda":
            self._feed = OandaStream(
                symbols=all_symbols,
                api_key=self._api_key,
                account_id=self._account_id,
                timeframe=timeframe,
                on_bar=self._on_bar,
                on_status_change=self._on_status_change,
            )
        else:
            self._feed = KrakenWebSocket(
                symbols=all_symbols,
                timeframe=timeframe,
                on_bar=self._on_bar,
                on_status_change=self._on_status_change,
            )

        await self._feed.connect()

    async def stop(self) -> None:
        self._running = False
        if hasattr(self, "_feed"):
            await self._feed.disconnect()

    def _on_bar(self, bar: Bar) -> None:
        """Handle each incoming bar — execute strategies with real broker."""
        try:
            self._current_ts = bar.timestamp

            # Check for new fills from the real broker
            fills = self._broker.get_fills(since=self._current_ts)
            for fill in fills:
                if self._on_fill:
                    self._on_fill(fill)

            # Accumulate bar history
            symbol = bar.symbol
            if symbol not in self._bars_history:
                self._bars_history[symbol] = []
            self._bars_history[symbol].append({
                "timestamp": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            })

            # Run strategies
            self._run_strategies_on_bar()

            # Record equity
            account = self._broker.get_account()
            self._equity_curve.append((self._current_ts, account.equity))

        except Exception as e:
            log.error("Error processing bar %s: %s", bar.symbol, e)
            if self._on_error:
                self._on_error(str(e))

    def _run_strategies_on_bar(self) -> None:
        """Execute strategies and submit orders to the real broker."""
        all_symbols = self._collect_symbols()
        strategy_signals: dict[str, list[Order]] = {}

        for alloc in self._portfolio.strategies:
            sid = alloc.strategy_id
            strategy = self._strategies.get(sid)
            if strategy is None:
                continue

            # Get positions from real broker
            positions = self._broker.get_positions()
            qty_map: dict[str, float] = {}
            for pos in positions:
                from models.position import PositionSide
                sign = 1.0 if pos.side == PositionSide.LONG else -1.0
                qty_map[pos.symbol] = sign * pos.quantity

            strat_symbols = alloc.symbols or all_symbols
            bar_df = self._build_bar_df(strat_symbols)
            if bar_df is None or len(bar_df) < 1:
                strategy_signals[sid] = []
                continue

            try:
                orders = strategy.on_bar(bar_df, qty_map)
                for order in orders:
                    order.strategy_id = sid
                strategy_signals[sid] = orders
            except Exception as e:
                log.error("Strategy %s error: %s", sid, e)
                if self._on_error:
                    self._on_error(f"Strategy {sid}: {e}")
                strategy_signals[sid] = []

        # Orchestrator
        allocations = {a.strategy_id: a.allocation_pct for a in self._portfolio.strategies}
        market_dfs = {s: self._bars_to_df(s) for s in all_symbols}
        adjusted = self._orchestrator.run(
            strategy_signals, allocations, {}, market_dfs
        )

        # Submit orders to real broker
        for alloc in self._portfolio.strategies:
            sid = alloc.strategy_id
            if adjusted.get(sid, 0) == 0:
                continue
            for order in strategy_signals.get(sid, []):
                allowed, reason = self._risk_mgr.check_order(order, self._broker)
                if allowed:
                    try:
                        self._broker.submit_order(order)
                    except Exception as e:
                        log.error("Failed to submit order: %s", e)
                        if self._on_error:
                            self._on_error(f"Order submission failed: {e}")

        self._risk_mgr.check_portfolio(self._broker)

    def _build_strategies(self) -> None:
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
                log.error("Failed to build strategy '%s': %s", alloc.strategy_name, e)

    def _collect_symbols(self) -> list[str]:
        symbols: set[str] = set()
        for alloc in self._portfolio.strategies:
            symbols.update(alloc.symbols)
        return sorted(symbols)

    def _build_bar_df(self, symbols: list[str]) -> pd.DataFrame | None:
        rows = self._bars_history.get(symbols[0], [])
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        return df

    def _bars_to_df(self, symbol: str) -> pd.DataFrame:
        rows = self._bars_history.get(symbol, [])
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        return df
