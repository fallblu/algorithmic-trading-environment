# Data Management

This guide covers how market data is ingested, stored, queried, and aggregated in the trader system.

## Overview

The system uses three storage layers, all based on Apache Parquet:

| Store | Class | Purpose | Layout |
|-------|-------|---------|--------|
| MarketDataStore | `lib/data/store.py` | OHLCV bar data | `{base_dir}/{exchange}/{symbol}/{timeframe}.parquet` |
| TickStore | `lib/data/tick_store.py` | Raw tick data | `{base_dir}/{exchange}/{pair}/YYYY-MM-DD.parquet` |
| ResultStore | `lib/data/result_store.py` | Backtest/analysis results | `{base_dir}/{result_type}/{uuid}/` |

The default base directory is `.persistra/market_data/` for bars, `.persistra/tick_data/` for ticks, and `.persistra/results/` for results.

## MarketDataStore

`MarketDataStore` handles OHLCV bar data in Parquet format. It is the primary data layer used by backtesting.

### File Layout

```
.persistra/market_data/
├── kraken/
│   ├── BTC_USD/
│   │   ├── 1h.parquet
│   │   ├── 4h.parquet
│   │   └── 1d.parquet
│   └── ETH_USD/
│       └── 1h.parquet
├── kraken_futures/
│   └── BTC-PERP/
│       └── 1h.parquet
└── oanda/
    └── EUR_USD/
        └── 1h.parquet
```

Symbols with `/` in the name are stored with `_` substitution (e.g., `BTC/USD` becomes `BTC_USD`).

### Parquet Schema

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | `timestamp[us]` | Bar timestamp (UTC, microsecond precision) |
| `open` | `float64` | Opening price |
| `high` | `float64` | High price |
| `low` | `float64` | Low price |
| `close` | `float64` | Closing price |
| `volume` | `float64` | Trade volume |
| `trades` | `int64` | Number of trades in the bar |
| `vwap` | `float64` | Volume-weighted average price |

### Writing Bars

```python
from pathlib import Path
from data.store import MarketDataStore

store = MarketDataStore(Path(".persistra/market_data"))
store.write_bars(bars, exchange="kraken", timeframe="1h")
```

`write_bars()` handles deduplication automatically:
- If the Parquet file already exists, new bars are merged with existing data
- Duplicates (same timestamp) are resolved by keeping the **last** value
- Bars are sorted by timestamp after merge

### Reading Bars

```python
from datetime import datetime, timezone

bars = store.read_bars(
    exchange="kraken",
    symbol="BTC/USD",
    timeframe="1h",
    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end=datetime(2024, 6, 1, tzinfo=timezone.utc),
)
# Returns: list[Bar] — sorted by timestamp
```

Each `Bar` object has `Decimal` fields for `open`, `high`, `low`, `close`, `volume`, and `vwap` (converted from the `float64` Parquet columns via string intermediary to preserve precision).

### Checking Data Availability

```python
# Check if any data exists
has_it = store.has_data("kraken", "BTC/USD", "1h")  # bool

# Get the date range of stored data
date_range = store.get_date_range("kraken", "BTC/USD", "1h")
if date_range:
    start, end = date_range
    print(f"Data from {start} to {end}")
```

## TickStore

`TickStore` handles raw tick-level data, stored in daily Parquet files. This is primarily used for OANDA forex streaming data.

### File Layout

```
.persistra/tick_data/
└── oanda/
    └── EUR_USD/
        ├── 2024-01-15.parquet
        ├── 2024-01-16.parquet
        └── 2024-01-17.parquet
```

### Parquet Schema

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | `timestamp[us]` | Tick timestamp (UTC) |
| `bid` | `float64` | Bid price |
| `ask` | `float64` | Ask price |
| `mid` | `float64` | Mid price `(bid + ask) / 2` |
| `spread` | `float64` | Spread `ask - bid` |
| `volume` | `float64` | Tick volume |

### Writing Ticks

