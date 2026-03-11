# Architecture

This document describes the technical architecture of the trader system: its ABC hierarchy, data flow, module structure, exchange abstraction, event bus, and Persistra integration.

## System Overview

The trader system is a multi-exchange algorithmic trading platform that supports backtesting, paper trading, and live trading through a unified set of abstractions. The core design principle is that **strategies are execution-mode agnostic** — the same `Strategy` subclass runs in backtest, paper, or live mode without modification.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Persistra Layer                         │
│           (processes, workflows, state management)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐   ┌──────────────────┐   ┌────────────────────┐  │
│  │ Strategy │──>│ ExecutionContext  │──>│      Broker        │  │
│  │  (ABC)   │   │  (ABC)           │   │  (ABC)             │  │
│  └──────────┘   │  - BacktestCtx   │   │  - SimulatedBroker │  │
│       │         │  - PaperCtx      │   │  - KrakenBroker    │  │
│       │         │  - LiveCtx       │   │  - KrakenFuturesBr │  │
│       v         └──────────────────┘   │  - OandaBroker     │  │
│  ┌──────────┐          │               └────────────────────┘  │
│  │  Orders  │<─────────┘                       │               │
│  └──────────┘   ┌──────────────────┐   ┌───────v────────────┐  │
│       │         │    DataFeed      │   │     Fills          │  │
│       v         │  (ABC)           │   └────────────────────┘  │
│  ┌──────────┐   │  - HistoricalFeed│          │               │
│  │RiskMgr   │   │  - LiveFeed     │   ┌───────v────────────┐  │
│  └──────────┘   │  - LiveFuturesFd│   │   EventBus         │  │
│                 │  - LiveOandaFeed │   │  (pub/sub)         │  │
│                 └──────────────────┘   └────────────────────┘  │
│                          │                                      │
│                 ┌────────v─────────┐                            │
│                 │   Exchange       │                            │
│                 │  (ABC)           │                            │
│                 │  - KrakenSpot    │                            │
│                 │  - KrakenFutures │                            │
│                 │  - Oanda         │                            │
│                 └──────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

## ABC Hierarchy

### DataFeed (`lib/data/feed.py`)

The `DataFeed` ABC defines how market data enters the system.

```python
class DataFeed(ABC):
    def subscribe(self, instrument: Instrument, timeframe: str) -> None: ...
    def next_bar(self) -> Bar | None: ...
    def historical_bars(self, instrument, timeframe, start, end) -> list[Bar]: ...
    def subscribe_all(self, instruments: list[Instrument], timeframe: str) -> None: ...
    def next_bars(self) -> list[Bar]: ...
```

**Implementations:**
- `HistoricalFeed` — Reads from `MarketDataStore` Parquet files for backtesting
- `LiveFeed` — Kraken spot WebSocket feed
- `LiveFuturesFeed` — Kraken futures WebSocket feed
- `LiveOandaFeed` — OANDA streaming feed

### Broker (`lib/broker/base.py`)

The `Broker` ABC defines order execution and account state.

```python
class Broker(ABC):
    def submit_order(self, order: Order) -> Order: ...
    def cancel_order(self, order_id: str) -> Order: ...
    def get_order(self, order_id: str) -> Order: ...
    def get_open_orders(self, instrument: Instrument | None = None) -> list[Order]: ...
    def get_position(self, instrument: Instrument) -> Position | None: ...
    def get_positions(self) -> list[Position]: ...
    def get_account(self) -> Account: ...
```

**Implementations:**
- `SimulatedBroker` — Used by backtest and paper contexts. Supports configurable `fee_rate`, `slippage_pct`, `spread_pips`, `margin_mode`, and `leverage`.
- `KrakenBroker` — Kraken spot REST API
- `KrakenFuturesBroker` — Kraken Futures REST API
- `OandaBroker` — OANDA v20 REST API

### ExecutionContext (`lib/execution/context.py`)

The `ExecutionContext` ABC composes a feed, broker, and risk manager into a single interface that strategies interact with. Strategies never touch the underlying components directly.

```python
class ExecutionContext(ABC):
    mode: str  # "backtest" | "paper" | "live"

    def get_universe(self) -> Universe: ...
    def get_broker(self) -> Broker: ...
    def get_risk_manager(self) -> RiskManager: ...
    def current_time(self) -> datetime: ...
```

**Implementations:**
- `BacktestContext` — Loads bars from `HistoricalFeed`, drives the bar-by-bar replay loop, uses `SimulatedBroker`. Supports spot, futures (margin mode with funding rate simulation), and forex (spread simulation).
- `PaperContext` — Uses a live `DataFeed` with `SimulatedBroker`
- `LiveContext` — Uses a live `DataFeed` with a real exchange `Broker`

### Strategy (`lib/strategy/base.py`)

The `Strategy` ABC defines the trading logic interface.

