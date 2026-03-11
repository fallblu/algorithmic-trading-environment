"""SMA Crossover strategy — multi-ticker DataFrame-based implementation."""

import logging
from decimal import Decimal

import pandas as pd

from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy

log = logging.getLogger(__name__)


class SmaCrossover(Strategy):
    """Simple Moving Average crossover strategy.

    Goes long when fast SMA crosses above slow SMA.
    Exits (sells) when fast SMA crosses below slow SMA.
    Long-only. Supports multiple symbols simultaneously.
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.fast_period = int(self.params.get("fast_period", 10))
        self.slow_period = int(self.params.get("slow_period", 30))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
        self._prev_fast_above: dict[str, bool | None] = {}

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return self.slow_period

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        orders: list[Order] = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            sym_data = panel.xs(symbol, level="symbol")

            if len(sym_data) < self.slow_period:
                continue

            closes = sym_data["close"].values
            fast_sma = float(closes[-self.fast_period:].mean())
            slow_sma = float(closes[-self.slow_period:].mean())
            fast_above = fast_sma > slow_sma

            prev = self._prev_fast_above.get(symbol)

            if prev is not None and fast_above != prev:
                broker = self.ctx.get_broker()
                univ = self.ctx.get_universe()
                instrument = univ.instruments[symbol]
                position = broker.get_position(instrument)

                if fast_above and (position is None or position.quantity == 0):
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.BUY,
                        type=OrderType.MARKET,
                        quantity=self.quantity,
                        strategy_id="sma_crossover",
                    ))
                    log.info(
                        "BUY %s at %s: fast_sma=%.2f > slow_sma=%.2f, price=%.2f",
                        symbol, sym_data.index[-1], fast_sma, slow_sma, closes[-1],
                    )

                elif not fast_above and position is not None and position.quantity > 0:
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.SELL,
                        type=OrderType.MARKET,
                        quantity=position.quantity,
                        strategy_id="sma_crossover",
                    ))
                    log.info(
                        "SELL %s at %s: fast_sma=%.2f < slow_sma=%.2f, price=%.2f",
                        symbol, sym_data.index[-1], fast_sma, slow_sma, closes[-1],
                    )

            self._prev_fast_above[symbol] = fast_above

        return orders
