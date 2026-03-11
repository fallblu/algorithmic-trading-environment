# Batch Backtesting Guide

## Overview

Batch backtesting runs a strategy across many parameter combinations in parallel, producing a structured set of results that can be ranked, compared, and visualized as heatmaps. This is the primary tool for parameter optimization and sensitivity analysis.

## Quick Start

```bash
# Run a 4x4 grid sweep of SMA crossover parameters
persistra process run batch_backtest \
  -p strategy=sma_crossover \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1h \
  -p grid='{"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}'
```

Or via workflow (validates data availability first):

```bash
persistra state set batch_strategy "sma_crossover"
persistra state set batch_symbols "BTC/USD,ETH/USD"
persistra state set batch_timeframe "1h"
persistra state set batch_grid '{"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}'
persistra workflow run batch_backtest
```

## ParameterGrid

`ParameterGrid` defines the sweep space. It takes a dict mapping parameter names to lists of values and generates all combinations as a Cartesian product.

```python
from execution.batch import ParameterGrid

grid = ParameterGrid(params={
    "fast_period": [5, 10, 15, 20, 25],
    "slow_period": [20, 30, 40, 50, 60],
})

# Total combinations: 5 x 5 = 25
print(grid.total)  # 25

# Each combination is a dict
combos = grid.combinations()
# [{"fast_period": 5, "slow_period": 20}, {"fast_period": 5, "slow_period": 30}, ...]
```

When passed as a command-line argument, the grid is specified as a JSON string:

```bash
-p grid='{"fast_period": [5, 10, 15, 20, 25], "slow_period": [20, 30, 40, 50, 60]}'
```

### Grid Size Considerations

Each combination runs a full backtest. A 5x5 grid = 25 backtests, a 10x10 grid = 100 backtests. Keep grid sizes reasonable, especially with long date ranges or multiple symbols. Start with coarse grids and refine around promising regions.

## BatchBacktest

`BatchBacktest` executes a parameter grid using Python's `multiprocessing.Pool`. Each parameter combination runs as an independent backtest in a separate process.

```python
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from data.universe import Universe
from execution.batch import BatchBacktest, ParameterGrid
from strategy.registry import get_strategy

strategy_class = get_strategy("sma_crossover")
universe = Universe.from_symbols(["BTC/USD", "ETH/USD"], "1h")

grid = ParameterGrid(params={
    "fast_period": [5, 10, 15, 20],
    "slow_period": [20, 30, 40, 50],
})

batch = BatchBacktest(
    strategy_class=strategy_class,
    universe=universe,
    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end=datetime(2024, 12, 31, tzinfo=timezone.utc),
    base_params={"symbols": ["BTC/USD", "ETH/USD"], "quantity": "0.01"},
    grid=grid,
    initial_cash=Decimal("10000"),
    n_workers=4,                                  # None = auto (cpu_count)
    data_dir=Path(".persistra/market_data"),
)

results = batch.run()  # Returns BatchResults
```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `strategy_class` | `type[Strategy]` | required | Strategy class to instantiate per run |
| `universe` | `Universe` | required | Symbol universe and timeframe |
| `start` | `datetime \| None` | `None` | Backtest start date |
| `end` | `datetime \| None` | `None` | Backtest end date |
| `base_params` | `dict` | `{}` | Fixed params applied to every run |
| `grid` | `ParameterGrid` | empty | Parameter sweep specification |
| `initial_cash` | `Decimal` | `10000` | Starting equity |
| `n_workers` | `int \| None` | `None` | Worker processes (`None` = auto, `1` = sequential/debug) |
| `data_dir` | `Path` | `.persistra/market_data` | Market data directory |

### Parallel Execution

- Setting `n_workers=None` (default) uses `multiprocessing.cpu_count()`.
- Setting `n_workers=1` runs sequentially in the main process, which is useful for debugging.
- Each worker re-imports the strategy module, so strategies must be importable by module path.
- Memory usage scales with `n_workers` since each worker loads its own copy of the data.

