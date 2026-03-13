# Running Backtests

This guide covers single backtests, batch parameter sweeps, performance analysis, and stress testing.

## Single Backtest

### Basic Setup

```python
from decimal import Decimal
from datetime import datetime
from data.universe import Universe
from execution.backtest import BacktestContext
from strategy.sma_crossover import SmaCrossover

# Define instruments and timeframe
universe = Universe.from_symbols(
    symbols=["BTC/USD", "ETH/USD"],
    timeframe="1h",
    exchange="kraken",
)

# Configure execution
ctx = BacktestContext(
    universe=universe,
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    initial_cash=Decimal("10000"),
    fee_rate=Decimal("0.0026"),
    slippage_pct=Decimal("0.0001"),
    max_position_size=Decimal("1.0"),
)

# Run
strategy = SmaCrossover(ctx, params={
    "fast_period": 10,
    "slow_period": 30,
    "quantity": "0.01",
    "symbols": ["BTC/USD", "ETH/USD"],
})
results = ctx.run(strategy)
```

### BacktestContext Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `universe` | `Universe` | required | Instruments and timeframe |
| `start` | `datetime` | `None` | Start date (None = earliest available) |
| `end` | `datetime` | `None` | End date (None = latest available) |
| `initial_cash` | `Decimal` | `10000` | Starting account balance |
| `fee_rate` | `Decimal` | `0.0026` | Fee per trade as fraction (0.26%) |
| `slippage_pct` | `Decimal` | `0.0001` | Slippage as fraction of price |
| `max_position_size` | `Decimal` | `1.0` | Maximum position quantity |
| `data_dir` | `Path` | `None` | Custom data directory |
| `exchange` | `str` | `None` | Exchange name (auto-detected from universe) |
| `margin_mode` | `bool` | `False` | Enable margin trading simulation |
| `leverage` | `Decimal` | `1` | Leverage multiplier (margin mode) |
| `spread_pips` | `Decimal` | `0` | Bid-ask spread in pips (forex) |

### Forex Backtesting

```python
universe = Universe.from_forex_symbols(
    symbols=["EUR/USD", "GBP/USD"],
    timeframe="1h",
    exchange="oanda",
)

ctx = BacktestContext(
    universe=universe,
    initial_cash=Decimal("100000"),
    fee_rate=Decimal("0"),           # OANDA has no commission
    spread_pips=Decimal("1.5"),      # spread-based cost model
    margin_mode=True,
    leverage=Decimal("50"),
)
```

### Results Structure

`ctx.run(strategy)` returns a dict with:

| Key | Type | Description |
|-----|------|-------------|
| `equity_curve` | `list[(datetime, Decimal)]` | Time series of account equity |
| `fills` | `list[Fill]` | All executed trades |
| `bars_processed` | `int` | Number of bar groups processed |
| `initial_equity` | `Decimal` | Starting equity |
| `final_equity` | `Decimal` | Ending equity |

## Performance Metrics

```python
from analytics.performance import compute_performance

metrics = compute_performance(
    equity_curve=results["equity_curve"],
    fills=results["fills"],
)
```

### Available Metrics

| Metric | Description |
|--------|-------------|
| `total_return` | (final - initial) / initial |
| `annualized_return` | Return scaled to yearly rate |
| `sharpe_ratio` | Risk-adjusted return (annualized) |
| `sortino_ratio` | Downside-risk-adjusted return |
| `calmar_ratio` | Annualized return / max drawdown |
| `max_drawdown` | Largest peak-to-trough decline |
| `max_drawdown_duration` | Longest recovery period |
| `num_trades` | Total completed trades |
| `win_rate` | Fraction of profitable trades |
| `profit_factor` | Gross profit / gross loss |
| `avg_win` | Average winning trade size |
| `avg_loss` | Average losing trade size |
| `total_fees` | Total fees paid |

## Batch Backtesting

Run parameter sweeps to find optimal strategy settings:

