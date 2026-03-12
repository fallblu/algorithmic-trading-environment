# Architecture Overview

This document describes the high-level architecture of the Trader platform — a Python 3.12 quantitative trading system supporting backtesting, paper trading, and live trading across Kraken (crypto) and OANDA (forex).

## System Diagram

```
                          +-----------------+
                          |   Strategies    |
                          | (SMA, Momentum, |
                          |  Pairs, etc.)   |
                          +--------+--------+
                                   |
                            on_bar(panel)
                                   |
                          +--------v--------+
                          | ExecutionContext |
                          |  (ABC)          |
                          +--------+--------+
                          /        |        \
                 +-------+    +----+----+   +-------+
                 |Backtest|   | Paper   |   | Live  |
                 |Context |   | Context |   |Context|
                 +---+----+   +----+----+   +---+---+
                     |             |            |
              +------+------+     +------+-----+
              |             |            |
        +-----v---+  +------v--+  +------v------+
        |Historical|  |Live Feed|  |Live Broker  |
        |  Feed    |  |(WS/API) |  |(Kraken/OANDA)|
        +---------+  +---------+  +-------------+
              |             |
        +-----v-------------v-----+
        |   SimulatedBroker       |
        |   + PositionManager     |
        +-------------------------+
```

## Core Modules

### Execution Layer (`lib/execution/`)

The execution layer defines how strategies interact with the trading system. Every strategy receives an `ExecutionContext` — the same strategy code runs identically in backtest, paper, and live modes.

| Module | Purpose |
|--------|---------|
| `context.py` | `ExecutionContext` ABC — provides `get_broker()`, `get_universe()`, `get_risk_manager()`, `current_time()` |
| `backtest.py` | `BacktestContext` — replays historical bars through `HistoricalFeed` + `SimulatedBroker` |
| `realtime.py` | `RealtimeContext` — shared base for paper/live with `warmup()`, `run_once()`, `subscribe_all()` |
| `paper.py` | `PaperContext` — live data feed + simulated execution |
| `live.py` | `LiveContext` — live data feed + real exchange broker |
| `batch.py` | `BatchBacktest` — parallel parameter sweep across worker processes |

### Strategy Layer (`lib/strategy/`)

Strategies implement the `Strategy` ABC:

```python
class Strategy(ABC):
    def on_bar(self, panel: pd.DataFrame) -> list[Order]: ...
    def universe(self) -> list[str]: ...
    def lookback(self) -> int: ...
    def on_fill(self, fill: Fill) -> None: ...   # optional
    def on_stop(self) -> None: ...               # optional
```

Strategies are registered via `@register("name")` and retrieved with `get_strategy(name)`.

**Built-in strategies:** `sma_crossover`, `bollinger_reversion`, `rsi_reversion`, `breakout`, `macd_trend`, `adx_trend`, `pairs`, `regime_adaptive`, `multi_tf`, `portfolio_rebalance`

### Broker Layer (`lib/broker/`)

| Module | Purpose |
|--------|---------|
| `base.py` | `Broker` ABC — `submit_order()`, `get_position()`, `get_account()`, etc. |
| `simulated.py` | `SimulatedBroker` — market/limit/stop fills with slippage, fees, spread simulation |
| `position_manager.py` | `PositionManager` — extracted position lifecycle (open, add, reduce, close, reverse) |
| `kraken.py` | `KrakenBroker` — live Kraken spot trading |
| `oanda.py` | `OandaBroker` — live OANDA forex trading |

### Data Layer (`lib/data/`)

| Module | Purpose |
|--------|---------|
| `store.py` | `MarketDataStore` — Parquet read/write with deduplication |
| `historical.py` | `HistoricalFeed` — loads bars from store, groups by timestamp |
| `live.py` | `LiveFeed` — Kraken WebSocket v2 OHLC candles |
| `live_oanda.py` | `LiveOandaFeed` — OANDA streaming API |
| `price_panel.py` | `PricePanel` — rolling MultiIndex DataFrame for synchronized multi-symbol bars |
| `universe.py` | `Universe` — collection of instruments + timeframe |
| `exchange.py` | Exchange metadata and instrument definitions |

