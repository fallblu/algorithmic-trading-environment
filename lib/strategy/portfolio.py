"""Portfolio optimization — mean-variance, risk parity, and rebalancing strategy."""

import logging
from decimal import Decimal

import numpy as np
import pandas as pd

from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy
from strategy.registry import register

log = logging.getLogger(__name__)


class PortfolioOptimizer:
    """Portfolio optimization methods for computing target weights.

    Supports mean-variance, minimum variance, risk parity, and equal weight.
    """

    @staticmethod
    def mean_variance(returns_df: pd.DataFrame, risk_free_rate: float = 0.0) -> dict[str, float]:
        """Mean-variance optimization (max Sharpe ratio).

        Args:
            returns_df: DataFrame of asset returns (columns = symbols).
            risk_free_rate: Risk-free rate for Sharpe computation.

        Returns:
            Dict of symbol -> target weight (sums to 1.0).
        """
        symbols = returns_df.columns.tolist()
        n = len(symbols)

        if n == 0:
            return {}

        mean_returns = returns_df.mean().values
        cov_matrix = returns_df.cov().values

        # Analytical solution for max Sharpe with no constraints
        try:
            inv_cov = np.linalg.inv(cov_matrix)
        except np.linalg.LinAlgError:
            log.warning("Singular covariance matrix, falling back to equal weight")
            return {s: 1.0 / n for s in symbols}

        excess_returns = mean_returns - risk_free_rate
        raw_weights = inv_cov @ excess_returns

        # Normalize to sum to 1
        weight_sum = np.sum(raw_weights)
        if abs(weight_sum) < 1e-10:
            return {s: 1.0 / n for s in symbols}

        weights = raw_weights / weight_sum

        # Clip negative weights to 0 (long-only constraint)
        weights = np.maximum(weights, 0)
        weight_sum = np.sum(weights)
        if weight_sum > 0:
            weights = weights / weight_sum

        return {symbols[i]: float(weights[i]) for i in range(n)}

    @staticmethod
    def min_variance(returns_df: pd.DataFrame) -> dict[str, float]:
        """Minimum variance portfolio (no return forecasts needed).

        Args:
            returns_df: DataFrame of asset returns.

        Returns:
            Dict of symbol -> target weight.
        """
        symbols = returns_df.columns.tolist()
        n = len(symbols)

        if n == 0:
            return {}

        cov_matrix = returns_df.cov().values

        try:
            inv_cov = np.linalg.inv(cov_matrix)
        except np.linalg.LinAlgError:
            return {s: 1.0 / n for s in symbols}

        ones = np.ones(n)
        raw_weights = inv_cov @ ones
        weights = raw_weights / np.sum(raw_weights)

        # Long-only
        weights = np.maximum(weights, 0)
        weight_sum = np.sum(weights)
        if weight_sum > 0:
            weights = weights / weight_sum

        return {symbols[i]: float(weights[i]) for i in range(n)}

    @staticmethod
    def risk_parity(returns_df: pd.DataFrame) -> dict[str, float]:
        """Risk parity — equal risk contribution from each asset.

        Approximation: weight inversely proportional to volatility.

        Args:
            returns_df: DataFrame of asset returns.

        Returns:
            Dict of symbol -> target weight.
        """
        symbols = returns_df.columns.tolist()
        n = len(symbols)

        if n == 0:
            return {}

        vols = returns_df.std().values
        # Avoid division by zero
        vols = np.where(vols < 1e-10, 1e-10, vols)

        inv_vols = 1.0 / vols
        weights = inv_vols / np.sum(inv_vols)

        return {symbols[i]: float(weights[i]) for i in range(n)}

    @staticmethod
    def equal_weight(symbols: list[str]) -> dict[str, float]:
        """Simple 1/N equal weight allocation.

        Args:
            symbols: List of symbols.

        Returns:
            Dict of symbol -> target weight.
        """
        n = len(symbols)
        if n == 0:
            return {}
        w = 1.0 / n
        return {s: w for s in symbols}


