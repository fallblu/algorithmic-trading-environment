# Trading Platform Major Refactor — Implementation Plan

## Current State Summary

The platform is a ~2,800 line Python trading system built on Persistra, with clean ABC-driven architecture:

- **Exchange support**: Kraken spot only (REST + WebSocket v2)
- **Execution modes**: Backtest, paper trading (simulated broker + live feed), live trading (real Kraken broker)
- **Strategy framework**: ABC-based with `on_bar()` receiving a MultiIndex DataFrame price panel; one example strategy (SMA crossover)
- **Data**: Parquet-based OHLCV storage, historical backfill via Kraken REST, live data via Kraken WebSocket
- **Analytics**: Performance metrics (Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor)
- **Models**: Instrument (with FuturesInstrument subclass), Bar, FundingRate, Order, Fill, Position, Account
- **Risk**: Pre-trade validation (max position size, max order value, kill switch)
- **No dashboard/visualization layer exists**

### Key Architecture Patterns
- `DataFeed` ABC → `HistoricalFeed`, `LiveFeed`
- `Broker` ABC → `SimulatedBroker`, `KrakenBroker`
- `ExecutionContext` ABC → `BacktestContext`, `PaperContext`, `LiveContext`
- `Strategy` ABC → `SmaCrossover`
- `Universe` from symbol lists; `PricePanel` for rolling window management
- Persistra processes (job/daemon) as entry points; workflows for DAG orchestration

---

## Phase 1: Kraken Derivatives (Perpetual Futures)

### Goal
Add perpetual futures trading on Kraken Futures (`futures.kraken.com`) across all three execution modes (backtest, paper, live).

### Key Design Decisions
- Kraken Futures has a **separate API** from Kraken spot (`futures.kraken.com` vs `api.kraken.com`), with different auth, endpoints, and WebSocket URLs.
- The existing `FuturesInstrument` model already exists with leverage/margin fields — we extend it.
- The `SimulatedBroker` needs margin accounting for futures; currently it does spot-style cash accounting.

### New/Modified Files

#### `lib/data/kraken_futures_api.py` (new)
REST client for `futures.kraken.com`:
- `fetch_ohlcv_futures()` — OHLCV candle data from `/api/charts/v1/trade/...`
- `backfill_ohlcv_futures()` — paginated historical backfill
- `fetch_funding_rate()` — current and historical funding rates from `/derivatives/api/v3/tickers`
- `fetch_instruments()` — available perpetual contracts from `/derivatives/api/v3/instruments`
- Symbol mapping: e.g. `"BTC-PERP"` → Kraken's `"PF_XBTUSD"`

#### `lib/data/kraken_futures_auth.py` (new)
Authentication for the Kraken Futures API:
- Uses `KRAKEN_FUTURES_API_KEY` and `KRAKEN_FUTURES_API_SECRET` env vars
- Different signing scheme from spot (still HMAC-based but different nonce/path handling)
- `private_futures_request()` for authenticated endpoints

#### `lib/data/live_futures.py` (new)
WebSocket feed for Kraken Futures (`wss://futures.kraken.com/ws/v1`):
- Subclass of `DataFeed`
- Subscribes to `candles_trade_{interval}` channel
- Subscribes to `ticker` channel for real-time mark price, funding rate, open interest
- Same daemon thread + asyncio pattern as existing `LiveFeed`
- Also publishes `FundingRate` objects alongside `Bar` objects

#### `lib/broker/kraken_futures.py` (new)
Live broker for Kraken Futures:
- Subclass of `Broker`
- Order submission via `/derivatives/api/v3/sendorder`
- Position management via `/derivatives/api/v3/openpositions` (Kraken Futures has native position tracking, unlike spot)
- Account/margin queries via `/derivatives/api/v3/accounts`
- Leverage setting via `/derivatives/api/v3/leveragepreferences`
- Order types: market, limit, stop, take-profit

