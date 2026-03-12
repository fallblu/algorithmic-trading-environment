"""Mean reversion strategies — Bollinger Band bounce and RSI overbought/oversold."""

import logging
from decimal import Decimal

import pandas as pd

from analytics.indicators import bollinger_bands, rsi
from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy
from strategy.registry import register

log = logging.getLogger(__name__)


@register("bollinger_reversion")
class BollingerReversion(Strategy):
    """Bollinger Band mean reversion strategy.

    Enter long when price touches lower band (oversold), exit at middle band.
    Enter short when price touches upper band (overbought), exit at middle band.

    Parameters:
        period: Bollinger band period (default 20)
        num_std: Number of standard deviations (default 2.0)
        quantity: Position size per trade
        symbols: List of symbols to trade
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.period = int(self.params.get("period", 20))
        self.num_std = float(self.params.get("num_std", 2.0))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return self.period + 5

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        orders: list[Order] = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            sym_data = panel.xs(symbol, level="symbol")
            if len(sym_data) < self.period:
                continue

            closes = sym_data["close"].values.astype(float)
            upper, middle, lower = bollinger_bands(closes, self.period, self.num_std)

            if len(upper) == 0:
                continue

            current_price = closes[-1]
            broker = self.ctx.get_broker()
            instrument = self.ctx.get_universe().instruments[symbol]
            position = broker.get_position(instrument)

            # Buy when price touches lower band (oversold)
            if current_price <= lower[-1] and (position is None or position.quantity == 0):
                orders.append(Order(
                    instrument=instrument,
                    side=OrderSide.BUY,
                    type=OrderType.MARKET,
                    quantity=self.quantity,
                    strategy_id="bollinger_reversion",
                ))
                log.info("BUY %s: price %.4f <= lower band %.4f", symbol, current_price, lower[-1])

            # Exit long at middle band
            elif current_price >= middle[-1] and position is not None and position.side == OrderSide.BUY:
                orders.append(Order(
                    instrument=instrument,
                    side=OrderSide.SELL,
                    type=OrderType.MARKET,
                    quantity=position.quantity,
                    strategy_id="bollinger_reversion",
                ))
                log.info("EXIT LONG %s: price %.4f >= middle band %.4f", symbol, current_price, middle[-1])

        return orders


@register("rsi_reversion")
class RSIReversion(Strategy):
    """RSI mean reversion strategy.

    Buy when RSI < oversold_threshold, sell when RSI > overbought_threshold.

    Parameters:
        rsi_period: RSI calculation period (default 14)
        oversold: RSI threshold for buy signal (default 30)
        overbought: RSI threshold for sell signal (default 70)
        quantity: Position size per trade
        symbols: List of symbols to trade
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.rsi_period = int(self.params.get("rsi_period", 14))
        self.oversold = float(self.params.get("oversold", 30))
        self.overbought = float(self.params.get("overbought", 70))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return self.rsi_period + 5

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        orders: list[Order] = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            sym_data = panel.xs(symbol, level="symbol")
            if len(sym_data) < self.rsi_period + 1:
                continue

            closes = sym_data["close"].values.astype(float)
            rsi_vals = rsi(closes, self.rsi_period)

            if len(rsi_vals) == 0:
                continue

            current_rsi = rsi_vals[-1]
            broker = self.ctx.get_broker()
            instrument = self.ctx.get_universe().instruments[symbol]
            position = broker.get_position(instrument)

            if current_rsi < self.oversold and (position is None or position.quantity == 0):
                orders.append(Order(
                    instrument=instrument,
                    side=OrderSide.BUY,
                    type=OrderType.MARKET,
                    quantity=self.quantity,
                    strategy_id="rsi_reversion",
                ))
                log.info("BUY %s: RSI %.2f < %.2f (oversold)", symbol, current_rsi, self.oversold)

            elif current_rsi > self.overbought and position is not None and position.side == OrderSide.BUY:
                orders.append(Order(
                    instrument=instrument,
                    side=OrderSide.SELL,
                    type=OrderType.MARKET,
                    quantity=position.quantity,
                    strategy_id="rsi_reversion",
                ))
                log.info("SELL %s: RSI %.2f > %.2f (overbought)", symbol, current_rsi, self.overbought)

        return orders
