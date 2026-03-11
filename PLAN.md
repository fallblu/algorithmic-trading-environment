# Persistra Trading Environment — Architecture & Implementation Plan
 
## Context
 
Build a Persistra environment for systematic/quantitative backtesting and paper/live trading of crypto (Kraken spot + futures) with a pluggable architecture supporting other asset classes (e.g., Forex via OANDA). The system uses a unified strategy code model where the same process code runs identically in backtest, paper, and live modes — only the execution context changes. The first milestone is an end-to-end thin slice: SMA crossover on BTC/USD spot, validated across all three modes.
 
---
 
## 1. Architecture Overview
 
### Environment Directory Layout
 
```
trading/
├── persistra.toml              # Config: packages, state schema, process defs
├── processes/
│   ├── data_ingestor.py        # Daemon: fetches & stores market data
│   ├── sma_crossover.py        # Strategy process (thin-slice)
│   └── risk_monitor.py         # Daemon: portfolio-level risk checks
├── workflows/
│   └── backtest.py             # Backtest pipeline DAG
├── lib/
│   ├── models/                 # Domain models
│   │   ├── __init__.py
│   │   ├── instrument.py       # Instrument, SpotInstrument, FuturesInstrument
│   │   ├── order.py            # Order, OrderSide, OrderType, OrderStatus, TimeInForce
│   │   ├── fill.py             # Fill, partial fill tracking
│   │   ├── position.py         # Position (spot & leveraged)
│   │   ├── account.py          # Account (balances, equity, margin)
│   │   └── bar.py              # Bar (OHLCV), Trade, FundingRate
│   ├── execution/              # Execution context abstraction
│   │   ├── __init__.py
│   │   ├── context.py          # ExecutionContext ABC
│   │   ├── backtest.py         # BacktestContext (replay engine + sim broker)
│   │   ├── paper.py            # PaperContext (live data + sim broker)
│   │   └── live.py             # LiveContext (live data + real broker) [stub]
│   ├── broker/                 # Broker abstraction
│   │   ├── __init__.py
│   │   ├── base.py             # Broker ABC
│   │   ├── simulated.py        # SimulatedBroker (fill sim, position tracking)
│   │   └── kraken.py           # KrakenBroker (REST/WS) [stub for thin-slice]
│   ├── data/                   # Market data infrastructure
│   │   ├── __init__.py
│   │   ├── feed.py             # DataFeed ABC
│   │   ├── store.py            # MarketDataStore (Parquet read/write)
│   │   ├── historical.py       # HistoricalFeed (bar replay from store)
│   │   ├── live.py             # LiveFeed (WebSocket) [stub]
│   │   └── kraken_api.py       # Kraken REST client for OHLCV backfill
│   ├── risk/                   # Risk management
│   │   ├── __init__.py
│   │   └── manager.py          # RiskManager (pre-trade checks, limits)
│   ├── analytics/              # Performance analytics
│   │   ├── __init__.py
│   │   └── performance.py      # Sharpe, drawdown, win rate, etc.
│   └── strategy/               # Strategy base
│       ├── __init__.py
│       └── base.py             # Strategy ABC with on_bar() hook
└── .persistra/                 # Auto-created runtime directory
```
 
### Mapping Trading Concepts to Persistra Primitives
 
| Trading concept | Persistra primitive |
|---|---|
| Strategy | `@process("daemon")` with interval, or `@process("job")` for backtest |
| Market data ingestor | `@process("daemon", interval="1m")` |
| Risk monitor | `@process("daemon", interval="10s")` |
| Portfolio state | `StateNamespace` under `portfolio.*` |
| Open orders | `env.state.ns("orders")` |
| Position tracking | `env.state.ns("positions")` |
| Trade history | State with `history` enabled |
| Backtest pipeline | `Workflow` DAG |
| PnL time series | State stored as list/dict; large series via BinaryStore |
| Config (fees, slippage) | `persistra.toml` state schema + custom TOML sections |
 
### Data Flow
 
```
[Market Data] ──→ [DataFeed] ──→ [Strategy.on_bar()] ──→ [Order]
                                        │                    │
                                        │                    ▼
                                   [RiskManager] ◄── [Broker.submit_order()]
                                        │                    │
                                        ▼                    ▼
                                 [reject/allow]         [FillSimulator]
                                                            │
                                                            ▼
                                                    [Position update]
                                                    [Account update]
                                                    [State persist]
```
 
---
 
## 2. Core Domain Models (`lib/models/`)
 