```python
from data.tick_store import TickStore

tick_store = TickStore(Path(".persistra/tick_data"))
tick_store.write_ticks(ticks_df, exchange="oanda", pair="EUR/USD")
```

The `write_ticks()` method automatically routes ticks to daily files based on the timestamp. Like `MarketDataStore`, it merges with existing data and deduplicates on timestamp.

### Reading Ticks

```python
ticks_df = tick_store.read_ticks(
    exchange="oanda",
    pair="EUR/USD",
    start=datetime(2024, 1, 15, tzinfo=timezone.utc),
    end=datetime(2024, 1, 17, tzinfo=timezone.utc),
)
# Returns: pd.DataFrame with columns [timestamp, bid, ask, mid, spread, volume]
```

### Aggregating Ticks to Bars

Convert tick data into OHLCV bars at any supported timeframe:

```python
bars_df = tick_store.aggregate_to_bars(
    exchange="oanda",
    pair="EUR/USD",
    timeframe="5m",  # or 1m, 15m, 30m, 1h, 4h, 1d
)
# Returns: pd.DataFrame with columns [timestamp, open, high, low, close, volume]
```

Supported timeframe strings:

| Input | Resampling frequency |
|-------|---------------------|
| `1m` | 1 minute |
| `5m` | 5 minutes |
| `15m` | 15 minutes |
| `30m` | 30 minutes |
| `1h` | 1 hour |
| `4h` | 4 hours |
| `1d` | 1 day |

Aggregation uses the `mid` price for OHLC and sums `volume`.

## ResultStore

`ResultStore` provides UUID-indexed storage for backtest, batch, stress test, and analysis results. It combines JSON metadata with Parquet DataFrames.

### File Layout

```
.persistra/results/
├── index.json                          # Global result index
├── backtest/
│   └── a1b2c3d4-e5f6-.../
│       ├── metadata.json               # Strategy, params, metrics
│       └── equity_curve.parquet        # Heavy data
├── batch/
│   └── f7g8h9i0-.../
│       ├── metadata.json
│       └── results.parquet
└── stress_test/
    └── j1k2l3m4-.../
        ├── metadata.json
        └── simulations.parquet
```

### Saving Results

```python
from data.result_store import ResultStore
import pandas as pd

store = ResultStore(Path(".persistra/results"))

result_id = store.save(
    result_type="backtest",
    metadata={
        "strategy": "sma_crossover",
        "universe": "BTC/USD",
        "params": {"fast_period": 10, "slow_period": 30},
        "metrics": {"sharpe_ratio": 1.25, "total_return": 0.15},
    },
    dataframes={
        "equity_curve": equity_df,
        "fills": fills_df,
    },
)
# Returns: UUID string like "a1b2c3d4-e5f6-..."
```

### Querying Results

```python
# List all backtest results (newest first)
results = store.list_results(result_type="backtest")

# Filter by strategy
results = store.list_results(result_type="backtest", strategy="sma_crossover")

# Load a specific result
meta = store.load("a1b2c3d4-e5f6-...")  # Returns metadata dict

# Load a DataFrame from a result
equity_df = store.load_dataframe("a1b2c3d4-e5f6-...", "equity_curve")

# Delete a result
store.delete("a1b2c3d4-e5f6-...")
```

The `index.json` file provides fast listing without reading individual metadata files.

## Data Ingestor Process

The `data_ingestor` process (`processes/data_ingestor.py`) is the primary way to fetch and store market data.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbols` | `str` | `"BTC/USD"` | Comma-separated symbol list |
| `timeframe` | `str` | `"1h"` | Bar timeframe |
| `backfill_days` | `int` | `365` | Number of days to backfill on first run |
| `exchange` | `str` | `"kraken"` | Exchange name: `kraken`, `kraken_futures`, or `oanda` |

### Usage

```bash
# Kraken spot
persistra process start data_ingestor \
  -p symbols="BTC/USD,ETH/USD,SOL/USD" \
  -p timeframe=1h \
  -p backfill_days=365 \
  -p exchange=kraken

