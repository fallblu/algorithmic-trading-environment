"""Multi-timeframe strategy — higher TF trend direction + lower TF entry signals."""

import logging
from decimal import Decimal

import numpy as np
import pandas as pd

from analytics.indicators import ema, sma
from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy
from strategy.registry import register

log = logging.getLogger(__name__)


@register("multi_tf")
class MultiTimeframe(Strategy):
    """Multi-timeframe confirmation strategy.

    Uses a longer-period moving average on the same bar data to simulate
    a higher timeframe trend filter, combined with a shorter-period
    indicator for precise entry timing.

    Only takes trades aligned with the higher-timeframe trend direction.

    Parameters:
        trend_period: Long MA period simulating higher TF trend (default 100)
        entry_fast: Fast MA period for entry signals (default 10)
        entry_slow: Slow MA period for entry signals (default 30)
        trend_indicator: 'sma' or 'ema' for trend (default 'sma')
        entry_indicator: 'sma' or 'ema' for entry (default 'ema')
        quantity: Position size per trade
        symbols: List of symbols to trade
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.trend_period = int(self.params.get("trend_period", 100))
        self.entry_fast = int(self.params.get("entry_fast", 10))
        self.entry_slow = int(self.params.get("entry_slow", 30))
        self.trend_indicator = self.params.get("trend_indicator", "sma")
        self.entry_indicator = self.params.get("entry_indicator", "ema")
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
        self._prev_entry_above: dict[str, bool | None] = {}

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return self.trend_period + 5

    def _compute_ma(self, closes: np.ndarray, period: int, kind: str) -> np.ndarray:
        if kind == "ema":
            return ema(closes, period)
        return sma(closes, period)

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        orders: list[Order] = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            sym_data = panel.xs(symbol, level="symbol")
            if len(sym_data) < self.trend_period:
                continue

            closes = sym_data["close"].values.astype(float)

            # Higher-timeframe trend
            trend_ma = self._compute_ma(closes, self.trend_period, self.trend_indicator)
            if len(trend_ma) == 0:
                continue
            trend_bullish = closes[-1] > trend_ma[-1]

            # Entry signals
            fast_ma = self._compute_ma(closes, self.entry_fast, self.entry_indicator)
            slow_ma = self._compute_ma(closes, self.entry_slow, self.entry_indicator)
            if len(fast_ma) == 0 or len(slow_ma) == 0:
                continue

            entry_above = fast_ma[-1] > slow_ma[-1]
            prev = self._prev_entry_above.get(symbol)

            broker = self.ctx.get_broker()
            instrument = self.ctx.get_universe().instruments[symbol]
            position = broker.get_position(instrument)

            if prev is not None and entry_above != prev:
                # Only take BUY signals when trend is bullish
                if entry_above and trend_bullish:
                    if position is None or position.quantity == 0:
                        orders.append(Order(
                            instrument=instrument,
                            side=OrderSide.BUY,
                            type=OrderType.MARKET,
                            quantity=self.quantity,
                            strategy_id="multi_tf",
                        ))
                        log.info("MTF BUY %s: entry crossover + bullish trend", symbol)

                # Exit when entry crosses down (regardless of trend)
                elif not entry_above and position is not None and position.side == OrderSide.BUY:
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.SELL,
                        type=OrderType.MARKET,
                        quantity=position.quantity,
                        strategy_id="multi_tf",
                    ))
                    log.info("MTF SELL %s: entry crossover down", symbol)

            self._prev_entry_above[symbol] = entry_above

        return orders