### `instrument.py`
 
```python
@dataclass(frozen=True)
class Instrument:
    symbol: str           # "BTC/USD", "ETH-PERP"
    base: str             # "BTC"
    quote: str            # "USD"
    exchange: str         # "kraken"
    asset_class: str      # "crypto", "forex"
    tick_size: Decimal     # Minimum price increment
    lot_size: Decimal      # Minimum quantity increment
    min_notional: Decimal  # Minimum order value
 
@dataclass(frozen=True)
class FuturesInstrument(Instrument):
    contract_type: str     # "perpetual" | "fixed"
    max_leverage: Decimal
    initial_margin_rate: Decimal   # e.g. 0.01 for 100x
    maintenance_margin_rate: Decimal
    funding_interval_hours: int    # 8 for most perps
    expiry: datetime | None        # None for perpetuals
```
 
### `order.py`
 
```python
class OrderSide(Enum): BUY, SELL
class OrderType(Enum): MARKET, LIMIT, STOP, STOP_LIMIT
class OrderStatus(Enum): PENDING, OPEN, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED
class TimeInForce(Enum): GTC, IOC, FOK, GTD
 
@dataclass
class Order:
    id: str
    instrument: Instrument
    side: OrderSide
    type: OrderType
    quantity: Decimal
    price: Decimal | None          # For limit/stop-limit
    stop_price: Decimal | None     # For stop/stop-limit
    tif: TimeInForce
    status: OrderStatus
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    created_at: datetime
    updated_at: datetime
    strategy_id: str               # Which strategy placed this
    metadata: dict                 # Strategy-specific tags
```
 
### `fill.py`
 
```python
@dataclass(frozen=True)
class Fill:
    order_id: str
    instrument: Instrument
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    timestamp: datetime
    is_maker: bool
    slippage: Decimal              # Deviation from mid/expected price
```
 
### `position.py`
 
```python
@dataclass
class Position:
    instrument: Instrument
    side: OrderSide                # LONG=BUY, SHORT=SELL
    quantity: Decimal
    entry_price: Decimal           # Volume-weighted avg entry
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    margin_used: Decimal           # For futures
    liquidation_price: Decimal | None  # For futures
    opened_at: datetime
    last_updated: datetime
```
 
### `account.py`
 
```python
@dataclass
class Account:
    balances: dict[str, Decimal]   # {"USD": 10000, "BTC": 0.5}
    equity: Decimal                # Total value in quote currency
    margin_used: Decimal
    margin_available: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    daily_pnl: Decimal
    max_drawdown: Decimal
```
 
### `bar.py`
 
```python
@dataclass(frozen=True)
class Bar:
    instrument_symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int | None             # Number of trades in bar
    vwap: Decimal | None
 
@dataclass(frozen=True)
class FundingRate:
    instrument_symbol: str
    timestamp: datetime
    rate: Decimal
    next_funding_time: datetime
```
 
---
 
## 3. Key Abstractions
 
### `ExecutionContext` (`lib/execution/context.py`)
 
The central abstraction that makes strategy code mode-agnostic:
 
```python
class ExecutionContext(ABC):
    mode: str  # "backtest" | "paper" | "live"
 
    @abstractmethod
    def get_feed(self, instrument: Instrument) -> DataFeed: ...
 
    @abstractmethod
    def get_broker(self) -> Broker: ...
 
    @abstractmethod
    def get_risk_manager(self) -> RiskManager: ...
 
    @abstractmethod
    def current_time(self) -> datetime: ...  # Sim time in backtest, real time in live
```
 
- **BacktestContext**: Owns the replay loop. Creates `HistoricalFeed` and `SimulatedBroker`. Drives `current_time` from bar timestamps. The strategy's `on_bar()` is called synchronously per bar.
- **PaperContext**: Uses `LiveFeed` (WebSocket) for data but `SimulatedBroker` for execution. Real clock.
- **LiveContext**: Uses `LiveFeed` + `KrakenBroker`. Real clock, real money.
 
### `Broker` (`lib/broker/base.py`)
 
```python
class Broker(ABC):
    @abstractmethod
    def submit_order(self, order: Order) -> Order: ...
 
    @abstractmethod
    def cancel_order(self, order_id: str) -> Order: ...
 
    @abstractmethod
    def get_order(self, order_id: str) -> Order: ...
 
    @abstractmethod
    def get_open_orders(self, instrument: Instrument | None) -> list[Order]: ...
 
    @abstractmethod
    def get_position(self, instrument: Instrument) -> Position | None: ...
 
    @abstractmethod
    def get_positions(self) -> list[Position]: ...
 
    @abstractmethod
    def get_account(self) -> Account: ...
```
 