#### `lib/broker/simulated.py` (modify)
Extend `SimulatedBroker` to support margin-based futures accounting:
- Add `margin_mode: bool` flag and `leverage: Decimal` parameter
- When `margin_mode=True`:
  - Opening a position requires `notional / leverage` as initial margin (deducted from available balance)
  - Track `margin_used` on Position objects
  - Compute `liquidation_price` based on maintenance margin rate
  - Apply funding rate charges/credits at configured intervals
  - PnL is computed on full notional, not just margin posted
- When `margin_mode=False`: existing spot behavior unchanged
- Add `apply_funding()` method called by backtest engine at funding intervals

#### `lib/data/universe.py` (modify)
- Add `from_futures_symbols()` class method that creates `FuturesInstrument` instances
- Add defaults dict `_KRAKEN_FUTURES_DEFAULTS` for common perp contracts (BTC-PERP, ETH-PERP, SOL-PERP, etc.)
- Set `asset_class="crypto_futures"` to distinguish from spot

#### `lib/execution/backtest.py` (modify)
- Detect whether universe contains `FuturesInstrument` and configure `SimulatedBroker` accordingly (margin mode, leverage)
- During replay loop, call `broker.apply_funding()` at 8-hour intervals when processing futures
- Pass funding rate data alongside bar data

#### `lib/execution/paper.py` and `lib/execution/live.py` (modify)
- Add factory logic: if universe is futures, use `LiveFuturesFeed` and (for live) `KrakenFuturesBroker`
- Paper mode: `LiveFuturesFeed` + `SimulatedBroker(margin_mode=True)`
- Live mode: `LiveFuturesFeed` + `KrakenFuturesBroker`

#### `processes/data_ingestor.py` (modify)
- Add `exchange` parameter support for `"kraken_futures"`
- Route to `kraken_futures_api.backfill_ohlcv_futures()` when exchange is futures

---

## Phase 2: OANDA Forex Integration

