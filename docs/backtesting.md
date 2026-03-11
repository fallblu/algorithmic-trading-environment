# Backtesting Guide

## Overview

Backtesting replays historical market data through a strategy using a simulated broker. No API keys or live connections are needed — everything runs locally against Parquet-stored OHLCV data. The system supports backtesting across multiple symbols simultaneously.

## Quick Start

```bash
# 1. Fetch historical data from Kraken (comma-separated symbols)
persistra process run data_ingestor -p symbols=BTC/USD,ETH/USD -p timeframe=1h -p backfill_days=365

# 2. Run the backtest
persistra process run sma_crossover -p symbols=BTC/USD,ETH/USD -p timeframe=1h

# 3. View results
persistra state get backtest.results
```

Or use the workflow (validates data first, then runs strategy, then prints analytics):

```bash
persistra state set backtest_symbols "BTC/USD,ETH/USD"
persistra workflow run backtest
```

## Step 1: Ingest Historical Data

The `data_ingestor` process fetches OHLCV bars from the Kraken public REST API and stores them as Parquet files in `.persistra/market_data/`.

```bash
persistra process run data_ingestor \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1h \
  -p backfill_days=365
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `symbols` | `BTC/USD` | Comma-separated trading pairs |
| `timeframe` | `1h` | Bar period |
| `backfill_days` | `365` | Days of history to fetch |
| `exchange` | `kraken` | Data source |

### Supported Symbols

| Symbol | Kraken Pair |
|--------|-------------|
| BTC/USD | XBTUSD |
| ETH/USD | ETHUSD |
| SOL/USD | SOLUSD |
| XRP/USD | XRPUSD |

Any Kraken pair works — unsupported symbols are passed through as-is (e.g., `DOGEUSD`).

### Supported Timeframes

`1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w`

### Incremental Updates

Running the ingestor again for the same symbols/timeframe only fetches bars newer than the last stored timestamp. No data is duplicated.

```bash
# First run: backfills 365 days for both symbols
persistra process run data_ingestor -p symbols=BTC/USD,ETH/USD -p timeframe=1h -p backfill_days=365

# Second run: only fetches new bars since last update
persistra process run data_ingestor -p symbols=BTC/USD,ETH/USD -p timeframe=1h
```

Check what data is available:

```bash
persistra state get data.BTC_USD_1h_bars      # number of bars stored
persistra state get data.ETH_USD_1h_bars
persistra state get data.last_update           # last fetch timestamp
```

## Step 2: Run a Backtest

The `sma_crossover` process runs the SMA crossover strategy against historical data using a simulated broker. It supports backtesting across multiple symbols simultaneously.

```bash
persistra process run sma_crossover \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1h \
  -p fast_period=10 \
  -p slow_period=30 \
  -p quantity=0.01 \
  -p initial_cash=10000
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `symbols` | `BTC/USD` | Comma-separated trading pairs (must have data ingested) |
| `timeframe` | `1h` | Bar period (must match ingested data) |
| `fast_period` | `10` | Fast SMA window (bars) |
| `slow_period` | `30` | Slow SMA window (bars) |
| `quantity` | `0.01` | Trade size per signal per symbol (base asset) |
| `initial_cash` | `10000` | Starting USD balance |
| `fee_rate` | `0.0026` | Taker fee rate (0.26% = Kraken default) |
| `slippage_pct` | `0.0001` | Slippage as fraction of price (0.01%) |
| `max_position_size` | `1.0` | Maximum position size per instrument (base asset) |
| `start` | *(earliest data)* | Backtest start date (ISO format) |
| `end` | *(now)* | Backtest end date (ISO format) |

### Strategy Logic

The SMA crossover strategy is long-only and trades each symbol independently:

1. **Buy signal**: For a given symbol, fast SMA crosses above slow SMA and no position is held. Submits a market buy order.
2. **Sell signal**: For a given symbol, fast SMA crosses below slow SMA and a position is held. Submits a market sell for the full position.
3. **Warmup**: The first `slow_period` bars per symbol are used to build up the SMA windows — no signals are generated.

With multiple symbols, the strategy computes independent SMA crossovers for each and can hold simultaneous positions.

### Multi-Symbol Backtest Engine

The backtest engine processes bars grouped by timestamp across all symbols:

1. **Load universe**: Reads bars for all symbols from the Parquet store
2. **Group by timestamp**: Bars at the same timestamp form a "bar group"
3. **Process bar group**: All bars are fed to the SimulatedBroker, which processes orders for each symbol and does a single bulk equity update
4. **Build panel**: Bars are appended to a `PricePanel`, which produces a MultiIndex `(timestamp, symbol)` DataFrame
5. **Call strategy**: `strategy.on_bar(panel)` receives the full lookback window for all symbols and returns orders for any symbol
6. **Risk check**: Each order is validated against per-instrument position limits
7. **Record equity**: A single equity snapshot is taken per timestamp

### PricePanel

The `PricePanel` provides the strategy with a rolling window of historical bars as a pandas MultiIndex DataFrame:

- **Index**: `(timestamp, symbol)` — sorted by timestamp, then symbol
- **Columns**: `open`, `high`, `low`, `close`, `volume`, `trades`, `vwap`
- **Inner-join**: Only timestamps present for ALL symbols appear in the window, so strategies always see aligned data
- **Lookback**: Configurable depth (defaults to `slow_period`)
- **Decimal→float**: Prices are converted from `Decimal` to `float64` at ingestion for fast numpy/pandas operations