### `SimulatedBroker` (`lib/broker/simulated.py`)
 
Implements `Broker` for backtest and paper modes:
- Maintains in-memory order book of open orders
- On each bar: checks if limit/stop orders should trigger
- Calls `FillSimulator` for fill price calculation
- Updates `Position` and `Account` state
- Applies funding rates for perps at funding intervals
- Handles margin requirements and liquidation checks
 
### `FillSimulator` (embedded in `SimulatedBroker`)
 
Configurable slippage models:
- **Fixed**: `fill_price = mid + fixed_amount * side_sign`
- **Percentage of spread**: `fill_price = mid + (spread * pct) * side_sign`
- **Volume-based**: Slippage increases with `order_size / bar_volume` ratio
 
Fee calculation:
- Configurable maker/taker fee tiers (Kraken: 0.16%/0.26% default)
- Fee currency matches quote for spot, USD for futures
 
### `DataFeed` (`lib/data/feed.py`)
 
```python
class DataFeed(ABC):
    @abstractmethod
    def subscribe(self, instrument: Instrument, timeframe: str) -> None: ...
 
    @abstractmethod
    def next_bar(self) -> Bar | None: ...  # None = end of data
 
    @abstractmethod
    def historical_bars(self, instrument: Instrument, timeframe: str,
                        start: datetime, end: datetime) -> list[Bar]: ...
```
 
### `MarketDataStore` (`lib/data/store.py`)
 
Local storage using Parquet files organized as:
```
.persistra/market_data/{exchange}/{symbol}/{timeframe}.parquet
```
- Append-only writes for new bars
- Efficient range queries via Parquet row group filtering
- Schema: timestamp, open, high, low, close, volume, trades, vwap
 
### `RiskManager` (`lib/risk/manager.py`)
 
Pre-trade validation + portfolio monitoring:
- Max position size per instrument
- Max total exposure (sum of |position_value|)
- Daily loss limit (kill switch: cancels all open orders, flattens positions)
- Max drawdown limit
- Per-strategy allocation caps
- Margin utilization warnings/limits for futures
 
### `Strategy` base (`lib/strategy/base.py`)
 
```python
class Strategy(ABC):
    def __init__(self, ctx: ExecutionContext, params: dict): ...
 
    @abstractmethod
    def on_bar(self, bar: Bar) -> list[Order]: ...
 
    def on_fill(self, fill: Fill) -> None: ...  # Optional override
 
    def on_stop(self) -> None: ...  # Cleanup
```
 
Strategies return orders from `on_bar()`; the execution context handles submission through the broker and risk manager.
 
---
 
## 4. State Schema Design
 
### `persistra.toml` State Schema
 
```toml
[state.schema]
# Account
account_balances = { type = "dict", default = {}, history = 100 }
account_equity = { type = "float", default = 0.0, history = 1000 }
 
# Portfolio-level
total_exposure = { type = "float", default = 0.0 }
daily_pnl = { type = "float", default = 0.0, history = 365 }
max_drawdown = { type = "float", default = 0.0 }
 
# Execution mode
execution_mode = { type = "str", default = "backtest" }
```
 
### State Namespace Hierarchy
 
```
portfolio.balances          → dict of currency balances
portfolio.equity            → total equity float
portfolio.margin_used       → margin used across all positions
portfolio.daily_pnl         → today's PnL
 
positions.{symbol}          → Position dict (serialized)
 
orders.open                 → list of open order dicts
orders.filled               → recent filled orders (history-tracked)
 
strategy.{name}.signal      → latest signal value
strategy.{name}.params      → strategy parameters
strategy.{name}.metrics     → running performance metrics
 
risk.daily_loss             → current day's loss
risk.kill_switch            → bool, emergency stop flag
risk.exposure               → total portfolio exposure
 
backtest.results            → dict with Sharpe, drawdown, trades, etc.
backtest.equity_curve       → list of (timestamp, equity) tuples
```
 
### Serialization Strategy
 
- Positions, orders, account: Serialized as dicts (JSON-safe) — well under 1MB
- Equity curves for long backtests: May exceed 1MB — automatically handled by BinaryStore
- Bar data: Stored in Parquet files (not in Persistra state), referenced by path
 
---
 
## 5. Process Design
 