```python
class Strategy(ABC):
    def __init__(self, ctx: ExecutionContext, params: dict | None = None):
        self.ctx = ctx
        self.params = params or {}

    def on_bar(self, panel: pd.DataFrame) -> list[Order]: ...    # Required
    def universe(self) -> list[str]: ...                          # Required
    def lookback(self) -> int: ...                                # Required
    def on_fill(self, fill: Fill) -> None: ...                    # Optional
    def on_stop(self) -> None: ...                                # Optional
```

See [Strategies](strategies.md) for a full guide to writing strategies.

### Exchange (`lib/data/exchange.py`)

The `Exchange` ABC unifies per-exchange operations: fetching historical data, creating live feeds, creating brokers, and resolving instruments.

```python
class Exchange(ABC):
    name: str

    def fetch_ohlcv(self, symbol, timeframe, start=None, end=None) -> list[Bar]: ...
    def create_live_feed(self) -> DataFeed: ...
    def create_broker(self) -> Broker: ...
    def get_instruments(self) -> list[Instrument]: ...
```

**Implementations and registry:**

| Name | Class | Asset class | Default symbols |
|------|-------|-------------|-----------------|
| `kraken` | `KrakenSpotExchange` | Crypto spot | BTC/USD, ETH/USD, SOL/USD, XRP/USD |
| `kraken_futures` | `KrakenFuturesExchange` | Crypto perpetuals | BTC-PERP, ETH-PERP, SOL-PERP |
| `oanda` | `OandaExchange` | Forex | EUR/USD, GBP/USD, USD/JPY, AUD/USD |

Resolve by name:

```python
from data.exchange import get_exchange

exchange = get_exchange("kraken")
bars = exchange.fetch_ohlcv("BTC/USD", "1h", start=start, end=end)
```

The `EXCHANGE_REGISTRY` dict maps string names to exchange classes.

## Data Flow

The complete bar lifecycle from API to strategy execution:

```
Exchange API / WebSocket
         │
         v
    ┌─────────┐       ┌──────────────────┐
    │ DataFeed │──────>│ MarketDataStore  │  (Parquet files)
    └─────────┘       └──────────────────┘
         │                     │
         │  (live)             │  (backtest: HistoricalFeed reads from store)
         v                     v
    ┌──────────────────────────────┐
    │         PricePanel           │
    │  (rolling MultiIndex window) │
    └──────────────────────────────┘
                   │
                   v
    ┌──────────────────────────────┐
    │   Strategy.on_bar(window)    │
    │   -> list[Order]             │
    └──────────────────────────────┘
                   │
                   v
    ┌──────────────────────────────┐
    │      RiskManager.check()     │
    │   (pre-trade validation)     │
    └──────────────────────────────┘
                   │
                   v
    ┌──────────────────────────────┐
    │   Broker.submit_order()      │
    └──────────────────────────────┘
                   │
                   v
    ┌──────────────────────────────┐
    │          Fill                 │
    │   -> Strategy.on_fill()      │
    │   -> EventBus.publish()      │
    └──────────────────────────────┘
```

### Backtest Replay Loop Detail

The `BacktestContext.run()` method drives the replay:

1. Load bars for all symbols from `HistoricalFeed` (reads from `MarketDataStore`)
2. Group bars by timestamp
3. For each timestamp group:
   - Apply funding rate charges at 8-hour intervals (futures mode only)
   - `broker.process_bars(bar_group)` — fill pending limit/stop orders against current prices
   - `panel.append_bars(bar_group)` — update the rolling window
   - If panel is ready: `orders = strategy.on_bar(panel.get_window())`
   - For each order: `risk_manager.check(order, broker)` then `broker.submit_order(order)`
   - Record equity snapshot
4. Return equity curve, fills, bars processed, and final equity

## Module Diagram

```
lib/
├── analytics/          Stateless computation
│   ├── indicators.py   SMA, EMA, WMA, RSI, MACD, Bollinger, ATR, ADX, Stochastic, OBV
│   └── performance.py  Sharpe, drawdown, win rate, total return, etc.
│
├── broker/             Order execution
│   ├── base.py         Broker ABC
│   ├── simulated.py    Backtest/paper broker (fees, slippage, margin, spread)
│   ├── kraken.py       Kraken spot REST
│   ├── kraken_futures.py  Kraken Futures REST
│   └── oanda.py        OANDA v20 REST
│
├── config.py           Credentials (env vars), exchange defaults, risk defaults
│
├── dashboard/          FastAPI + Plotly interactive web dashboard
│
├── data/               Market data layer
│   ├── exchange.py     Exchange ABC + EXCHANGE_REGISTRY
│   ├── feed.py         DataFeed ABC
│   ├── historical.py   HistoricalFeed (reads from MarketDataStore)
│   ├── live.py         Kraken spot WebSocket feed
│   ├── live_futures.py Kraken futures WebSocket feed
│   ├── live_oanda.py   OANDA streaming feed
│   ├── store.py        MarketDataStore (Parquet OHLCV)
│   ├── tick_store.py   TickStore (daily Parquet ticks)
│   ├── result_store.py ResultStore (UUID-indexed results)
│   ├── price_panel.py  PricePanel (rolling MultiIndex DataFrame)
│   ├── state_parquet.py ParquetStateStore (DataFrame persistence)
│   ├── universe.py     Universe (symbol set + instruments + timeframe)
│   ├── kraken_api.py   Kraken spot REST client
│   ├── kraken_futures_api.py  Kraken Futures REST client
│   └── oanda_api.py    OANDA REST client
│
├── events.py           EventBus (publish/subscribe with ring buffer)
│
├── execution/          Execution contexts
│   ├── context.py      ExecutionContext ABC
│   ├── backtest.py     BacktestContext (bar-by-bar replay)
│   └── batch.py        BatchBacktest + ParameterGrid
│
├── models/             Domain models (dataclasses)
│   ├── bar.py          Bar (OHLCV + trades + vwap)
│   ├── order.py        Order, OrderSide, OrderType, OrderStatus, TimeInForce
│   ├── fill.py         Fill
│   ├── position.py     Position
│   ├── account.py      Account (balances + equity)
│   └── instrument.py   Instrument, FuturesInstrument
│
├── risk/               Risk management
│   └── manager.py      RiskManager (max position size, order value, drawdown limit)
│
└── strategy/           Strategy layer
    ├── base.py         Strategy ABC
    ├── registry.py     @register decorator + STRATEGY_REGISTRY
    └── sma_crossover.py  Built-in SMA crossover implementation
```

