# Portfolio Optimization

The Trader platform includes portfolio optimization tools for multi-asset allocation, along with a rebalancing strategy that automatically adjusts positions to target weights.

## Optimization Methods

The `PortfolioOptimizer` class provides four allocation methods:

```python
from strategy.portfolio import PortfolioOptimizer
import pandas as pd

optimizer = PortfolioOptimizer()
```

### Mean-Variance (Markowitz)

Maximizes the Sharpe ratio given expected returns and covariance matrix. Best when you have reliable return forecasts.

```python
weights = optimizer.mean_variance(returns_df, risk_free_rate=0.0)
# Returns: {"BTC/USD": 0.45, "ETH/USD": 0.35, "SOL/USD": 0.20}
```

- Long-only constraint (negative weights clipped to zero)
- Falls back to equal weight if covariance matrix is singular
- Works best with 30+ data points for stable estimates

### Minimum Variance

Minimizes portfolio variance without needing return forecasts. Useful when you distrust return predictions but want lower volatility.

```python
weights = optimizer.min_variance(returns_df)
```

- Tends to overweight low-volatility assets
- More robust than mean-variance with limited data

### Risk Parity

Equal risk contribution from each asset. Each asset contributes the same amount of portfolio volatility.

```python
weights = optimizer.risk_parity(returns_df)
```

- Weights inversely proportional to asset volatility
- Does not require return forecasts
- Good diversification across asset classes with different risk profiles

### Equal Weight

Simple 1/N allocation. Surprisingly competitive baseline that's hard to beat consistently.

```python
weights = optimizer.equal_weight(["BTC/USD", "ETH/USD", "SOL/USD"])
# Returns: {"BTC/USD": 0.333, "ETH/USD": 0.333, "SOL/USD": 0.333}
```

### Method Comparison

| Method | Return Forecasts | Covariance Needed | Robustness | Best For |
|--------|:---:|:---:|:---:|---------|
| Mean-Variance | Yes | Yes | Low | Strong return signals |
| Min Variance | No | Yes | Medium | Low-vol portfolios |
| Risk Parity | No | Volatility only | High | Balanced risk budgets |
| Equal Weight | No | No | Highest | Default / baseline |

## Preparing Returns Data

All optimization methods (except equal weight) require a DataFrame of asset returns:

```python
import numpy as np
import pandas as pd

# From price series
prices = {
    "BTC/USD": np.array([50000, 51000, 50500, 52000, ...]),
    "ETH/USD": np.array([3000, 3050, 3020, 3100, ...]),
}

# Compute log returns
returns_dict = {}
for symbol, closes in prices.items():
    returns_dict[symbol] = np.diff(np.log(closes))

returns_df = pd.DataFrame(returns_dict)
```

Use at least 30-60 data points for stable estimates. Longer series give more reliable covariance estimates but may include outdated regime information.

## Portfolio Rebalance Strategy

The `portfolio_rebalance` strategy wraps `PortfolioOptimizer` and automatically generates orders to move from current to target weights.

### Setup

```python
from data.universe import Universe
from execution.backtest import BacktestContext
from strategy.portfolio import PortfolioRebalance
from decimal import Decimal

universe = Universe.from_symbols(
    symbols=["BTC/USD", "ETH/USD"],
    timeframe="1h",
    exchange="kraken",
)

ctx = BacktestContext(
    universe=universe,
    initial_cash=Decimal("100000"),
)

strategy = PortfolioRebalance(ctx, params={
    "method": "risk_parity",
    "rebalance_freq": 20,         # Rebalance every 20 bars
    "lookback_returns": 60,       # 60-bar window for return estimation
    "symbols": ["BTC/USD", "ETH/USD"],
})

results = ctx.run(strategy)
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `method` | `"equal_weight"` | Optimization method: `"mean_variance"`, `"min_variance"`, `"risk_parity"`, `"equal_weight"` |
| `rebalance_freq` | `20` | Rebalance every N bars |
| `lookback_returns` | `60` | Number of bars for return/covariance estimation |
| `symbols` | `["BTC/USD", "ETH/USD"]` | Symbols to allocate across |

### How Rebalancing Works

1. Every `rebalance_freq` bars, the strategy computes target weights using the selected method
2. Current positions are compared to target allocations based on account equity
3. Orders are generated to move from current to target weights
4. Small adjustments (< 1% of target position) are skipped to avoid excessive trading

### Rebalancing Frequency

The optimal rebalancing frequency depends on your cost structure:

| Frequency | Bars (1h) | Pros | Cons |
|-----------|-----------|------|------|
| Daily | 24 | Responsive to changes | Higher trading costs |
| Weekly | ~168 | Good balance | Moderate tracking error |
| Monthly | ~720 | Low costs | Slow to adapt |

For crypto (0.26% fees), weekly to bi-weekly rebalancing typically provides a good cost-benefit balance.

## Combining with Risk Management

Portfolio optimization works alongside the risk management layer:

```python
from config import RiskConfig
from risk.exposure import ExposureManager

# Set exposure limits
risk_config = RiskConfig(
    max_concentration_pct=Decimal("0.50"),  # No single asset > 50%
    max_drawdown_limit=Decimal("0.15"),
)

# The optimizer may suggest 60% in one asset,
# but the exposure manager will reject orders
# that would breach the 50% concentration limit
```

## Custom Allocation Strategies

You can use `PortfolioOptimizer` within your own strategy to compute weights, then apply custom logic for order generation:

```python
from strategy.base import Strategy
from strategy.portfolio import PortfolioOptimizer
from strategy.registry import register

@register("custom_allocation")
class CustomAllocation(Strategy):

    def on_bar(self, panel):
        optimizer = PortfolioOptimizer()
        symbols = panel.index.get_level_values("symbol").unique().tolist()

        # Use risk parity as base weights
        returns_df = self._build_returns(panel, symbols)
        base_weights = optimizer.risk_parity(returns_df)

        # Apply custom tilts (e.g., momentum overlay)
        adjusted_weights = self._apply_momentum_tilt(base_weights, panel)

        # Generate rebalancing orders
        return self._rebalance_to(adjusted_weights)
```

## Interpreting Results

After running a portfolio optimization backtest, examine:

1. **Weight stability** — Do weights change drastically at each rebalance? Volatile weights suggest estimation noise.

2. **Turnover** — Total quantity traded / portfolio value. High turnover erodes returns through fees.

3. **Diversification** — Check that the optimizer isn't concentrating into 1-2 assets (especially mean-variance).

4. **Risk metrics** — Compare Sharpe ratios, max drawdown, and volatility across methods to find the best fit for your risk tolerance.

```python
from analytics.performance import compute_metrics

metrics = compute_metrics(results["equity_curve"], results["fills"])

print(f"Method: risk_parity")
print(f"  Return:       {metrics['total_return']:.2%}")
print(f"  Sharpe:       {metrics['sharpe_ratio']:.2f}")
print(f"  Max Drawdown: {metrics['max_drawdown']:.2%}")
print(f"  Trades:       {metrics['num_trades']}")
print(f"  Total Fees:   {metrics['total_fees']:.2f}")
```