### `data_ingestor` — Daemon
 
```python
@process("daemon", interval="1m")
def run(env, symbol: str = "BTC/USD", timeframe: str = "1m"):
```
- Fetches latest OHLCV bars from Kraken REST API
- Appends to Parquet store
- Updates `env.state.ns("data").set("last_update", timestamp)`
- For backtest: not used (data pre-loaded)
 
### `sma_crossover` — Strategy Process
 
```python
@process("daemon", interval="1m")  # Live/paper mode
# OR
@process("job")  # Backtest mode (driven by workflow)
def run(env, mode: str = "backtest", fast_period: int = 10, slow_period: int = 30, ...):
```
- Instantiates `ExecutionContext` based on `mode` parameter
- Creates `SmaCrossover(Strategy)` with params
- In backtest: context drives replay loop calling `strategy.on_bar()` per bar
- In live/paper: context subscribes to feed, calls `on_bar()` on each new bar
- Persists positions, orders, PnL to namespaced state on each bar
 
### `risk_monitor` — Daemon
 
```python
@process("daemon", interval="10s")
def run(env):
```
- Reads positions from all strategy namespaces
- Computes portfolio-level exposure, daily PnL, drawdown
- Checks against risk limits
- Sets `risk.kill_switch = True` if limits breached
- Strategies check kill switch before submitting orders
 
---
 
## 6. Workflow Design
 
### Backtest Workflow (`workflows/backtest.py`)
 
```python
def build(env) -> Workflow:
    w = Workflow("backtest")
 
    # Step 1: Load/validate data
    w.add("load_data", load_and_validate_data)
 
    # Step 2: Run strategy backtest (job process)
    w.process("run_strategy", process="sma_crossover",
              params={"mode": "backtest", "fast_period": 10, "slow_period": 30},
              depends_on=["load_data"])
 
    # Step 3: Compute analytics
    w.add("analyze", compute_performance_analytics,
          depends_on=["run_strategy"])
 
    return w
```
 
### Live/Paper Mode
 
No workflow needed — strategies run as daemons:
```bash
persistra process start data_ingestor -p symbol=BTC/USD
persistra process start sma_crossover -p mode=paper -p fast_period=10 -p slow_period=30
persistra process start risk_monitor
```
 
---
 
## 7. Backtest Engine Design
 
### Replay Mechanics (in `BacktestContext`)
 
```python
class BacktestContext(ExecutionContext):
    def run(self, strategy: Strategy):
        bars = self.feed.historical_bars(instrument, timeframe, start, end)
        for bar in bars:
            self._current_time = bar.timestamp
 
            # 1. Process pending orders against this bar
            self.broker.process_bar(bar)
 
            # 2. Apply funding rates if applicable (futures, every 8h)
            self.broker.apply_funding_if_due(bar)
 
            # 3. Check margin/liquidation
            self.broker.check_margin(bar)
 
            # 4. Call strategy
            orders = strategy.on_bar(bar)
 
            # 5. Risk check + submit orders
            for order in orders:
                if self.risk_manager.check(order):
                    self.broker.submit_order(order)
 
            # 6. Record equity snapshot
            self._equity_curve.append((bar.timestamp, self.broker.get_account().equity))
```
 
### Fill Simulation Mechanics
 
