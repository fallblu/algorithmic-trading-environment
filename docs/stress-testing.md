# Stress Testing

Stress testing uses Monte Carlo simulation to quantify the uncertainty around backtest results. A single backtest produces one equity curve from one historical path -- stress testing generates thousands of alternative paths to answer questions like "how bad could it get?" and "what is the probability of ruin?"

## Why Stress Test

A backtest tells you what *did* happen. Stress testing tells you what *could* happen:

- A strategy with a 50% total return and 15% max drawdown on historical data might have a 10% probability of experiencing a 40% drawdown under slightly different market conditions.
- Two strategies with identical Sharpe ratios may have very different tail risk profiles.
- Confidence intervals on terminal wealth give a realistic range of outcomes rather than a single point estimate.

## Simulation Methods

The system supports two simulation methods, implemented in `lib/analytics/monte_carlo.py`.

### Bootstrap Resampling

Bootstrap resampling draws returns randomly (with replacement) from the actual strategy return series to build synthetic equity paths.

```python
from analytics.monte_carlo import bootstrap_equity_paths

paths = bootstrap_equity_paths(
    returns=returns_array,      # Historical return series from backtest
    n_simulations=1000,         # Number of synthetic paths
    path_length=None,           # Default: same length as returns
    block_size=1,               # 1 = simple bootstrap, >1 = block bootstrap
    initial_value=10000.0,      # Starting equity
    seed=42,                    # For reproducibility
)
# Returns: np.ndarray of shape (1000, len(returns))
```

**When to use:** Bootstrap is the default and generally preferred method. It makes no distributional assumptions -- it uses your actual returns, preserving their skewness and kurtosis.

**Block bootstrap:** Set `block_size > 1` to preserve autocorrelation in returns. A block size of 5-10 is reasonable for daily returns. The algorithm samples contiguous blocks of returns rather than individual observations.

**Limitations:** Assumes stationarity -- the distribution of returns does not change over time. If your strategy performed differently in bull vs bear markets, bootstrap will blend those regimes together.

### Geometric Brownian Motion (GBM)

GBM generates paths using a parametric model: `S(t+dt) = S(t) * exp((mu - sigma^2/2)*dt + sigma*sqrt(dt)*Z)` where Z is standard normal.

```python
from analytics.monte_carlo import gbm_equity_paths

paths = gbm_equity_paths(
    mu=0.15,           # Annualized drift (estimated from returns)
    sigma=0.25,        # Annualized volatility (estimated from returns)
    dt=1.0 / 252,      # Time step as fraction of year (1/252 for daily)
    n_simulations=1000,
    path_length=252,
    initial_value=10000.0,
    seed=42,
)
```

**When to use:** GBM is useful for comparison and for understanding what a "normal" return distribution would imply. It is widely used in finance for option pricing and risk management.

**Limitations:** Assumes returns are log-normally distributed. Real financial returns typically have fat tails and negative skewness, so GBM tends to underestimate extreme losses.

### Comparing Methods

When bootstrap and GBM disagree, pay attention:

- If bootstrap shows higher tail risk than GBM, the strategy's actual returns have fatter tails than a normal distribution. Trust the bootstrap.
- If GBM shows worse outcomes, the strategy may have positive skewness (frequent small losses, rare large gains) that bootstrap faithfully reproduces but GBM smooths out.

## Running a Stress Test

The `run_stress_test()` function in `lib/analytics/stress_test.py` orchestrates both methods:

```python
from analytics.stress_test import run_stress_test, save_stress_test_results

# backtest_results must contain an 'equity_curve' key
# with a list of (timestamp, equity_value) tuples
results = run_stress_test(
    backtest_results=backtest_results,
    config={
        "n_simulations": 1000,
        "methods": ["bootstrap", "gbm"],
        "block_size": 1,
        "confidence_levels": [0.05, 0.25, 0.50, 0.75, 0.95],
        "ruin_threshold": 0.5,  # 50% of initial equity
    },
)
```

**Configuration options:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `n_simulations` | `1000` | Number of simulated paths per method |
| `methods` | `["bootstrap", "gbm"]` | Which methods to run |
| `block_size` | `1` | Block size for bootstrap (1 = simple) |
| `confidence_levels` | `[0.05, 0.25, 0.50, 0.75, 0.95]` | Percentile levels for confidence bands |
| `ruin_threshold` | `0.5` | Fraction of initial equity that defines ruin |