```python
from execution.batch import BatchBacktest, ParameterGrid

# Define parameter grid
grid = ParameterGrid({
    "fast_period": [5, 10, 15, 20],
    "slow_period": [20, 30, 50],
    "quantity": ["0.01"],
})

# Configure batch
batch = BatchBacktest(
    strategy_class=SmaCrossover,
    universe=universe,
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    base_params={"symbols": ["BTC/USD"]},
    grid=grid,
    initial_cash=Decimal("10000"),
    n_workers=4,  # parallel processes
)

# Run all combinations
batch_results = batch.run()
```

### Analyzing Batch Results

```python
# View all results as a DataFrame
df = batch_results.as_dataframe()
print(df.sort_values("sharpe_ratio", ascending=False))

# Best parameters by Sharpe ratio
best = batch_results.best_by("sharpe_ratio")
print(f"Best params: {best['params']}")
print(f"Best Sharpe: {best['metrics']['sharpe_ratio']:.2f}")

# 2D heatmap for parameter sensitivity
heatmap = batch_results.heatmap_data("fast_period", "slow_period", "sharpe_ratio")

# 1D sensitivity analysis
sensitivity = batch_results.sensitivity("fast_period", "sharpe_ratio")
```

## Advanced Analytics

### Return Distribution

All statistics functions accept a DataFrame with a `close` column:

```python
import pandas as pd
from analytics.statistics import return_distribution

# Build a DataFrame from close prices
bars_df = pd.DataFrame({"close": [float(eq) for _, eq in results["equity_curve"]]})
dist = return_distribution(bars_df)
print(f"Mean return:  {dist['mean']:.6f}")
print(f"Skewness:     {dist['skewness']:.2f}")
print(f"Kurtosis:     {dist['kurtosis']:.2f}")
```

### Volatility Analysis

```python
from analytics.statistics import volatility_analysis

vol = volatility_analysis(bars_df)
print(f"Realized vol (ann): {vol['realized_vol']:.2%}")
print(f"Vol of vol:         {vol['vol_of_vol']:.4f}")
```

### Tail Risk

```python
from analytics.statistics import tail_risk_analysis

tail = tail_risk_analysis(bars_df)
print(f"VaR (95%):  {tail['var_95']:.4f}")
print(f"CVaR (95%): {tail['cvar_95']:.4f}")
```

### Correlation Analysis

```python
from analytics.correlation import correlation_matrix, rolling_correlation

# Static correlation between assets — pass {symbol: DataFrame_with_close}
corr = correlation_matrix({
    "BTC/USD": btc_bars_df,
    "ETH/USD": eth_bars_df,
})

# Rolling correlation between two assets — pass DataFrames with 'close' column
rolling = rolling_correlation(btc_bars_df, eth_bars_df, window=30)
```

## Backtesting via Persistra

The `processes/backtest.py` process runs backtests within the Persistra framework:

```bash
persistra process run backtest \
    -p strategy=sma_crossover \
    -p symbols=BTC/USD \
    -p timeframe=1h \
    -p params='{"fast_period":10,"slow_period":30}' \
    -p initial_cash=10000 \
    -p start=2024-01-01 \
    -p end=2024-12-31
```

Results are saved to Persistra state and visible in the dashboard.

## Tips

1. **Start with equal weight.** Before optimizing parameters, verify your strategy logic works correctly with simple settings.

2. **Use sufficient data.** Aim for at least 1 year of data for daily strategies, 3+ months for hourly. Short datasets lead to overfitting.

3. **Watch for look-ahead bias.** Only use data available at each bar's timestamp. The `PricePanel` enforces this by only providing historical bars.

4. **Account for costs.** Set realistic `fee_rate` and `slippage_pct`. A strategy profitable with zero fees may be unprofitable with realistic costs.

5. **Test out-of-sample.** Split your data into training and test periods. Optimize on training, validate on test.

6. **Check multiple metrics.** A high Sharpe ratio with 60% max drawdown may not be desirable. Look at Sharpe, Sortino, max drawdown, and profit factor together.