Strategies extract per-symbol data with:
```python
sym_data = panel.xs("BTC/USD", level="symbol")
closes = sym_data["close"].values
```

### Simulated Broker

Fill simulation:
- **Market orders**: Fill at bar open price ± slippage
- **Limit orders**: Fill if bar low ≤ limit price (buy) or bar high ≥ limit price (sell)
- **Stop orders**: Trigger when bar high ≥ stop price (buy) or bar low ≤ stop price (sell)
- **Fees**: `quantity × price × fee_rate`, deducted from USD balance
- **Slippage**: `price × slippage_pct`, added to buy price or subtracted from sell price

For multi-symbol bar groups, `process_bars()` processes all symbols then does a single equity update.

## Step 3: View Results

```bash
# Full metrics
persistra state get backtest.results

# Strategy parameters used
persistra state get strategy.sma_crossover.params

# Universe traded
persistra state get backtest.universe

# Equity curve (Parquet file path)
persistra state get backtest.equity_curve_path

# Fills (Parquet file path)
persistra state get backtest.fills_path
```

### Performance Metrics

| Metric | Description |
|--------|-------------|
| `total_return` | Total percentage return |
| `annualized_return` | Compound annual return |
| `sharpe_ratio` | Risk-adjusted return (annualized) |
| `sortino_ratio` | Downside risk-adjusted return |
| `max_drawdown` | Largest peak-to-trough decline |
| `max_drawdown_duration` | Time from peak to trough |
| `calmar_ratio` | Annualized return / max drawdown |
| `num_trades` | Number of completed round-trip trades (all symbols) |
| `win_rate` | Fraction of profitable trades |
| `profit_factor` | Gross profit / gross loss |
| `avg_win` | Average profit per winning trade (USD) |
| `avg_loss` | Average loss per losing trade (USD) |
| `total_fees` | Total fees paid (USD) |
| `initial_equity` | Starting capital |
| `final_equity` | Ending capital |

Annualized metrics assume hourly bars (8,760 periods/year). Adjust mentally for other timeframes, or modify `periods_per_year` in the analytics code.

### Equity Curve & Fills (Parquet)

Equity curve and fills are stored as Parquet files for efficient analysis:

```bash
# Get the file paths
persistra state get backtest.equity_curve_path
persistra state get backtest.fills_path
```

Load in Python:
```python
import pandas as pd
eq = pd.read_parquet(".persistra/dataframes/backtest_equity_curve.parquet")
fills = pd.read_parquet(".persistra/dataframes/backtest_fills.parquet")

# Per-symbol fill analysis
fills.groupby("symbol")["quantity"].sum()
```

## Using the Backtest Workflow

The `backtest` workflow chains three steps:

```
load_data → run_strategy → analyze
```

```bash
persistra workflow run backtest
```

1. **load_data** — Validates that market data exists for ALL symbols in the configured universe
2. **run_strategy** — Runs the `sma_crossover` process as a job
3. **analyze** — Reads `backtest.results` from state and logs a performance summary

The workflow reads configuration from state:

```bash
# Override defaults before running the workflow (optional)
persistra state set backtest_symbols "BTC/USD,ETH/USD,SOL/USD"
persistra state set backtest_timeframe "4h"
persistra state set backtest_exchange "kraken"
```

## Example: Multi-Symbol Backtest

```bash
# Ingest data for 3 symbols
persistra process run data_ingestor -p symbols=BTC/USD,ETH/USD,SOL/USD -p timeframe=1h

# Run backtest across all 3
persistra process run sma_crossover \
  -p symbols=BTC/USD,ETH/USD,SOL/USD \
  -p timeframe=1h \
  -p fast_period=10 \
  -p slow_period=30 \
  -p quantity=0.1 \
  -p initial_cash=100000

# View aggregate results
persistra state get backtest.results
```

## Example: Parameter Sweep

```bash
# Fast/Slow: 5/20
persistra process run sma_crossover -p symbols=BTC/USD,ETH/USD -p fast_period=5 -p slow_period=20
persistra state get backtest.results

# Fast/Slow: 10/50
persistra process run sma_crossover -p symbols=BTC/USD,ETH/USD -p fast_period=10 -p slow_period=50
persistra state get backtest.results
```

Each run overwrites `backtest.results`, `backtest.equity_curve_path`, and `backtest.fills_path` in state.

## Troubleshooting

**"No bars found"** — Data hasn't been ingested for one or more symbols. Run the data ingestor first for all required symbols.

**Backtest returns 0 trades** — The SMA windows may be too wide for the available data, or the market was flat during the period. Try shorter SMA periods or a longer date range.

**"No market data available for X"** (workflow) — One or more symbols in the universe don't have ingested data. Run `persistra process run data_ingestor -p symbols=X`.

**Process shows "stopped" immediately** — Check logs for errors:

```bash
persistra process logs sma_crossover-1
```

## Data Storage

Historical data is stored as Parquet files:

```
.persistra/market_data/
  kraken/
    BTC_USD/
      1h.parquet
      1m.parquet
    ETH_USD/
      1h.parquet
    SOL_USD/
      1h.parquet
```

Backtest results are stored as Parquet files:

```
.persistra/dataframes/
  backtest_equity_curve.parquet    # timestamp, equity
  backtest_fills.parquet           # timestamp, symbol, side, quantity, price, fee, order_id
```
