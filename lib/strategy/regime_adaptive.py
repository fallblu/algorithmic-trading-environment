"""Regime-adaptive strategy — switches sub-strategies based on HMM regime detection."""

import logging
from decimal import Decimal

import numpy as np
import pandas as pd

from models.order import Order
from strategy.base import Strategy
from strategy.registry import register

log = logging.getLogger(__name__)


@register("regime_adaptive")
class RegimeAdaptive(Strategy):
    """Regime-aware composite strategy.

    Uses a simplified volatility regime classifier to switch between
    momentum and mean-reversion behavior:
    - Low volatility regime: use momentum (trend-following) signals
    - High volatility regime: use mean-reversion signals
    - Extreme volatility: reduce position sizes or go flat

    Parameters:
        vol_lookback: Window for volatility regime classification (default 21)
        vol_threshold: Annualized vol threshold separating regimes (default 0.3)
        extreme_vol_threshold: Vol above which we go flat (default 0.6)
        fast_period: Fast MA period for momentum (default 10)
        slow_period: Slow MA period for momentum (default 30)
        bb_period: Bollinger band period for reversion (default 20)
        quantity: Base position size
        symbols: List of symbols to trade
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.vol_lookback = int(self.params.get("vol_lookback", 21))
        self.vol_threshold = float(self.params.get("vol_threshold", 0.3))
        self.extreme_vol_threshold = float(self.params.get("extreme_vol_threshold", 0.6))
        self.fast_period = int(self.params.get("fast_period", 10))
        self.slow_period = int(self.params.get("slow_period", 30))
        self.bb_period = int(self.params.get("bb_period", 20))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
        self._prev_fast_above: dict[str, bool | None] = {}
        self._current_regime: dict[str, str] = {}

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return max(self.vol_lookback, self.slow_period, self.bb_period) + 10

    def _classify_regime(self, closes: np.ndarray) -> str:
        """Classify current market regime based on realized volatility."""
        if len(closes) < self.vol_lookback + 1:
            return "unknown"

        returns = np.diff(np.log(closes[-self.vol_lookback - 1:]))
        annualized_vol = float(np.std(returns, ddof=1) * np.sqrt(252))

        if annualized_vol > self.extreme_vol_threshold:
            return "extreme"
        elif annualized_vol > self.vol_threshold:
            return "high_vol"
        else:
            return "low_vol"

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        from analytics.indicators import bollinger_bands, sma

        orders: list[Order] = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            sym_data = panel.xs(symbol, level="symbol")
            if len(sym_data) < self.lookback():
                continue

            closes = sym_data["close"].values.astype(float)
            regime = self._classify_regime(closes)
            self._current_regime[symbol] = regime

            broker = self.ctx.get_broker()
            instrument = self.ctx.get_universe().instruments[symbol]
            position = broker.get_position(instrument)

            if regime == "extreme":
                # Close all positions in extreme volatility
                if position is not None and position.quantity > 0:
                    from models.order import OrderSide, OrderType
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY,
                        type=OrderType.MARKET,
                        quantity=position.quantity,
                        strategy_id="regime_adaptive",
                    ))
                    log.info("REGIME FLAT %s: extreme vol, closing position", symbol)
                continue

            elif regime == "low_vol":
                # Momentum: SMA crossover
                fast_vals = sma(closes, self.fast_period)
                slow_vals = sma(closes, self.slow_period)
                if len(fast_vals) == 0 or len(slow_vals) == 0:
                    continue

                fast_above = fast_vals[-1] > slow_vals[-1]
                prev = self._prev_fast_above.get(symbol)

                from models.order import OrderSide, OrderType

                if prev is not None and fast_above and not prev:
                    if position is None or position.quantity == 0:
                        orders.append(Order(
                            instrument=instrument,
                            side=OrderSide.BUY,
                            type=OrderType.MARKET,
                            quantity=self.quantity,
                            strategy_id="regime_adaptive",
                        ))
                        log.info("REGIME BUY %s: low vol momentum crossover", symbol)

                elif prev is not None and not fast_above and prev:
                    if position is not None and position.side == OrderSide.BUY:
                        orders.append(Order(
                            instrument=instrument,
                            side=OrderSide.SELL,
                            type=OrderType.MARKET,
                            quantity=position.quantity,
                            strategy_id="regime_adaptive",
                        ))
                        log.info("REGIME SELL %s: low vol momentum exit", symbol)

                self._prev_fast_above[symbol] = fast_above

            elif regime == "high_vol":
                # Mean reversion: Bollinger band bounce
                upper, middle, lower = bollinger_bands(closes, self.bb_period)
                if len(upper) == 0:
                    continue

                current_price = closes[-1]
                from models.order import OrderSide, OrderType

                if current_price <= lower[-1] and (position is None or position.quantity == 0):
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.BUY,
                        type=OrderType.MARKET,
                        quantity=self.quantity,
                        strategy_id="regime_adaptive",
                    ))
                    log.info("REGIME BUY %s: high vol mean reversion at lower band", symbol)

                elif current_price >= middle[-1] and position is not None and position.side == OrderSide.BUY:
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.SELL,
                        type=OrderType.MARKET,
                        quantity=position.quantity,
                        strategy_id="regime_adaptive",
                    ))
                    log.info("REGIME SELL %s: high vol mean reversion exit at middle", symbol)

        return orders