### Goal
Add forex trading via OANDA v20 REST API with streaming prices for live data, using `SimulatedBroker` for paper trading (not OANDA's practice account).

### Key Design Decisions
- OANDA REST v20 for historical data, orders, account info
- OANDA streaming API for real-time price updates (sub-second tick data)
- Paper trading uses `SimulatedBroker` with forex-appropriate defaults (pip-based, leverage, typical spreads)
- Tick data recording to Parquet for later analysis
- Forex instruments use pip-based tick sizing (e.g., 0.0001 for EUR/USD, 0.01 for USD/JPY)

### New/Modified Files

#### `lib/data/oanda_api.py` (new)
REST client for OANDA v20:
- `fetch_candles()` — OHLCV from `/v3/instruments/{instrument}/candles`
- `backfill_candles()` — paginated historical backfill with OANDA's 5000-candle limit per request
- `fetch_instruments()` — available forex pairs from `/v3/accounts/{id}/instruments`
- `fetch_pricing()` — current bid/ask from `/v3/accounts/{id}/pricing`
- Granularity mapping: `"1m"` → `"M1"`, `"1h"` → `"H1"`, `"1d"` → `"D"`, etc.
- Symbol format: our `"EUR/USD"` → OANDA's `"EUR_USD"`
- Auth via `OANDA_API_TOKEN` and `OANDA_ACCOUNT_ID` env vars
- Base URL selection: practice (`api-fxpractice.oanda.com`) vs live (`api-fxtrade.oanda.com`) based on `OANDA_ENVIRONMENT` env var

#### `lib/data/oanda_stream.py` (new)
Streaming price feed for OANDA:
- Connects to `stream-fxtrade.oanda.com/v3/accounts/{id}/pricing/stream`
- Parses streaming JSON price ticks (bid/ask/mid)
- Aggregates ticks into OHLCV bars at the configured timeframe
- Background thread with reconnection logic (same pattern as Kraken `LiveFeed`)
- **Tick recording**: optionally writes raw tick data to Parquet files under `.persistra/tick_data/oanda/{pair}/`
  - Schema: `(timestamp, bid, ask, mid, spread, liquidity)`
  - Configurable via `record_ticks=True` parameter
  - Rotates files daily to keep individual files manageable

#### `lib/data/live_oanda.py` (new)
`DataFeed` subclass for OANDA:
- Uses `oanda_stream.py` for real-time bar construction
- Uses `oanda_api.py` for historical bar fetching (warmup)
- Same interface as `LiveFeed` — `subscribe()`, `next_bar()`, `historical_bars()`

#### `lib/broker/oanda.py` (new)
Live broker for OANDA (for live trading mode only):
- Subclass of `Broker`
- Order submission via `/v3/accounts/{id}/orders` (market, limit, stop, trailing stop)
- Position queries via `/v3/accounts/{id}/positions`
- Account info via `/v3/accounts/{id}/summary`
- Native support for:
  - Fractional pip pricing
  - Leverage (OANDA handles margin server-side)
  - Take-profit and stop-loss attached to orders
  - Long/short position netting

#### `lib/data/universe.py` (modify)
- Add `_OANDA_DEFAULTS` dict for common forex pairs with correct tick sizes (pip values):
  - EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, etc.
  - Cross pairs: EUR/GBP, GBP/JPY, etc.
- Add `from_forex_symbols()` class method with `exchange="oanda"`, `asset_class="forex"`
- Forex lot sizes: standard (100,000), mini (10,000), micro (1,000)

#### `lib/broker/simulated.py` (modify)
- For forex paper trading: configure with forex-specific defaults
  - `fee_rate=Decimal("0")` (forex has no commission, cost is in spread)
  - `slippage_pct` models spread widening
  - Add `spread_pips` parameter for fixed simulated spread
- Add spread simulation: buy at ask (mid + half spread), sell at bid (mid - half spread)

#### `lib/execution/paper.py` and `lib/execution/live.py` (modify)
- Factory logic: if `exchange="oanda"`, use `LiveOandaFeed` and (for live) `OandaBroker`
- Paper mode: `LiveOandaFeed` + `SimulatedBroker` with forex config

#### `processes/data_ingestor.py` (modify)
- Route to `oanda_api.backfill_candles()` when `exchange="oanda"`

#### `lib/data/tick_store.py` (new)
Storage for raw tick data:
- Write/read tick DataFrames to Parquet under `.persistra/tick_data/{exchange}/{pair}/YYYY-MM-DD.parquet`
- Schema: `(timestamp_us, bid, ask, mid, spread, volume)`
- Query by date range
- Aggregation helpers: ticks → bars at arbitrary timeframes

---

## Phase 3: Historical Data Analysis Toolkit

### Goal
Provide statistical analysis and technical scanning capabilities on stored market data without running a backtest.

### New Files

#### `lib/analytics/data_analyzer.py` (new)
Core statistical analysis engine:

**Statistical Analysis:**
- `return_distribution(bars, period)` — compute return series, fit normal/t-distribution, compute skewness, kurtosis, JB test for normality
- `volatility_analysis(bars)` — realized vol, rolling vol (multiple windows), vol-of-vol, GARCH(1,1) parameter estimation
- `correlation_matrix(symbol_bars_dict)` — cross-asset return correlation matrix over configurable windows
- `rolling_correlation(bars_a, bars_b, window)` — time-varying correlation between two assets
- `regime_detection(bars, n_regimes=2)` — Hidden Markov Model with 2-3 states (low-vol trending, high-vol mean-reverting, crisis)
  - Uses `hmmlearn` library
  - Outputs regime labels, transition matrix, per-regime statistics
- `autocorrelation_analysis(bars, max_lag)` — ACF/PACF of returns and squared returns (detect mean-reversion vs momentum, and volatility clustering)
- `tail_risk_analysis(bars)` — VaR, CVaR at multiple confidence levels, extreme value theory (GPD fit to tails)

**Technical Scanning:**
- `scan_indicators(bars, indicators)` — compute a batch of technical indicators over a bar series
  - Moving averages (SMA, EMA, WMA), RSI, MACD, Bollinger Bands, ATR, ADX, Stochastic, OBV
  - Returns a DataFrame with all indicator columns aligned to bar timestamps
- `scan_signals(bars, signal_configs)` — detect buy/sell signal events from indicator combinations
  - Signal configs define conditions, e.g.: `{"type": "crossover", "fast": "ema_10", "slow": "sma_30"}`
  - Returns timestamped signal events with strength scores
- `scan_patterns(bars)` — detect candlestick patterns (doji, hammer, engulfing, etc.)
- `support_resistance(bars, method="clustering")` — identify S/R levels using k-means clustering of price levels or pivot points
- `scan_universe(store, exchange, symbols, timeframe, scan_config)` — run scans across multiple symbols, return ranked results

#### `lib/analytics/indicators.py` (new)
Pure indicator computation functions (stateless, NumPy-based):
- `sma(values, period)`, `ema(values, period, alpha)`, `wma(values, period)`
- `rsi(closes, period)`, `macd(closes, fast, slow, signal)`
- `bollinger_bands(closes, period, std_dev)`
- `atr(highs, lows, closes, period)`, `adx(highs, lows, closes, period)`
- `stochastic(highs, lows, closes, k_period, d_period)`
- `obv(closes, volumes)`
- All functions operate on NumPy arrays for performance

#### `workflows/analyze.py` (new)
Persistra workflow for data analysis:
- `analyze_symbol` — run full statistical analysis on a single symbol
- `scan_universe` — scan all symbols in universe for technical signals
- `correlation_report` — compute cross-asset correlations
- `regime_report` — run regime detection and label historical data

#### `persistra.toml` (modify)
- Add state schema fields for analysis results

---

## Phase 4: Monte Carlo Stress Testing

### Goal
Stress-test strategies using both bootstrap resampling and Geometric Brownian Motion simulation to assess robustness.

### New Files

#### `lib/analytics/monte_carlo.py` (new)
Core simulation engine with both methods:

**Bootstrap Resampling:**
- `bootstrap_equity_paths(returns, n_simulations, path_length, block_size=1)` — resample actual strategy returns with replacement
  - Optionally use **block bootstrap** (block_size > 1) to preserve autocorrelation structure
  - Input: return series from a completed backtest
  - Output: array of shape `(n_simulations, path_length)` of simulated equity paths

**Geometric Brownian Motion:**
- `gbm_equity_paths(mu, sigma, dt, n_simulations, path_length, initial_value)` — parametric simulation
  - Estimates drift (μ) and volatility (σ) from historical returns
  - Generates synthetic paths: `S(t+dt) = S(t) * exp((μ - σ²/2)dt + σ√dt * Z)`
  - Output: same shape as bootstrap

**Analysis Functions:**
- `compute_path_statistics(paths)` — for each simulated path compute: total return, max drawdown, Sharpe, final value
- `confidence_intervals(paths, levels=[0.05, 0.25, 0.50, 0.75, 0.95])` — percentile bands across simulations at each time step
- `probability_of_ruin(paths, ruin_threshold)` — probability that equity drops below threshold
- `var_cvar_from_simulations(paths, confidence)` — VaR and CVaR from terminal values
- `expected_shortfall_over_time(paths, threshold)` — time-varying expected shortfall
- `summary_report(paths, method_name)` — consolidated dict of all statistics

#### `lib/analytics/stress_test.py` (new)
High-level stress testing orchestrator:
- `run_stress_test(backtest_results, config)` where config specifies:
  - `n_simulations` (default: 1000)
  - `methods`: list of `["bootstrap", "gbm"]`
  - `block_size` for bootstrap
  - `confidence_levels` for interval computation
  - `ruin_threshold` for P(ruin) calculation
- Runs both methods, computes all statistics, returns structured results
- Saves results to Parquet under `.persistra/stress_tests/{strategy}_{timestamp}/`
  - `bootstrap_paths.parquet` — full path matrix
  - `gbm_paths.parquet` — full path matrix
  - `statistics.json` — summary statistics for both methods

#### `workflows/stress_test.py` (new)
Persistra workflow:
- Step 1: Load backtest results (equity curve, returns)
- Step 2: Run bootstrap simulation
- Step 3: Run GBM simulation
- Step 4: Compute statistics and save

---

## Phase 5: Batch Backtesting with Parameter Sweeps

### Goal
Run batches of backtests over the same timeframe varying one or more strategy parameters, using multiprocessing for parallelism.

### New Files

#### `lib/execution/batch.py` (new)
Batch backtest orchestrator:

```python
@dataclass
class ParameterGrid:
    """Defines parameter sweep space."""
    params: dict[str, list]  # e.g. {"fast_period": [5, 10, 15], "slow_period": [20, 30, 50]}

    def combinations(self) -> list[dict]:
        """Generate all parameter combinations (Cartesian product)."""
        ...

    @property
    def total(self) -> int:
        ...
```

```python
class BatchBacktest:
    """Runs multiple backtests with varying parameters."""

    def __init__(
        self,
        strategy_class: type[Strategy],
        universe: Universe,
        start: datetime,
        end: datetime,
        base_params: dict,        # Fixed params shared across all runs
        grid: ParameterGrid,      # Params to vary
        initial_cash: Decimal = Decimal("10000"),
        n_workers: int | None = None,  # None = cpu_count()
        data_dir: Path | None = None,
    ): ...

    def run(self) -> BatchResults: ...
```

- Uses `multiprocessing.Pool` with `n_workers` processes
- Each worker runs an independent `BacktestContext` + strategy
- **Data sharing**: preload bar data once in the main process, pass via shared memory or pickle to workers (Parquet files are on disk, so each worker reads independently — Parquet is fast enough)
- Progress tracking via `multiprocessing.Value` counter
- Catches exceptions per-run; records failures separately

#### `lib/analytics/batch_results.py` (new)
Results container and comparison:

```python
@dataclass
class BatchResults:
    """Aggregated results from a batch of backtests."""
    runs: list[dict]              # Per-run: {params, metrics, equity_curve_path}
    grid: ParameterGrid
    elapsed_seconds: float

    def as_dataframe(self) -> pd.DataFrame:
        """All runs as a DataFrame with param columns + metric columns."""
        ...

    def best_by(self, metric: str, ascending: bool = False) -> dict:
        """Return the run with the best value for a metric."""
        ...

    def heatmap_data(self, param_x: str, param_y: str, metric: str) -> pd.DataFrame:
        """Pivot table for 2D heatmap visualization of metric vs two params."""
        ...

    def sensitivity(self, param: str, metric: str) -> pd.DataFrame:
        """1D sensitivity: metric vs single param (averaged over other params)."""
        ...

    def save(self, path: Path) -> None:
        """Save all results to Parquet + JSON."""
        ...

    @classmethod
    def load(cls, path: Path) -> "BatchResults": ...
```

#### `workflows/batch_backtest.py` (new)
Persistra workflow:
- Step 1: Validate data availability
- Step 2: Run batch backtest
- Step 3: Compute summary statistics, identify best params
- Step 4: Save results

#### `processes/batch_backtest.py` (new)
Process entry point for batch backtests:
- Accepts parameter grid as JSON string or inline params
- Example: `persistra process start batch_backtest -p strategy=sma_crossover -p grid='{"fast_period":[5,10,15,20],"slow_period":[20,30,40,50]}'`

---

## Phase 6: Interactive HTML Dashboard

### Goal
Build a comprehensive web dashboard using FastAPI + Plotly that provides interactive visualizations of all system data: backtests, portfolios, live data, signals, stress tests, batch results.

### Technology Stack
- **Backend**: FastAPI (async, high-performance)
- **Charts**: Plotly (via `plotly.py` for server-side figure generation)
- **Templates**: Jinja2 for HTML page structure
- **CSS**: Minimal custom CSS + a lightweight CSS framework (Pico CSS or similar, no npm required)
- **Interactivity**: Plotly's built-in zoom/pan/hover + htmx for dynamic page updates without a JS build step
- **No frontend build process** — pure server-rendered HTML with embedded Plotly JSON

### Architecture

The dashboard is a standalone FastAPI application that reads from the same Parquet data store and Persistra state. It does NOT modify any trading state — it is read-only.

```
lib/dashboard/
├── app.py              # FastAPI application factory
├── routes/
│   ├── overview.py     # Main dashboard / overview page
│   ├── backtests.py    # Backtest results browser
│   ├── batch.py        # Batch backtest results + heatmaps
│   ├── portfolio.py    # Paper/live portfolio views
│   ├── market_data.py  # Historical data explorer
│   ├── signals.py      # Strategy signal visualization
│   ├── stress_test.py  # Monte Carlo visualization
│   └── analysis.py     # Data analysis results
├── charts/
│   ├── equity.py       # Equity curve charts
│   ├── candlestick.py  # OHLCV candlestick charts
│   ├── heatmap.py      # Parameter sweep heatmaps
│   ├── distribution.py # Return distribution charts
│   ├── monte_carlo.py  # MC simulation fan charts
│   ├── correlation.py  # Correlation matrices
│   ├── signals.py      # Buy/sell signal overlay charts
│   └── common.py       # Shared chart utilities, theming
├── templates/
│   ├── base.html       # Base template with nav, footer
│   ├── overview.html
│   ├── backtest_detail.html
│   ├── batch_detail.html
│   ├── portfolio.html
│   ├── market_data.html
│   ├── signals.html
│   ├── stress_test.html
│   └── analysis.html
└── static/
    └── style.css       # Minimal custom styles
```

### Pages & Visualizations

#### Overview Page (`/`)
- System status: running processes, data freshness, latest backtest results
- Quick stats cards: total strategies, active paper/live trades, latest Sharpe
- Recent activity feed (last N fills, signals, risk events)
- Navigation to all sub-pages

#### Backtest Browser (`/backtests`)
- List of all completed backtests with key metrics (sortable table)
- Click into detail view:
  - **Equity curve** (interactive Plotly line chart with drawdown shading)
  - **Trade markers** overlaid on price candlestick chart (green triangles = buy, red = sell)
  - **Metrics table**: all performance stats
  - **Per-symbol breakdown** table
  - **Return distribution** histogram with fitted normal overlay
  - **Underwater plot** (drawdown over time)
  - **Monthly returns heatmap** (month × year grid)
  - **Rolling Sharpe** line chart (rolling window Sharpe over time)

#### Batch Backtest Results (`/batch`)
- List of batch runs
- Detail view:
  - **2D parameter heatmap** (e.g., fast_period × slow_period colored by Sharpe)
  - **1D sensitivity plots** (metric vs single parameter, other params averaged)
  - **Top-N runs table** ranked by selected metric
  - **Equity curve overlay** of top-N parameter sets on same chart
  - **Parameter distribution** of top performers

#### Portfolio View (`/portfolio`)
- Current positions table (symbol, side, qty, entry, unrealized PnL, %)
- Account summary (equity, cash, margin, daily PnL)
- Live equity curve (auto-refreshing via htmx polling)
- Recent fills table
- Position history timeline

#### Market Data Explorer (`/data`)
- Symbol selector dropdown
- **Interactive candlestick chart** with volume bars
- Timeframe selector
- Date range picker
- Technical indicator overlays (SMA, EMA, Bollinger, RSI subplot, MACD subplot)
- Data availability heatmap (which symbols/timeframes have data, date ranges)

#### Signal Viewer (`/signals`)
- Select strategy + symbol
- Candlestick chart with buy/sell signal markers
- Signal strength indicators
- Filter by signal type, date range
- Signal statistics (frequency, avg return after signal)

#### Stress Test Viewer (`/stress`)
- Select a stress test run
- **Fan chart**: median path with confidence interval bands (5th/25th/75th/95th percentiles)
- **Terminal value distribution** histogram for bootstrap and GBM side-by-side
- **Probability of ruin** vs threshold level curve
- **Max drawdown distribution** histogram
- **Statistics summary** table comparing bootstrap vs GBM results
- **Individual path spaghetti plot** (showing N random sample paths)

#### Data Analysis Viewer (`/analysis`)
- **Return distribution** with QQ plot
- **Volatility regime chart** (rolling vol with regime labels color-coded)
- **Correlation matrix heatmap** (interactive, shows value on hover)
- **Autocorrelation plots** (ACF/PACF bar charts)
- **Support/resistance levels** overlaid on price chart
- **Regime timeline** with state probabilities over time

### Dashboard Process

#### `processes/dashboard.py` (new)
Persistra daemon process that runs the FastAPI server:
```python
@process("daemon", interval="0s")  # runs once, blocks on server
def run(env, host="127.0.0.1", port=8050):
    import uvicorn
    from dashboard.app import create_app
    app = create_app(env)
    uvicorn.run(app, host=host, port=port)
```

Usage: `persistra process start dashboard -p port=8050`

---

## Phase 7: Cross-Cutting Improvements

### 7a. Exchange Abstraction Layer

Currently, exchange-specific logic is scattered. Introduce a cleaner abstraction:

#### `lib/data/exchange.py` (new)
```python
class Exchange(ABC):
    """Unified interface for exchange-specific operations."""
    name: str

    @abstractmethod
    def fetch_ohlcv(self, symbol, timeframe, start, end) -> list[Bar]: ...

    @abstractmethod
    def create_live_feed(self) -> DataFeed: ...

    @abstractmethod
    def create_broker(self) -> Broker: ...

    @abstractmethod
    def get_instruments(self) -> list[Instrument]: ...
```

Implementations: `KrakenSpotExchange`, `KrakenFuturesExchange`, `OandaExchange`

This allows `Universe.from_symbols()` to auto-resolve the correct exchange adapter and `ExecutionContext` subclasses to be exchange-agnostic.

### 7b. Result Persistence & Registry

#### `lib/data/result_store.py` (new)
Centralized storage and indexing of all results:
- Backtest results, batch results, stress test results, analysis results
- Each result gets a UUID, timestamp, and metadata (strategy name, params, universe)
- Index file (JSON or SQLite) for fast listing/querying
- Parquet files for heavy data (equity curves, paths)
- The dashboard reads from this store

### 7c. Strategy Registry

#### `lib/strategy/registry.py` (new)
```python
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}

def register(name: str):
    def decorator(cls):
        STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator

def get_strategy(name: str) -> type[Strategy]:
    return STRATEGY_REGISTRY[name]
```

All strategies use `@register("sma_crossover")` decorator. Batch backtests and the dashboard can resolve strategies by name string.

### 7d. Configuration Improvements

#### `lib/config.py` (new)
Centralized configuration loading:
- Exchange credentials from env vars (already done per-exchange, but centralize the pattern)
- Default parameters for each exchange (fee rates, tick sizes, etc.)
- Dashboard settings (port, host, theme)
- Risk defaults

### 7e. Logging & Events

#### `lib/events.py` (new)
Simple event bus for decoupled communication:
- Events: `FillEvent`, `SignalEvent`, `RiskEvent`, `EquityUpdate`
- The dashboard can subscribe to events for real-time updates
- Risk monitor can subscribe to fill events
- Stored in a ring buffer for recent history

---

## Dependency Changes

### New Dependencies (`persistra.toml`)
```toml
[dependencies]
packages = [
    # Existing
    "pandas>=2.0",
    "pyarrow>=14.0",
    "requests>=2.31",
    "numpy>=1.26",
    "websockets>=16.0",
    # New — Dashboard
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "jinja2>=3.1",
    "plotly>=5.24",
    # New — Analysis
    "scipy>=1.14",
    "hmmlearn>=0.3",
    # New — OANDA streaming
    "httpx>=0.28",       # async HTTP for OANDA streaming
]
```

---

## Implementation Order & Phasing

### Recommended sequence (each phase builds on prior):

1. **Phase 7a-7e: Cross-cutting improvements** (foundation)
   - Exchange abstraction, result store, strategy registry, config, events
   - These provide cleaner patterns that phases 1-6 build on
   - ~3-4 new files, moderate modifications

2. **Phase 3: Historical data analysis** (no exchange dependency)
   - Indicators library and data analyzer
   - Tests can run on existing stored Kraken data
   - ~3 new files

3. **Phase 4: Monte Carlo stress testing** (depends on backtest results)
   - Simulation engine and stress test orchestrator
   - Tests run on existing backtest results
   - ~2 new files

4. **Phase 5: Batch backtesting** (depends on backtest engine)
   - Parameter grid, batch runner, results container
   - Uses existing BacktestContext in parallel
   - ~3 new files

5. **Phase 1: Kraken derivatives** (parallel with phases 3-5)
   - Futures API, auth, live feed, broker, model updates
   - ~4 new files, moderate modifications to existing

6. **Phase 2: OANDA forex** (parallel with phase 1)
   - OANDA API, streaming, live feed, broker
   - ~5 new files, moderate modifications to existing

7. **Phase 6: Dashboard** (last — needs all data sources)
   - FastAPI app, routes, chart generators, templates
   - ~20 new files (but mostly thin route/chart files)
   - This is the largest phase by file count but benefits from all prior phases being complete

### Estimated File Impact
- **New files**: ~45
- **Modified files**: ~10
- **New lines of code**: ~6,000-8,000
- **Total phases**: 7 (with sub-phases)

---

## Testing Strategy

Each phase should include tests under `tests/`:

- `tests/test_indicators.py` — unit tests for all indicator functions
- `tests/test_monte_carlo.py` — test simulation shape, statistics
- `tests/test_batch.py` — test parameter grid generation, parallel execution
- `tests/test_simulated_broker_margin.py` — test futures margin accounting
- `tests/test_oanda_api.py` — mock-based tests for OANDA REST client
- `tests/test_data_analyzer.py` — test statistical analysis functions
- `tests/test_dashboard_routes.py` — FastAPI test client for route smoke tests

---

## Risk & Considerations

1. **API rate limits**: Both Kraken Futures and OANDA have rate limits. All API clients should implement rate limiting (sleep between requests for backfill, respect Retry-After headers).

2. **Data consistency**: Forex markets close on weekends; the bar timeline will have gaps. The `PricePanel` and `HistoricalFeed` should handle this gracefully.

3. **Timezone handling**: Forex operates in different sessions (Tokyo, London, New York). All timestamps remain UTC internally, but the dashboard should offer timezone display options.

4. **Decimal precision**: Forex prices need 5 decimal places (for JPY pairs: 3). The existing `Decimal` usage handles this correctly.

5. **Memory for batch backtests**: With large parameter grids (e.g., 100+ combinations), memory usage could be significant. Each worker should only return summary metrics + equity curve file path, not full in-memory data.

6. **Dashboard security**: The dashboard is local-only by default (`127.0.0.1`). If exposed on a network, authentication should be added (out of scope for initial implementation, but the plan accommodates it).