## Event Bus Architecture

The event bus (`lib/events.py`) provides decoupled publish/subscribe communication. It uses a global singleton with a ring buffer for recent event history.

### Event Types

| Type | Class | Emitted When |
|------|-------|-------------|
| `FILL` | `FillEvent` | An order is filled |
| `SIGNAL` | `SignalEvent` | A strategy generates a trading signal |
| `RISK` | `RiskEvent` | A risk limit is breached or an order is rejected |
| `EQUITY_UPDATE` | `EquityUpdate` | Account equity changes |

### Usage

```python
from events import event_bus, EventType, FillEvent

# Subscribe
def on_fill(event):
    print(f"Filled: {event.data['symbol']} {event.data['side']}")

event_bus.subscribe(EventType.FILL, on_fill)

# Publish
event_bus.publish(FillEvent(symbol="BTC/USD", side="BUY", quantity=Decimal("0.1"), price=Decimal("50000")))

# Query history
recent = event_bus.get_history(event_type=EventType.FILL, limit=10)
```

The ring buffer defaults to 1000 events. History is returned newest-first.

## Persistra Integration

The trader system uses Persistra for three things: **process orchestration**, **workflow DAGs**, and **persistent state**.

### Processes

Processes are entry points decorated with `@process("job")` or `@process("daemon")`:

- **Jobs** run once and exit (backtest, data ingestor, batch backtest)
- **Daemons** run continuously (paper/live trading, risk monitor, dashboard)

```bash
persistra process start <name> -p key=value -p key2=value2
```

| Process | Type | Purpose |
|---------|------|---------|
| `data_ingestor` | job | Fetch and store OHLCV data |
| `sma_crossover` | job | Run SMA crossover backtest |
| `sma_crossover_live` | daemon | Paper/live SMA crossover trading |
| `batch_backtest` | job | Parameter sweep backtesting |
| `risk_monitor` | daemon | Real-time risk monitoring |
| `dashboard` | daemon | Web dashboard server |

### Workflows

Workflows define DAGs of steps with dependencies. Each step can be a function or a process invocation.

| Workflow | Steps |
|----------|-------|
| `backtest` | ingest -> backtest -> analyze |
| `batch_backtest` | ingest -> batch sweep -> rank |
| `analyze` | statistical analysis pipeline |
| `stress_test` | Monte Carlo stress testing |

```bash
persistra workflow run backtest --param symbols=BTC/USD --param timeframe=1h
```

### State Management

Persistra state provides persistent key-value storage organized by namespaces:

| Namespace | Keys | Purpose |
|-----------|------|---------|
| `backtest.*` | `results`, `equity_curve_path`, `fills_path`, `universe` | Backtest output |
| `strategy.<name>.*` | `params`, `metrics` | Per-strategy parameters and results |
| `batch.*` | `best_params`, `best_metrics`, `total_runs`, `successful_runs` | Batch results |
| `data.*` | `last_update`, `{symbol}_{timeframe}_bars` | Data ingestor tracking |
| Global | `account_equity`, `daily_pnl`, `max_drawdown`, `execution_mode` | Account and system state |

State is defined in `persistra.toml` under `[state.schema]` with types, defaults, and history depth.

```bash
# Read state
persistra state get backtest.results
persistra state get strategy.sma_crossover.metrics

# State is also accessible in process code via env.state
ns = env.state.ns("backtest")
ns.set("results", metrics)
```

## Further Reading

- [Getting Started](getting-started.md) — Installation and first backtest
- [Strategies](strategies.md) — Writing custom strategies
- [Data Management](data-management.md) — Data ingestion and storage
- [Configuration Reference](configuration-reference.md) — All configuration options