### Risk Layer (`lib/risk/`)

| Module | Purpose |
|--------|---------|
| `manager.py` | `RiskManager` — pre-trade check pipeline (position size, notional, daily loss, drawdown, exposure) |
| `exposure.py` | `ExposureManager` — gross/net exposure caps, per-asset concentration limits |
| `sizing.py` | Position sizers: `FixedFractionalSizer`, `ATRSizer`, `VolatilityScaledSizer`, `KellySizer` |

### Analytics Layer (`lib/analytics/`)

| Module | Purpose |
|--------|---------|
| `indicators.py` | Technical indicators (SMA, EMA, RSI, MACD, Bollinger, ADX, ATR) |
| `performance.py` | Performance metrics (Sharpe, Sortino, Calmar, drawdown, win rate) |
| `statistics.py` | Return distribution, volatility analysis, tail risk, autocorrelation |
| `correlation.py` | Correlation matrix, rolling correlation |
| `regime.py` | HMM-based regime detection |
| `scanner.py` | Indicator scanning, signal detection, pattern recognition |
| `utils.py` | Shared helpers: `log_returns()`, `bars_to_arrays()` |

### Events (`lib/events.py`)

Pub/sub event bus for cross-cutting concerns:

- `FillEvent` — order filled (typed fields: symbol, side, quantity, price)
- `SignalEvent` — strategy signal generated
- `RiskEvent` — risk limit breached
- `EquityUpdate` — account equity changed

### Models (`lib/models/`)

Core data models using `@dataclass`:

- `Bar` — OHLCV market data bar
- `Instrument` — tradeable asset (symbol, exchange, lot_size, tick_size)
- `Order` — order request (MARKET, LIMIT, STOP, STOP_LIMIT)
- `Fill` — execution report (price, fee, slippage)
- `Position` — open position with entry price and PnL tracking
- `Account` — balances, equity, margin, PnL

## Data Flow

```
Market Data Sources
    |
    v
DataFeed (Historical or Live)
    |
    v
Bar objects grouped by timestamp
    |
    v
SimulatedBroker.process_bars()  ←── fills pending limit/stop orders
    |
    v
PricePanel.append_bars()  ←── rolling MultiIndex DataFrame
    |
    v
Strategy.on_bar(panel)  ←── generates Order list
    |
    v
RiskManager.check()  ←── pre-trade validation pipeline
    |
    v
Broker.submit_order()  ←── SimulatedBroker or Exchange API
    |
    v
Fill  ←── execution report
    |
    v
PositionManager.apply_fill()  ←── updates positions & account
    |
    v
EventBus.emit(FillEvent)  ←── notifies subscribers
```

## Storage

Market data is stored as Parquet files:

```
data/
  kraken/
    BTC_USD/
      1h.parquet
      1d.parquet
    ETH_USD/
      1h.parquet
  oanda/
    EUR_USD/
      1h.parquet
```

Each Parquet file contains columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`, `trades`, `vwap`.

Backtest results, batch results, and stress test outputs are persisted via the Persistra state system.

## Dashboard

The web dashboard (`lib/dashboard/`) is a FastAPI application with Jinja2 templates and Plotly charts:

| Route | Purpose |
|-------|---------|
| `/` | Overview with quick stats |
| `/backtests/` | Backtest results with equity curves |
| `/batch/` | Parameter sweep results and heatmaps |
| `/portfolio/` | Current positions and P&L |
| `/market-data/` | Data coverage and ingestion status |
| `/signals/` | Strategy entry/exit visualization |
| `/stress-test/` | Stress test and drawdown analysis |
| `/analysis/` | Performance analytics, correlation, regimes |
