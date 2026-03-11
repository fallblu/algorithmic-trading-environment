"""Momentum / trend-following strategies — breakout, MACD, ADX."""

import logging
from decimal import Decimal

import numpy as np
import pandas as pd

from analytics.indicators import adx, atr, macd, sma
from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy
from strategy.registry import register

log = logging.getLogger(__name__)


@register("breakout")
class BreakoutStrategy(Strategy):
    """N-period high/low breakout with ATR-based stops.

    Enter long when price breaks above N-period high.
    Enter short when price breaks below N-period low.
    Uses ATR for stop-loss placement.

    Parameters:
        breakout_period: Lookback for high/low channel (default 20)
        atr_period: ATR period for stops (default 14)
        atr_multiplier: ATR multiplier for stop distance (default 2.0)
        quantity: Position size per trade
        symbols: List of symbols to trade
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.breakout_period = int(self.params.get("breakout_period", 20))
        self.atr_period = int(self.params.get("atr_period", 14))
        self.atr_multiplier = float(self.params.get("atr_multiplier", 2.0))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
        self._entry_prices: dict[str, float] = {}
        self._stop_prices: dict[str, float] = {}

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return max(self.breakout_period, self.atr_period) + 5

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        orders: list[Order] = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            sym_data = panel.xs(symbol, level="symbol")
            if len(sym_data) < self.breakout_period:
                continue

            highs = sym_data["high"].values.astype(float)
            lows = sym_data["low"].values.astype(float)
            closes = sym_data["close"].values.astype(float)

            channel_high = np.max(highs[-self.breakout_period - 1:-1])
            channel_low = np.min(lows[-self.breakout_period - 1:-1])
            current_price = closes[-1]

            atr_vals = atr(highs, lows, closes, self.atr_period)
            current_atr = float(atr_vals[-1]) if len(atr_vals) > 0 else current_price * 0.02

            broker = self.ctx.get_broker()
            instrument = self.ctx.get_universe().instruments[symbol]
            position = broker.get_position(instrument)

            # Check stop-loss on existing position
            if symbol in self._stop_prices and position is not None and position.quantity > 0:
                if current_price <= self._stop_prices[symbol]:
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.SELL,
                        type=OrderType.MARKET,
                        quantity=position.quantity,
                        strategy_id="breakout",
                    ))
                    log.info("STOP %s: price %.4f <= stop %.4f", symbol, current_price, self._stop_prices[symbol])
                    del self._stop_prices[symbol]
                    del self._entry_prices[symbol]
                    continue

            # Breakout entry
            if current_price > channel_high and (position is None or position.quantity == 0):
                orders.append(Order(
                    instrument=instrument,
                    side=OrderSide.BUY,
                    type=OrderType.MARKET,
                    quantity=self.quantity,
                    strategy_id="breakout",
                ))
                self._entry_prices[symbol] = current_price
                self._stop_prices[symbol] = current_price - current_atr * self.atr_multiplier
                log.info("BREAKOUT BUY %s: price %.4f > channel %.4f, stop=%.4f",
                         symbol, current_price, channel_high, self._stop_prices[symbol])

        return orders


@register("macd_trend")
class MACDTrend(Strategy):
    """MACD trend follower.

    Enter on MACD line crossing above signal line, exit on reverse.

    Parameters:
        fast_period: Fast EMA period (default 12)
        slow_period: Slow EMA period (default 26)
        signal_period: Signal line period (default 9)
        quantity: Position size per trade
        symbols: List of symbols to trade
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.fast_period = int(self.params.get("fast_period", 12))
        self.slow_period = int(self.params.get("slow_period", 26))
        self.signal_period = int(self.params.get("signal_period", 9))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
        self._prev_histogram: dict[str, float | None] = {}

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return self.slow_period + self.signal_period + 5

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        orders: list[Order] = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            sym_data = panel.xs(symbol, level="symbol")
            if len(sym_data) < self.slow_period + self.signal_period:
                continue

            closes = sym_data["close"].values.astype(float)
            macd_line, signal_line, histogram = macd(closes, self.fast_period, self.slow_period, self.signal_period)

            if len(histogram) < 2:
                continue

            current_hist = histogram[-1]
            prev_hist = self._prev_histogram.get(symbol)

            broker = self.ctx.get_broker()
            instrument = self.ctx.get_universe().instruments[symbol]
            position = broker.get_position(instrument)

            if prev_hist is not None:
                # Bullish crossover: histogram goes from negative to positive
                if prev_hist <= 0 and current_hist > 0:
                    if position is None or position.quantity == 0:
                        orders.append(Order(
                            instrument=instrument,
                            side=OrderSide.BUY,
                            type=OrderType.MARKET,
                            quantity=self.quantity,
                            strategy_id="macd_trend",
                        ))
                        log.info("MACD BUY %s: histogram crossed positive (%.6f)", symbol, current_hist)

                # Bearish crossover: histogram goes from positive to negative
                elif prev_hist >= 0 and current_hist < 0:
                    if position is not None and position.side == OrderSide.BUY and position.quantity > 0:
                        orders.append(Order(
                            instrument=instrument,
                            side=OrderSide.SELL,
                            type=OrderType.MARKET,
                            quantity=position.quantity,
                            strategy_id="macd_trend",
                        ))
                        log.info("MACD SELL %s: histogram crossed negative (%.6f)", symbol, current_hist)

            self._prev_histogram[symbol] = current_hist

        return orders