## BatchResults

`BatchResults` aggregates all run outcomes and provides analysis methods.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `runs` | `list[dict]` | All run results (successful and failed) |
| `grid` | `ParameterGrid` | The parameter grid used |
| `elapsed_seconds` | `float` | Total wall-clock time |
| `n_successful` | `int` | Count of successful runs |
| `n_failed` | `int` | Count of failed runs |

### as_dataframe()

Converts successful runs into a pandas DataFrame with parameter columns and metric columns merged together.

```python
df = results.as_dataframe()
# Columns: fast_period, slow_period, sharpe_ratio, total_return, max_drawdown, ...
print(df.sort_values("sharpe_ratio", ascending=False).head())
```

### best_by(metric, ascending=False)

Returns the single best run dict for a given metric.

```python
best = results.best_by("sharpe_ratio")
print(best["params"])    # {"fast_period": 10, "slow_period": 40}
print(best["metrics"])   # {"sharpe_ratio": 1.82, "total_return": 0.34, ...}

# For metrics where lower is better:
lowest_dd = results.best_by("max_drawdown", ascending=True)
```

### heatmap_data(param_x, param_y, metric)

Creates a pivot table for 2D heatmap visualization. The result is a DataFrame with `param_y` as the index and `param_x` as columns, with `metric` values in the cells.

```python
heatmap = results.heatmap_data("fast_period", "slow_period", "sharpe_ratio")
#              5      10     15     20
# 20        0.45   0.82   0.91   0.67
# 30        0.52   1.23   1.45   0.98
# 40        0.38   1.12   1.82   1.15
# 50        0.21   0.89   1.33   0.92
```

### sensitivity(param, metric)

One-dimensional sensitivity analysis: averages the metric across all other parameters for each value of `param`.

```python
sens = results.sensitivity("fast_period", "sharpe_ratio")
# fast_period  sharpe_ratio
# 5            0.39
# 10           1.02
# 15           1.38
# 20           0.93
```

### save(path) and load(path)

Persist results to disk and reload them later.

```python
from pathlib import Path

# Save
results.save(Path(".persistra/batch_results/sma_crossover"))
# Creates: runs.parquet, runs.json, metadata.json

# Load
from analytics.batch_results import BatchResults
loaded = BatchResults.load(Path(".persistra/batch_results/sma_crossover"))
```

## Process Entry Point

The `processes/batch_backtest.py` module exposes a Persistra job process.

```bash
persistra process run batch_backtest \
  -p strategy=sma_crossover \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1h \
  -p grid='{"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}' \
  -p initial_cash=10000 \
  -p n_workers=4 \
  -p start=2024-01-01T00:00:00+00:00 \
  -p end=2024-12-31T00:00:00+00:00
```

### Process Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `strategy` | `sma_crossover` | Registered strategy name |
| `symbols` | `BTC/USD` | Comma-separated symbol list |
| `timeframe` | `1h` | Bar timeframe |
| `grid` | `{"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}` | JSON parameter grid |
| `initial_cash` | `10000` | Starting equity |
| `n_workers` | `0` | Worker processes (0 = auto) |
| `start` | empty | Start date (ISO format) |
| `end` | empty | End date (ISO format) |

Results are saved to `.persistra/batch_results/{strategy}/` and the best parameters are stored in state under `batch.best_params` and `batch.best_metrics`.

## Workflow Entry Point

The `workflows/batch_backtest.py` module defines a two-step DAG:

1. **validate_data** -- checks that market data exists for all requested symbols, timeframe, and exchange. Raises an error if data is missing (run `data_ingestor` first).
2. **run_batch** -- executes the batch backtest and saves results.

Configuration is read from Persistra state:

| State Key | Default | Description |
|-----------|---------|-------------|
| `batch_strategy` | `sma_crossover` | Registered strategy name |
| `batch_symbols` | `BTC/USD` | Comma-separated symbols |
| `batch_timeframe` | `1h` | Bar timeframe |
| `batch_grid` | `{"fast_period": [5, 10, 15], "slow_period": [20, 30, 50]}` | JSON parameter grid |
| `batch_start` | empty | Start date (ISO) |
| `batch_end` | empty | End date (ISO) |
| `batch_workers` | `0` | Worker count (0 = auto) |
| `batch_initial_cash` | `10000` | Starting equity |
| `batch_exchange` | `kraken` | Exchange for data validation |

## Interpreting Results

### What Good Results Look Like

- **Sharpe ratio > 1.0**: reasonable risk-adjusted returns. Above 2.0 is strong.
- **Total return**: positive and meaningful relative to the time period.
- **Max drawdown**: ideally under 20%. Above 40% is a red flag.
- **Consistency across neighbors**: if a parameter combination has a high Sharpe but its neighbors in the grid do not, this is likely overfitting to noise.

### Overfitting Warnings

Parameter optimization inherently risks overfitting. Keep these guidelines in mind:

- **Smooth heatmaps**: the best parameters should be surrounded by reasonably good neighbors. Isolated spikes suggest noise.
- **Out-of-sample validation**: always reserve a portion of your data that was not part of the sweep. Run the best parameters on that holdout period.
- **Fewer parameters is better**: the more parameters you sweep, the higher the risk of finding spurious combinations.
- **Reasonable parameter values**: best parameters should make financial sense (e.g., a "fast" SMA should be faster than the "slow" SMA).

### Visualization

Batch results are viewable in the web dashboard under the "Batch Results" page, which shows heatmaps and sensitivity plots. See the [Dashboard Guide](dashboard.md) for details.

## Example: SMA Fast/Slow Period Sweep

This example sweeps SMA crossover fast and slow periods across two crypto pairs.

```bash
# 1. Ensure data is available
persistra process run data_ingestor \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1h \
  -p backfill_days=365

# 2. Run the sweep: 5 fast x 5 slow = 25 backtests
persistra process run batch_backtest \
  -p strategy=sma_crossover \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1h \
  -p grid='{"fast_period": [5, 10, 15, 20, 25], "slow_period": [20, 30, 40, 50, 60]}' \
  -p initial_cash=10000

# 3. Check the best result
persistra state get batch.best_params
persistra state get batch.best_metrics

# 4. View heatmap in dashboard
persistra process start dashboard
# Open http://localhost:8050 -> Batch Results
```

Or programmatically:

```python
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from data.universe import Universe
from execution.batch import BatchBacktest, ParameterGrid
from strategy.registry import get_strategy
import strategy.sma_crossover  # ensure registered

strategy_class = get_strategy("sma_crossover")
universe = Universe.from_symbols(["BTC/USD", "ETH/USD"], "1h")

grid = ParameterGrid(params={
    "fast_period": [5, 10, 15, 20, 25],
    "slow_period": [20, 30, 40, 50, 60],
})

batch = BatchBacktest(
    strategy_class=strategy_class,
    universe=universe,
    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end=datetime(2024, 12, 31, tzinfo=timezone.utc),
    base_params={"symbols": ["BTC/USD", "ETH/USD"], "quantity": "0.01"},
    grid=grid,
    initial_cash=Decimal("10000"),
    n_workers=4,
    data_dir=Path(".persistra/market_data"),
)

results = batch.run()

# Analyze
print(f"Completed: {results.n_successful}/{len(results.runs)} in {results.elapsed_seconds:.1f}s")

best = results.best_by("sharpe_ratio")
print(f"Best params: {best['params']}")
print(f"Best Sharpe: {best['metrics']['sharpe_ratio']:.4f}")

# Heatmap
heatmap = results.heatmap_data("fast_period", "slow_period", "sharpe_ratio")
print(heatmap)

# Save for later / dashboard viewing
results.save(Path(".persistra/batch_results/sma_crossover"))
```
