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
from analytics.performance import compute_metrics

metrics = compute_metrics(
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
| `volatility` | Annualized standard deviation of returns |
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
# Get all results sorted by Sharpe ratio
for result in batch_results.sorted_by("sharpe_ratio", descending=True):
    print(f"fast={result.params['fast_period']}, "
          f"slow={result.params['slow_period']}: "
          f"Sharpe={result.metrics['sharpe_ratio']:.2f}, "
          f"Return={result.metrics['total_return']:.2%}")

# Best parameters
best = batch_results.best("sharpe_ratio")
print(f"Best params: {best.params}")
```

## Advanced Analytics

### Return Distribution

```python
from analytics.statistics import return_distribution

dist = return_distribution(equity_curve)
print(f"Mean daily return: {dist['mean']:.4%}")
print(f"Skewness:          {dist['skewness']:.2f}")
print(f"Kurtosis:          {dist['kurtosis']:.2f}")
```

### Volatility Analysis

```python
from analytics.statistics import volatility_analysis

vol = volatility_analysis(equity_curve)
print(f"Realized vol (ann): {vol['annualized_vol']:.2%}")
print(f"Parkinson vol:      {vol['parkinson_vol']:.2%}")
```

### Tail Risk

```python
from analytics.statistics import tail_risk_analysis

tail = tail_risk_analysis(equity_curve)
print(f"VaR (95%):  {tail['var_95']:.2%}")
print(f"CVaR (95%): {tail['cvar_95']:.2%}")
```

### Regime Detection

```python
from analytics.regime import regime_detection

regimes = regime_detection(closes, n_regimes=3)
# Returns regime labels, transition probabilities, regime characteristics
```

### Correlation Analysis

```python
from analytics.correlation import correlation_matrix, rolling_correlation

# Static correlation between assets
corr = correlation_matrix(returns_dict)  # {symbol: returns_array}

# Rolling correlation between two assets
rolling = rolling_correlation(returns_a, returns_b, window=30)
```

## Backtesting via Persistra

The `processes/sma_crossover.py` process runs backtests within the Persistra framework:

```bash
persistra run sma_crossover --params '{
    "symbols": ["BTC/USD"],
    "timeframe": "1h",
    "fast_period": 10,
    "slow_period": 30,
    "quantity": "0.01",
    "initial_cash": 10000,
    "start": "2024-01-01",
    "end": "2024-12-31"
}'
```

Results are saved to Persistra state and visible in the dashboard.

## Tips

1. **Start with equal weight.** Before optimizing parameters, verify your strategy logic works correctly with simple settings.

2. **Use sufficient data.** Aim for at least 1 year of data for daily strategies, 3+ months for hourly. Short datasets lead to overfitting.

3. **Watch for look-ahead bias.** Only use data available at each bar's timestamp. The `PricePanel` enforces this by only providing historical bars.

4. **Account for costs.** Set realistic `fee_rate` and `slippage_pct`. A strategy profitable with zero fees may be unprofitable with realistic costs.

5. **Test out-of-sample.** Split your data into training and test periods. Optimize on training, validate on test.

6. **Check multiple metrics.** A high Sharpe ratio with 60% max drawdown may not be desirable. Look at Sharpe, Sortino, max drawdown, and profit factor together.
