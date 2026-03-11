# Backtesting Guide

## Overview

Backtesting replays historical market data through a strategy using a simulated broker. No API keys or live connections are needed — everything runs locally against Parquet-stored OHLCV data.

## Quick Start

```bash
# 1. Fetch historical data from Kraken
persistra process start data_ingestor -p symbol=BTC/USD -p timeframe=1h -p backfill_days=365

# 2. Run the backtest
persistra process start sma_crossover -p symbol=BTC/USD -p timeframe=1h

# 3. View results
persistra state get backtest.results
```

Or use the workflow (validates data first, then runs strategy, then prints analytics):

```bash
persistra workflow run backtest
```

## Step 1: Ingest Historical Data

The `data_ingestor` process fetches OHLCV bars from the Kraken public REST API and stores them as Parquet files in `.persistra/market_data/`.

```bash
persistra process start data_ingestor \
  -p symbol=BTC/USD \
  -p timeframe=1h \
  -p backfill_days=365
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `symbol` | `BTC/USD` | Trading pair |
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

Running the ingestor again for the same symbol/timeframe only fetches bars newer than the last stored timestamp. No data is duplicated.

```bash
# First run: backfills 365 days
persistra process start data_ingestor -p symbol=BTC/USD -p timeframe=1h -p backfill_days=365

# Second run: only fetches new bars since last update
persistra process start data_ingestor -p symbol=BTC/USD -p timeframe=1h
```

Check what data is available:

```bash
persistra state get data.BTC_USD_1h_bars      # number of bars stored
persistra state get data.last_update           # last fetch timestamp
```

## Step 2: Run a Backtest

The `sma_crossover` process runs the SMA crossover strategy against historical data using a simulated broker.

```bash
persistra process start sma_crossover \
  -p symbol=BTC/USD \
  -p timeframe=1h \
  -p fast_period=10 \
  -p slow_period=30 \
  -p quantity=0.01 \
  -p initial_cash=10000
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `symbol` | `BTC/USD` | Trading pair (must have data ingested) |
| `timeframe` | `1h` | Bar period (must match ingested data) |
| `fast_period` | `10` | Fast SMA window (bars) |
| `slow_period` | `30` | Slow SMA window (bars) |
| `quantity` | `0.01` | Trade size per signal (in base asset, e.g., BTC) |
| `initial_cash` | `10000` | Starting USD balance |
| `fee_rate` | `0.0026` | Taker fee rate (0.26% = Kraken default) |
| `slippage_pct` | `0.0001` | Slippage as fraction of price (0.01%) |
| `max_position_size` | `1.0` | Maximum position size (base asset) |
| `start` | *(earliest data)* | Backtest start date (ISO format, e.g., `2025-01-01T00:00:00+00:00`) |
| `end` | *(now)* | Backtest end date (ISO format) |

### Strategy Logic

The SMA crossover strategy is long-only:

1. **Buy signal**: Fast SMA crosses above slow SMA, and no position is held. Submits a market buy order.
2. **Sell signal**: Fast SMA crosses below slow SMA, and a position is held. Submits a market sell for the full position.
3. **Warmup**: The first `slow_period` bars are used to build up the SMA windows — no signals are generated.

### Simulated Broker

The backtest engine processes each bar in sequence:

1. **Fill pending orders** against the current bar (market orders fill at bar open + slippage)
2. **Call strategy** with the bar to generate new orders
3. **Risk check** each order (max position size)
4. **Submit** approved orders (they fill on the next bar)
5. **Record equity** snapshot

Fill simulation:
- **Market orders**: Fill at bar open price ± slippage
- **Limit orders**: Fill if bar low ≤ limit price (buy) or bar high ≥ limit price (sell)
- **Stop orders**: Trigger when bar high ≥ stop price (buy) or bar low ≤ stop price (sell)
- **Fees**: `quantity × price × fee_rate`, deducted from USD balance
- **Slippage**: `price × slippage_pct`, added to buy price or subtracted from sell price

## Step 3: View Results

```bash
# Full metrics
persistra state get backtest.results

# Strategy parameters used
persistra state get strategy.sma_crossover.params
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
| `num_trades` | Number of completed round-trip trades |
| `win_rate` | Fraction of profitable trades |
| `profit_factor` | Gross profit / gross loss |
| `avg_win` | Average profit per winning trade (USD) |
| `avg_loss` | Average loss per losing trade (USD) |
| `total_fees` | Total fees paid (USD) |
| `initial_equity` | Starting capital |
| `final_equity` | Ending capital |

Annualized metrics assume hourly bars (8,760 periods/year). Adjust mentally for other timeframes, or modify `periods_per_year` in the analytics code.

### Equity Curve

The full equity curve is stored as a list of `{timestamp, equity}` entries:

```bash
persistra state get backtest.equity_curve
```

## Using the Backtest Workflow

The `backtest` workflow chains three steps:

```
load_data → run_strategy → analyze
```

```bash
persistra workflow run backtest
```

1. **load_data** — Validates that market data exists for the configured symbol/timeframe
2. **run_strategy** — Runs the `sma_crossover` process as a job
3. **analyze** — Reads `backtest.results` from state and logs a performance summary

The workflow reads configuration from state:

```bash
# Override defaults before running the workflow (optional)
persistra state set backtest_symbol "ETH/USD"
persistra state set backtest_timeframe "4h"
persistra state set backtest_exchange "kraken"
```

## Example: Parameter Sweep

Run multiple backtests with different parameters:

```bash
# Fast/Slow: 5/20
persistra process start sma_crossover -p fast_period=5 -p slow_period=20
persistra state get backtest.results

# Fast/Slow: 10/50
persistra process start sma_crossover -p fast_period=10 -p slow_period=50
persistra state get backtest.results

# Different quantity
persistra process start sma_crossover -p quantity=0.1 -p initial_cash=100000
persistra state get backtest.results
```

Each run overwrites `backtest.results` and `strategy.sma_crossover.metrics` in state. To preserve results across runs, read them before starting the next backtest.

## Troubleshooting

**"No bars found"** — Data hasn't been ingested for the requested symbol/timeframe. Run the data ingestor first.

**Backtest returns 0 trades** — The SMA windows may be too wide for the available data, or the market was flat during the period. Try shorter SMA periods or a longer date range.

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
```

Each file contains columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`, `trades`, `vwap`.