# Kraken futures
persistra process start data_ingestor \
  -p symbols="BTC-PERP,ETH-PERP" \
  -p timeframe=1h \
  -p exchange=kraken_futures

# OANDA forex
persistra process start data_ingestor \
  -p symbols="EUR/USD,GBP/USD,USD/JPY" \
  -p timeframe=1h \
  -p exchange=oanda
```

### Backfill vs Incremental Updates

The ingestor handles both modes automatically:

1. **First run (backfill)**: No existing data found. Fetches `backfill_days` worth of bars from `now - backfill_days` to `now`.

2. **Subsequent runs (incremental)**: Detects existing data via `store.get_date_range()`. Only fetches bars from the last stored timestamp to now.

This means you can run the ingestor repeatedly to keep data up to date without re-downloading everything:

```bash
# First run: downloads 365 days
persistra process start data_ingestor -p symbols=BTC/USD -p backfill_days=365

# Later: only downloads new bars since last run
persistra process start data_ingestor -p symbols=BTC/USD
```

### Exchange-Specific Backends

| Exchange | Backend module | Function |
|----------|---------------|----------|
| `kraken` | `data.kraken_api` | `backfill_ohlcv()` |
| `kraken_futures` | `data.kraken_futures_api` | `backfill_ohlcv_futures()` |
| `oanda` | `data.oanda_api` | `backfill_candles()` |

### State Tracking

After ingestion, the process records state:

```python
ns = env.state.ns("data")
ns.set("last_update", "2024-06-15T12:00:00+00:00")
ns.set("BTC_USD_1h_bars", 8760)  # number of bars stored
```

Check the last update time:

```bash
persistra state get data.last_update
```

## Data Quality

### Deduplication

Both `MarketDataStore` and `TickStore` automatically deduplicate on timestamp when merging new data with existing files. The `keep="last"` policy ensures that corrected data overwrites stale values.

### Timestamp Handling

All timestamps are stored and processed in UTC. When reading bars, the store localizes timestamps to UTC if they lack timezone info:

```python
if start_ts.tzinfo is None:
    start_ts = start_ts.tz_localize("UTC")
```

### Gap Detection

Use `get_date_range()` to identify the time span of available data. Gaps within the data (e.g., exchange downtime, forex weekends) are not explicitly tracked but can be detected by checking for missing timestamps at the expected timeframe interval.

## Programmatic Access

### Using MarketDataStore Directly

```python
from pathlib import Path
from data.store import MarketDataStore

store = MarketDataStore(Path(".persistra/market_data"))

# Check what data is available
if store.has_data("kraken", "BTC/USD", "1h"):
    start, end = store.get_date_range("kraken", "BTC/USD", "1h")
    print(f"BTC/USD 1h: {start} to {end}")

# Read all bars
all_bars = store.read_bars("kraken", "BTC/USD", "1h")

# Read a date range
from datetime import datetime, timezone
bars = store.read_bars(
    "kraken", "BTC/USD", "1h",
    start=datetime(2024, 6, 1, tzinfo=timezone.utc),
    end=datetime(2024, 7, 1, tzinfo=timezone.utc),
)

# Convert to DataFrame for analysis
import pandas as pd
df = pd.DataFrame([{
    "timestamp": b.timestamp,
    "open": float(b.open),
    "high": float(b.high),
    "low": float(b.low),
    "close": float(b.close),
    "volume": float(b.volume),
} for b in bars])
```

### Using the Exchange Abstraction

For simpler one-off data fetching without storage:

```python
from data.exchange import get_exchange

exchange = get_exchange("kraken")
bars = exchange.fetch_ohlcv("ETH/USD", "1h", start=start_dt, end=end_dt)
```

## Further Reading

- [Getting Started](getting-started.md) — Quick start with data ingestion
- [Architecture](architecture.md) — How DataFeed, MarketDataStore, and PricePanel fit together
- [Configuration Reference](configuration-reference.md) — Exchange credentials and defaults
