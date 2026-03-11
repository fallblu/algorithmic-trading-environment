"""Pairs trading strategy — statistical spread trading based on cointegration."""

import logging
from decimal import Decimal

import numpy as np
import pandas as pd

from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy
from strategy.registry import register

log = logging.getLogger(__name__)


def _compute_spread(closes_a: np.ndarray, closes_b: np.ndarray) -> tuple[np.ndarray, float]:
    """Compute the spread between two price series using OLS hedge ratio.

    Returns (spread_series, hedge_ratio).
    """
    # OLS regression: A = beta * B + alpha
    X = np.column_stack([closes_b, np.ones(len(closes_b))])
    beta, alpha = np.linalg.lstsq(X, closes_a, rcond=None)[0]
    spread = closes_a - beta * closes_b - alpha
    return spread, float(beta)


def _zscore(series: np.ndarray, lookback: int) -> float:
    """Compute z-score of the latest value over a rolling window."""
    if len(series) < lookback:
        return 0.0
    window = series[-lookback:]
    mean = np.mean(window)
    std = np.std(window, ddof=1)
    if std < 1e-10:
        return 0.0
    return float((series[-1] - mean) / std)


@register("pairs")
class PairsTrading(Strategy):
    """Statistical pairs trading based on spread z-score.

    Requires exactly 2 symbols. Computes spread using OLS hedge ratio.
    Enters when z-score exceeds entry threshold, exits at mean reversion.

    Parameters:
        pair_symbols: List of exactly 2 symbols
        lookback: Window for z-score computation (default 30)
        entry_z: Z-score threshold to enter (default 2.0)
        exit_z: Z-score threshold to exit (default 0.5)
        quantity: Position size per leg
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        pair = self.params.get("pair_symbols", ["BTC/USD", "ETH/USD"])
        if len(pair) != 2:
            raise ValueError("pairs strategy requires exactly 2 symbols")
        self._symbol_a = pair[0]
        self._symbol_b = pair[1]
        self._lookback = int(self.params.get("lookback", 30))
        self._entry_z = float(self.params.get("entry_z", 2.0))
        self._exit_z = float(self.params.get("exit_z", 0.5))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
        self._in_trade = False
        self._trade_direction: str | None = None  # "long_spread" or "short_spread"

    def universe(self) -> list[str]:
        return [self._symbol_a, self._symbol_b]

    def lookback(self) -> int:
        return self._lookback + 20

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        symbols = panel.index.get_level_values("symbol").unique()
        if self._symbol_a not in symbols or self._symbol_b not in symbols:
            return []

        data_a = panel.xs(self._symbol_a, level="symbol")
        data_b = panel.xs(self._symbol_b, level="symbol")

        if len(data_a) < self._lookback or len(data_b) < self._lookback:
            return []

        closes_a = data_a["close"].values.astype(float)
        closes_b = data_b["close"].values.astype(float)

        n = min(len(closes_a), len(closes_b))
        closes_a = closes_a[-n:]
        closes_b = closes_b[-n:]

        spread, hedge_ratio = _compute_spread(closes_a, closes_b)
        z = _zscore(spread, self._lookback)

        broker = self.ctx.get_broker()
        univ = self.ctx.get_universe()
        inst_a = univ.instruments[self._symbol_a]
        inst_b = univ.instruments[self._symbol_b]
        orders: list[Order] = []

        hedge_qty = Decimal(str(abs(round(float(self.quantity) * abs(hedge_ratio), 8))))

        if not self._in_trade:
            # Enter: spread is far from mean
            if z > self._entry_z:
                # Short spread: sell A, buy B
                orders.append(Order(instrument=inst_a, side=OrderSide.SELL, type=OrderType.MARKET,
                                    quantity=self.quantity, strategy_id="pairs"))
                orders.append(Order(instrument=inst_b, side=OrderSide.BUY, type=OrderType.MARKET,
                                    quantity=hedge_qty, strategy_id="pairs"))
                self._in_trade = True
                self._trade_direction = "short_spread"
                log.info("PAIRS SHORT SPREAD: z=%.2f sell %s buy %s", z, self._symbol_a, self._symbol_b)

            elif z < -self._entry_z:
                # Long spread: buy A, sell B
                orders.append(Order(instrument=inst_a, side=OrderSide.BUY, type=OrderType.MARKET,
                                    quantity=self.quantity, strategy_id="pairs"))
                orders.append(Order(instrument=inst_b, side=OrderSide.SELL, type=OrderType.MARKET,
                                    quantity=hedge_qty, strategy_id="pairs"))
                self._in_trade = True
                self._trade_direction = "long_spread"
                log.info("PAIRS LONG SPREAD: z=%.2f buy %s sell %s", z, self._symbol_a, self._symbol_b)

        else:
            # Exit: spread has reverted toward mean
            if self._trade_direction == "short_spread" and z < self._exit_z:
                pos_a = broker.get_position(inst_a)
                pos_b = broker.get_position(inst_b)
                if pos_a and pos_a.quantity > 0:
                    orders.append(Order(instrument=inst_a, side=OrderSide.BUY, type=OrderType.MARKET,
                                        quantity=pos_a.quantity, strategy_id="pairs"))
                if pos_b and pos_b.quantity > 0:
                    orders.append(Order(instrument=inst_b, side=OrderSide.SELL, type=OrderType.MARKET,
                                        quantity=pos_b.quantity, strategy_id="pairs"))
                self._in_trade = False
                log.info("PAIRS EXIT short spread: z=%.2f", z)

            elif self._trade_direction == "long_spread" and z > -self._exit_z:
                pos_a = broker.get_position(inst_a)
                pos_b = broker.get_position(inst_b)
                if pos_a and pos_a.quantity > 0:
                    orders.append(Order(instrument=inst_a, side=OrderSide.SELL, type=OrderType.MARKET,
                                        quantity=pos_a.quantity, strategy_id="pairs"))
                if pos_b and pos_b.quantity > 0:
                    orders.append(Order(instrument=inst_b, side=OrderSide.BUY, type=OrderType.MARKET,
                                        quantity=pos_b.quantity, strategy_id="pairs"))
                self._in_trade = False
                log.info("PAIRS EXIT long spread: z=%.2f", z)

        return orders