@register("portfolio_rebalance")
class PortfolioRebalance(Strategy):
    """Portfolio rebalancing strategy.

    Periodically rebalances portfolio to target weights computed by
    PortfolioOptimizer. Generates orders to move from current to target allocation.

    Parameters:
        method: Optimization method ('mean_variance', 'min_variance', 'risk_parity', 'equal_weight')
        rebalance_freq: Rebalance every N bars (default 20)
        symbols: List of symbols to allocate across
        lookback_returns: Lookback for returns computation (default 60)
    """

    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.method = self.params.get("method", "equal_weight")
        self.rebalance_freq = int(self.params.get("rebalance_freq", 20))
        self.lookback_returns = int(self.params.get("lookback_returns", 60))
        self._bar_count = 0
        self._target_weights: dict[str, float] = {}

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD", "ETH/USD"])

    def lookback(self) -> int:
        return self.lookback_returns + 5

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        self._bar_count += 1

        # Only rebalance at specified frequency
        if self._bar_count % self.rebalance_freq != 0:
            return []

        symbols = panel.index.get_level_values("symbol").unique().tolist()
        optimizer = PortfolioOptimizer()

        # Compute target weights
        if self.method == "equal_weight":
            self._target_weights = optimizer.equal_weight(symbols)
        else:
            # Build returns DataFrame
            returns_dict = {}
            for symbol in symbols:
                sym_data = panel.xs(symbol, level="symbol")
                if len(sym_data) < self.lookback_returns:
                    continue
                closes = sym_data["close"].values.astype(float)
                returns = np.diff(np.log(closes[-self.lookback_returns:]))
                returns_dict[symbol] = returns

            if not returns_dict:
                return []

            # Align lengths
            min_len = min(len(r) for r in returns_dict.values())
            returns_df = pd.DataFrame({s: r[-min_len:] for s, r in returns_dict.items()})

            if self.method == "mean_variance":
                self._target_weights = optimizer.mean_variance(returns_df)
            elif self.method == "min_variance":
                self._target_weights = optimizer.min_variance(returns_df)
            elif self.method == "risk_parity":
                self._target_weights = optimizer.risk_parity(returns_df)
            else:
                self._target_weights = optimizer.equal_weight(symbols)

        log.info("Target weights: %s", {s: f"{w:.2%}" for s, w in self._target_weights.items()})

        # Generate rebalancing orders
        return self._generate_rebalance_orders(panel, symbols)

    def _generate_rebalance_orders(self, panel: pd.DataFrame, symbols: list[str]) -> list[Order]:
        """Generate orders to move from current to target weights."""
        broker = self.ctx.get_broker()
        account = broker.get_account()
        equity = float(account.equity)
        orders: list[Order] = []

        for symbol in symbols:
            target_weight = self._target_weights.get(symbol, 0.0)
            target_notional = equity * target_weight

            instrument = self.ctx.get_universe().instruments.get(symbol)
            if instrument is None:
                continue

            # Get current price from panel
            sym_data = panel.xs(symbol, level="symbol")
            current_price = float(sym_data["close"].values[-1])
            if current_price <= 0:
                continue

            target_qty = Decimal(str(round(target_notional / current_price, 8)))

            position = broker.get_position(instrument)
            current_qty = position.quantity if position is not None else Decimal("0")
            current_side = position.side if position is not None else OrderSide.BUY

            diff = target_qty - current_qty

            # Skip small adjustments (< 1% of position)
            if abs(float(diff)) < abs(float(target_qty)) * 0.01:
                continue

            if diff > 0:
                orders.append(Order(
                    instrument=instrument,
                    side=OrderSide.BUY,
                    type=OrderType.MARKET,
                    quantity=abs(diff),
                    strategy_id="portfolio_rebalance",
                ))
                log.info("REBAL BUY %s: qty=%s (target_weight=%.2%%)",
                         symbol, abs(diff), target_weight * 100)
            elif diff < 0:
                sell_qty = min(abs(diff), current_qty)
                if sell_qty > 0:
                    orders.append(Order(
                        instrument=instrument,
                        side=OrderSide.SELL,
                        type=OrderType.MARKET,
                        quantity=sell_qty,
                        strategy_id="portfolio_rebalance",
                    ))
                    log.info("REBAL SELL %s: qty=%s (target_weight=%.2%%)",
                             symbol, sell_qty, target_weight * 100)

        return orders
