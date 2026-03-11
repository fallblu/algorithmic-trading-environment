"""SMA Crossover strategy — extracted for reuse by backtest and live processes."""

import logging
from decimal import Decimal

from models.bar import Bar
from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy

log = logging.getLogger(__name__)


class SmaCrossover(Strategy):
    """Simple Moving Average crossover strategy.

    Goes long when fast SMA crosses above slow SMA.
    Exits (sells) when fast SMA crosses below slow SMA.
    Long-only for the thin-slice.
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.fast_period = int(self.params.get("fast_period", 10))
        self.slow_period = int(self.params.get("slow_period", 30))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
        self._closes: list[Decimal] = []
        self._prev_fast_above: bool | None = None

    def on_bar(self, bar: Bar) -> list[Order]:
        self._closes.append(bar.close)

        if len(self._closes) < self.slow_period:
            return []

        fast_sma = self._sma(self.fast_period)
        slow_sma = self._sma(self.slow_period)
        fast_above = fast_sma > slow_sma

        orders: list[Order] = []

        if self._prev_fast_above is not None and fast_above != self._prev_fast_above:
            broker = self.ctx.get_broker()
            instrument = self.params.get("_instrument")
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
                    "BUY signal at %s: fast_sma=%.2f > slow_sma=%.2f, price=%s",
                    bar.timestamp, fast_sma, slow_sma, bar.close,
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
                    "SELL signal at %s: fast_sma=%.2f < slow_sma=%.2f, price=%s",
                    bar.timestamp, fast_sma, slow_sma, bar.close,
                )

        self._prev_fast_above = fast_above
        return orders

    def _sma(self, period: int) -> float:
        window = self._closes[-period:]
        return float(sum(window)) / len(window)