The function:
1. Extracts the equity curve and computes returns.
2. Runs bootstrap simulation (draws from actual returns).
3. Runs GBM simulation (estimates drift `mu` and volatility `sigma` from returns, annualized by factor of 252).
4. Computes `summary_report()` for each method.

The return value is a dictionary keyed by method name (`"bootstrap"`, `"gbm"`), each containing `"paths"` (the simulated equity arrays) and `"summary"` (aggregated statistics).

### Saving Results

```python
from pathlib import Path

result_dir = save_stress_test_results(
    results=results,
    base_dir=Path(".persistra"),
    strategy_name="sma_crossover",
)
# Saves to: .persistra/stress_tests/sma_crossover_{timestamp}/
#   bootstrap_paths.parquet
#   gbm_paths.parquet
#   statistics.json
```

## Interpreting Results

### Summary Report

The `summary_report()` function (called internally) produces a statistics dictionary for each method:

```json
{
    "method": "bootstrap",
    "n_simulations": 1000,
    "path_length": 365,
    "mean_return": 0.142,
    "median_return": 0.118,
    "std_return": 0.283,
    "mean_max_drawdown": 0.194,
    "median_max_drawdown": 0.172,
    "mean_sharpe": 0.87,
    "mean_final_value": 11420.0,
    "median_final_value": 11180.0,
    "var_95": -0.218,
    "cvar_95": -0.341,
    "probability_of_ruin_50pct": 0.023
}
```

### Confidence Intervals

Confidence intervals show the range of equity values at each time step across all simulations:

```python
from analytics.monte_carlo import confidence_intervals

ci = confidence_intervals(paths, levels=[0.05, 0.25, 0.50, 0.75, 0.95])
# ci["p5"]  — 5th percentile at each timestep (worst-case band)
# ci["p25"] — 25th percentile
# ci["p50"] — median path
# ci["p75"] — 75th percentile
# ci["p95"] — 95th percentile (best-case band)
```

The dashboard renders these as a fan chart. The area between p5 and p95 represents the 90% confidence band -- 90% of simulated paths fall within this range.

### VaR and CVaR

Value at Risk (VaR) and Conditional VaR (Expected Shortfall) are computed from terminal values:

```python
from analytics.monte_carlo import var_cvar_from_simulations

var_95, cvar_95 = var_cvar_from_simulations(paths, confidence=0.95)
```

- **VaR at 95%**: The return below which only 5% of simulated outcomes fall. If VaR is -0.20, there is a 5% chance of losing more than 20%.
- **CVaR at 95%** (Expected Shortfall): The average return in the worst 5% of outcomes. CVaR is always worse than VaR and captures tail severity. If CVaR is -0.35, the average loss in the worst 5% of scenarios is 35%.

### Probability of Ruin

```python
from analytics.monte_carlo import probability_of_ruin

p_ruin = probability_of_ruin(paths, ruin_threshold=5000.0)
```

This measures the fraction of simulated paths where equity drops below the threshold at any point during the simulation (not just the terminal value). A probability of ruin below 5% is generally considered acceptable for most strategies.

The summary report computes ruin at the 50% equity level by default (e.g., for a $10,000 account, ruin is triggered if equity drops below $5,000 at any point).

### Per-Path Statistics

```python
from analytics.monte_carlo import compute_path_statistics

stats = compute_path_statistics(paths)
# List of dicts, one per simulated path:
# [{"total_return": 0.15, "max_drawdown": 0.12, "sharpe": 1.2, "final_value": 11500}, ...]
```

Each path's Sharpe ratio is annualized using a factor of sqrt(252).

## Limitations

- **Bootstrap assumes stationarity**: The return distribution is constant over time. This breaks down during regime changes (e.g., a strategy that works in low-vol environments but fails in high-vol).
- **GBM assumes normality**: Log-returns are normally distributed. Real returns are fat-tailed and negatively skewed. GBM typically underestimates downside risk.
- **Neither captures regime changes**: If your strategy's returns depend on market regime (trending vs mean-reverting), neither method models the regime transition dynamics.
- **Past returns are not predictive**: Both methods resample or model based on historical returns. If future market conditions differ materially, all bets are off.

## Visualization

View stress test results in the web dashboard at `/stress`. The detail page renders fan charts showing confidence bands and simulation path statistics. See the [Dashboard Guide](dashboard.md) for details.