**Market orders**: Filled on current bar at slippage-adjusted price
- `fill_price = bar.open + slippage` (next bar's open for more realism, configurable)
 
**Limit orders**: Filled if bar's low <= limit_price (buy) or high >= limit_price (sell)
- Fill at limit price (optimistic) or with configurable slippage
 
**Stop orders**: Triggered if bar's high >= stop (buy-stop) or low <= stop (sell-stop)
- Convert to market order, fill at stop price + slippage
 
**Volume check**: Optional rejection if `order_quantity > bar.volume * max_volume_participation`
 
**Fee calculation**: `fee = fill_quantity * fill_price * fee_rate`
 
**Funding rates (perps)**: Every 8 hours, debit/credit `position_value * funding_rate` to account
 
### Performance Analytics (`lib/analytics/performance.py`)
 
Computed from equity curve and trade list:
- Total return, annualized return
- Sharpe ratio, Sortino ratio
- Max drawdown (peak-to-trough), max drawdown duration
- Win rate, profit factor
- Average win / average loss
- Number of trades, average holding period
- Calmar ratio
 
---
 
## 8. First Thin-Slice Milestone — SMA Crossover on BTC/USD Spot
 
### What to Implement Fully
 
1. **Domain models**: `Instrument` (spot only), `Order` (market only), `Fill`, `Position` (spot), `Account`, `Bar`
2. **`SimulatedBroker`**: Market orders only, fixed slippage, flat fee rate, spot position tracking
3. **`MarketDataStore`**: Parquet read/write for OHLCV bars
4. **`HistoricalFeed`**: Replay bars from store
5. **`BacktestContext`**: Bar-by-bar replay with sim broker
6. **`Strategy` base + `SmaCrossover`**: SMA fast/slow crossover, long-only initially
7. **`RiskManager`**: Max position size check only
8. **`kraken_api.py`**: REST client to fetch OHLCV history for backfill
9. **`performance.py`**: Sharpe, max drawdown, total return, win rate
10. **Backtest workflow**: load_data → run_strategy → analyze
11. **`persistra.toml`**: Full config with packages, state schema
 
### What to Stub
 
- `LiveFeed` (WebSocket) — interface only
- `KrakenBroker` (real exchange) — interface only
- `PaperContext` — thin wrapper reusing SimulatedBroker + LiveFeed stub
- `LiveContext` — interface only
- `FuturesInstrument` — model defined but not used in thin-slice
- Funding rates, margin, liquidation — skipped for spot-only milestone
 
### Files to Create (in order)
 
```
 1. trading/persistra.toml
 2. trading/lib/__init__.py
 3. trading/lib/models/__init__.py
 4. trading/lib/models/instrument.py
 5. trading/lib/models/bar.py
 6. trading/lib/models/order.py
 7. trading/lib/models/fill.py
 8. trading/lib/models/position.py
 9. trading/lib/models/account.py
10. trading/lib/data/__init__.py
11. trading/lib/data/feed.py
12. trading/lib/data/store.py
13. trading/lib/data/kraken_api.py
14. trading/lib/data/historical.py
15. trading/lib/broker/__init__.py
16. trading/lib/broker/base.py
17. trading/lib/broker/simulated.py
18. trading/lib/risk/__init__.py
19. trading/lib/risk/manager.py
20. trading/lib/execution/__init__.py
21. trading/lib/execution/context.py
22. trading/lib/execution/backtest.py
23. trading/lib/strategy/__init__.py
24. trading/lib/strategy/base.py
25. trading/lib/analytics/__init__.py
26. trading/lib/analytics/performance.py
27. trading/processes/sma_crossover.py
28. trading/processes/data_ingestor.py
29. trading/workflows/backtest.py
```
 
### Persistra Framework Files to Reference
 
- `src/persistra/core/environment.py` — Environment API, `create()`, state access
- `src/persistra/core/state.py` — StateStore, StateNamespace, StateVar
- `src/persistra/process/base.py` — `@process` decorator, ProcessMeta
- `src/persistra/control/workflow.py` — Workflow DAG, `add()`, `process()`, `execute()`
- `src/persistra/process/_runner_script.py` — confirms `lib/` is on sys.path in subprocesses
 
### Dependencies (`persistra.toml` packages)
 
```toml
[dependencies]
packages = [
    "pandas>=2.0",
    "pyarrow>=14.0",
    "requests>=2.31",
    "numpy>=1.26",
]
```
 
---
 
## 9. Verification Plan
 
### End-to-End Test Flow
 
1. **Initialize environment**: `persistra init --name trading` inside `trading/` directory
2. **Backfill data**: Run `data_ingestor` as a job to fetch ~1 year of BTC/USD 1h bars from Kraken
   ```bash
   persistra process start data_ingestor -p symbol=BTC/USD -p timeframe=1h -p backfill_days=365
   ```
3. **Run backtest workflow**:
   ```bash
   persistra workflow run backtest
   ```
4. **Inspect results**:
   ```bash
   persistra state get backtest.results
   persistra state history portfolio.equity --last 100
   ```
5. **Validate**: Confirm Sharpe ratio, drawdown, and trade count are computed. Cross-check a few fills manually against the bar data to verify slippage and fees are applied correctly.
 
### Unit Test Approach
 
- Test `SimulatedBroker` independently: submit market order, verify fill price includes slippage + fees, verify position updated correctly
- Test `SmaCrossover.on_bar()`: feed synthetic bars, verify signal flips at crossover points
- Test `MarketDataStore`: write bars to Parquet, read back, verify integrity
- Test `RiskManager`: submit oversized order, verify rejection
- Test `performance.py`: feed known equity curve, verify Sharpe/drawdown match hand-calculated values