@register("adx_trend")
class ADXTrend(Strategy):
    """ADX trend filter with SMA entry.

    Only enters momentum trades when ADX > threshold (strong trend).
    Uses SMA crossover for entry signals.

    Parameters:
        adx_period: ADX period (default 14)
        adx_threshold: Minimum ADX for trend confirmation (default 25)
        fast_period: Fast SMA period (default 10)
        slow_period: Slow SMA period (default 30)
        quantity: Position size per trade
        symbols: List of symbols to trade
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.adx_period = int(self.params.get("adx_period", 14))
        self.adx_threshold = float(self.params.get("adx_threshold", 25))
        self.fast_period = int(self.params.get("fast_period", 10))
        self.slow_period = int(self.params.get("slow_period", 30))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
        self._prev_fast_above: dict[str, bool | None] = {}

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return max(self.adx_period, self.slow_period) + 10

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        orders: list[Order] = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            sym_data = panel.xs(symbol, level="symbol")
            if len(sym_data) < max(self.adx_period, self.slow_period) + 5:
                continue

            highs = sym_data["high"].values.astype(float)
            lows = sym_data["low"].values.astype(float)
            closes = sym_data["close"].values.astype(float)

            adx_vals = adx(highs, lows, closes, self.adx_period)
            if len(adx_vals) == 0:
                continue

            current_adx = adx_vals[-1]

            # Only trade when trend is strong
            if current_adx < self.adx_threshold:
                self._prev_fast_above[symbol] = None
                continue

            fast_sma_vals = sma(closes, self.fast_period)
            slow_sma_vals = sma(closes, self.slow_period)

            if len(fast_sma_vals) == 0 or len(slow_sma_vals) == 0:
                continue

            fast_above = fast_sma_vals[-1] > slow_sma_vals[-1]
            prev = self._prev_fast_above.get(symbol)

            broker = self.ctx.get_broker()
            instrument = self.ctx.get_universe().instruments[symbol]
            position = broker.get_position(instrument)

            if prev is not None and fast_above != prev:
                if fast_above and (position is None or position.quantity == 0):
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.BUY,
                        type=OrderType.MARKET,
                        quantity=self.quantity,
                        strategy_id="adx_trend",
                    ))
                    log.info("ADX BUY %s: ADX=%.2f fast>slow, trend strong", symbol, current_adx)

                elif not fast_above and position is not None and position.side == OrderSide.BUY:
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.SELL,
                        type=OrderType.MARKET,
                        quantity=position.quantity,
                        strategy_id="adx_trend",
                    ))
                    log.info("ADX SELL %s: ADX=%.2f fast<slow", symbol, current_adx)

            self._prev_fast_above[symbol] = fast_above

        return orders
