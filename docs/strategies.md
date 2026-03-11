# Writing Custom Strategies

This guide covers the `Strategy` ABC contract, the strategy registry, the `PricePanel` DataFrame structure, accessing indicators, and building a custom strategy from scratch.

## Strategy ABC

All strategies extend `Strategy` from `lib/strategy/base.py`:

```python
from strategy.base import Strategy
from models.order import Order
from models.fill import Fill
import pandas as pd

class MyStrategy(Strategy):
    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        """Called on each new bar group. Return orders to submit."""
        ...

    def universe(self) -> list[str]:
        """Return the list of symbols this strategy trades."""
        ...

    def lookback(self) -> int:
        """Number of historical bars needed for indicator computation."""
        ...

    def on_fill(self, fill: Fill) -> None:
        """Optional: called when an order is filled."""
        pass

    def on_stop(self) -> None:
        """Optional: called when the strategy is stopped. Use for cleanup."""
        pass
```

### Constructor

The constructor receives an `ExecutionContext` and an optional `params` dict:

```python
def __init__(self, ctx: ExecutionContext, params: dict | None = None):
    self.ctx = ctx
    self.params = params or {}
```

- `self.ctx` provides access to the broker, risk manager, universe, and current time
- `self.params` holds strategy-specific parameters (passed as process args, converted from strings)

### Required Methods

**`on_bar(panel)`** — The core method. Called once per timestamp group with a rolling window of OHLCV data. Must return a `list[Order]` (empty list for no action).

**`universe()`** — Returns the list of symbol strings this strategy trades (e.g., `["BTC/USD", "ETH/USD"]`).

**`lookback()`** — The number of bars of history the strategy needs. The `PricePanel` buffers this many bars per symbol before calling `on_bar()`. For example, if your strategy uses a 50-period SMA, return `50`.

### Optional Methods

**`on_fill(fill)`** — Called when an order fills. Use this to update internal state, log trades, or adjust positions.

**`on_stop()`** — Called when the strategy is stopped (end of backtest, or daemon shutdown). Use for cleanup.

## Strategy Registry

The registry (`lib/strategy/registry.py`) allows strategies to be resolved by name, which is required for batch backtesting and dashboard integration.

### Registering a Strategy

Use the `@register` decorator:

```python
from strategy.registry import register
from strategy.base import Strategy

@register("momentum_rsi")
class MomentumRsi(Strategy):
    ...
```

The string name (`"momentum_rsi"`) is used in process parameters:

```bash
persistra process start batch_backtest -p strategy=momentum_rsi ...
```

### Resolving a Strategy

```python
from strategy.registry import get_strategy, list_strategies

# Get a strategy class by name
cls = get_strategy("momentum_rsi")

# List all registered strategy names
names = list_strategies()  # ["sma_crossover", "momentum_rsi", ...]
```

`get_strategy()` raises `KeyError` if the name is not found.

### Import Side Effects

Strategy modules must be imported before they can be resolved. In process files, ensure the module is imported:

```python
import strategy.sma_crossover  # noqa: F401  — triggers @register
```

## PricePanel Window

The `panel` argument to `on_bar()` is a pandas `DataFrame` with a `MultiIndex` of `(timestamp, symbol)`.

### Structure

```
                          open      high       low     close    volume  trades     vwap
timestamp           symbol
2024-01-01 00:00:00 BTC/USD  42150.0  42300.0  42050.0  42200.0   125.3     890  42175.5
                    ETH/USD   2250.0   2275.0   2240.0   2265.0  1450.0    3200   2257.8
2024-01-01 01:00:00 BTC/USD  42200.0  42400.0  42100.0  42350.0   130.1     920  42280.0
                    ETH/USD   2265.0   2290.0   2255.0   2280.0  1520.0    3400   2272.5
...
```

### Column Types

| Column | Type | Description |
|--------|------|-------------|
| `open` | `float64` | Opening price |
| `high` | `float64` | High price |
| `low` | `float64` | Low price |
| `close` | `float64` | Closing price |
| `volume` | `float64` | Trade volume |
| `trades` | `int64` | Number of trades |
| `vwap` | `float64` | Volume-weighted average price |

All `Decimal` fields from the `Bar` model are converted to `float64` at ingestion by `PricePanel`.

### Inner-Join Behavior

For multi-symbol strategies, the panel only includes timestamps where **all** symbols have data. This ensures every row in the window has data for every symbol, avoiding `NaN` alignment issues.

### Accessing Data

```python
def on_bar(self, panel: pd.DataFrame) -> list[Order]:
    # Get close prices for a specific symbol
    btc = panel.xs("BTC/USD", level="symbol")
    btc_closes = btc["close"].values  # numpy array

    # Get the latest bar for all symbols
    latest_ts = panel.index.get_level_values("timestamp")[-1]
    latest = panel.loc[latest_ts]  # DataFrame with symbol index

    # Get the latest close for one symbol
    latest_btc_close = panel.loc[(latest_ts, "BTC/USD"), "close"]

    # Get all closes as a pivoted DataFrame (timestamps x symbols)
    closes = panel["close"].unstack(level="symbol")
    # closes is a DataFrame with timestamp index and symbol columns
```

### Window Size

The window contains the last `lookback()` bars per symbol. If your strategy needs a 50-period SMA, set `lookback()` to return `50` (or more, to account for indicator warm-up).

## Constructing Orders

Orders are built using the `Order` dataclass from `lib/models/order.py`:

```python
from models.order import Order, OrderSide, OrderType, TimeInForce
from decimal import Decimal

order = Order(
    instrument=self.ctx.get_universe().instruments["BTC/USD"],
    side=OrderSide.BUY,
    type=OrderType.MARKET,
    quantity=Decimal("0.01"),
)
```

### Order Fields

| Field | Type | Description |
|-------|------|-------------|
| `instrument` | `Instrument` | The instrument to trade |
| `side` | `OrderSide` | `BUY` or `SELL` |
| `type` | `OrderType` | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT` |
| `quantity` | `Decimal` | Order size |
| `price` | `Decimal \| None` | Limit price (for `LIMIT` and `STOP_LIMIT`) |
| `stop_price` | `Decimal \| None` | Stop trigger price (for `STOP` and `STOP_LIMIT`) |
| `tif` | `TimeInForce` | `GTC`, `IOC`, `FOK`, `GTD` (default: `GTC`) |
| `strategy_id` | `str` | Optional identifier for the strategy |
| `metadata` | `dict` | Optional metadata dict |
| `id` | `str` | Auto-generated UUID |

### Order Types

- **`MARKET`** — Execute immediately at current price (plus slippage)
- **`LIMIT`** — Execute at `price` or better
- **`STOP`** — Triggers a market order when price reaches `stop_price`
- **`STOP_LIMIT`** — Triggers a limit order at `price` when price reaches `stop_price`

### TimeInForce

- **`GTC`** (Good Till Cancel) — Stays open until filled or cancelled
- **`IOC`** (Immediate Or Cancel) — Fill what you can immediately, cancel the rest
- **`FOK`** (Fill Or Kill) — Fill entirely or cancel entirely
- **`GTD`** (Good Till Date) — Stays open until a specified date

## Accessing Broker State

Strategies can query the broker through the execution context:

```python
def on_bar(self, panel: pd.DataFrame) -> list[Order]:
    broker = self.ctx.get_broker()

    # Check current position
    inst = self.ctx.get_universe().instruments["BTC/USD"]
    position = broker.get_position(inst)
    if position is not None:
        print(f"Current position: {position.quantity} @ {position.avg_price}")

    # Check account
    account = broker.get_account()
    print(f"Equity: {account.equity}")

    # Check open orders
    open_orders = broker.get_open_orders(inst)

    # Get all positions
    all_positions = broker.get_positions()
```

## Using Indicators

The `analytics.indicators` module provides stateless, NumPy-based indicator functions:

```python
from analytics.indicators import sma, ema, rsi, macd, bollinger_bands, atr, adx, stochastic, obv, wma
```

### Available Indicators

| Function | Signature | Returns |
|----------|-----------|---------|
| `sma(values, period)` | Simple Moving Average | `ndarray` of length `len(values) - period + 1` |
| `ema(values, period, alpha=None)` | Exponential Moving Average | `ndarray` of length `len(values) - period + 1` |
| `wma(values, period)` | Weighted Moving Average | `ndarray` of length `len(values) - period + 1` |
| `rsi(closes, period=14)` | Relative Strength Index [0-100] | `ndarray` of length `len(closes) - period` |
| `macd(closes, fast=12, slow=26, signal=9)` | MACD | `(macd_line, signal_line, histogram)` |
| `bollinger_bands(closes, period=20, std_dev=2.0)` | Bollinger Bands | `(upper, middle, lower)` |
| `atr(highs, lows, closes, period=14)` | Average True Range | `ndarray` of length `len(closes) - period` |
| `adx(highs, lows, closes, period=14)` | Average Directional Index [0-100] | `ndarray` |
| `stochastic(highs, lows, closes, k_period=14, d_period=3)` | Stochastic Oscillator | `(%K, %D)` |
| `obv(closes, volumes)` | On-Balance Volume | `ndarray` of same length as input |

All functions accept NumPy arrays and return NumPy arrays. They return empty arrays when insufficient data is provided.

### Using Indicators in a Strategy

```python
from analytics.indicators import sma
import numpy as np

def on_bar(self, panel: pd.DataFrame) -> list[Order]:
    btc = panel.xs("BTC/USD", level="symbol")
    closes = btc["close"].values

    fast = sma(closes, self.params.get("fast_period", 10))
    slow = sma(closes, self.params.get("slow_period", 30))

    if len(fast) == 0 or len(slow) == 0:
        return []

    # Compare latest values (align from the end)
    if fast[-1] > slow[-1]:
        # Bullish signal
        ...
```

## Example: Simple Momentum Strategy

Here is a complete strategy that buys when RSI crosses above 30 (oversold recovery) with an upward SMA trend filter, and sells when RSI crosses above 70 (overbought).

```python
from decimal import Decimal

import pandas as pd

from analytics.indicators import rsi, sma
from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy
from strategy.registry import register


@register("momentum_rsi")
class MomentumRsi(Strategy):
    """Buy on RSI oversold recovery with trend filter; sell on RSI overbought."""

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return max(self.params.get("rsi_period", 14), self.params.get("trend_period", 50)) + 5

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        orders = []
        quantity = Decimal(str(self.params.get("quantity", "0.01")))

        for symbol in self.universe():
            try:
                sym_data = panel.xs(symbol, level="symbol")
            except KeyError:
                continue

            closes = sym_data["close"].values
            rsi_period = self.params.get("rsi_period", 14)
            trend_period = self.params.get("trend_period", 50)

            rsi_values = rsi(closes, rsi_period)
            trend = sma(closes, trend_period)

            if len(rsi_values) < 2 or len(trend) < 1:
                continue

            current_rsi = rsi_values[-1]
            prev_rsi = rsi_values[-2]
            trend_up = closes[-1] > trend[-1]

            inst = self.ctx.get_universe().instruments[symbol]
            position = self.ctx.get_broker().get_position(inst)

            # Buy: RSI crosses above 30 from below, and price above SMA (trend filter)
            if prev_rsi < 30 and current_rsi >= 30 and trend_up and position is None:
                orders.append(Order(
                    instrument=inst,
                    side=OrderSide.BUY,
                    type=OrderType.MARKET,
                    quantity=quantity,
                    strategy_id="momentum_rsi",
                ))

            # Sell: RSI crosses above 70 (take profit on overbought)
            elif current_rsi > 70 and position is not None:
                orders.append(Order(
                    instrument=inst,
                    side=OrderSide.SELL,
                    type=OrderType.MARKET,
                    quantity=quantity,
                    strategy_id="momentum_rsi",
                ))

        return orders
```

### Running the Strategy

Create a process file at `processes/momentum_rsi.py`:

```python
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)


@process("job")
def run(
    env,
    symbols: str = "BTC/USD",
    timeframe: str = "1h",
    rsi_period: int = 14,
    trend_period: int = 50,
    quantity: str = "0.01",
    initial_cash: str = "10000",
    start: str = "",
    end: str = "",
):
    from analytics.performance import compute_performance
    from data.universe import Universe
    from execution.backtest import BacktestContext
    import strategy.momentum_rsi  # noqa: F401 — trigger @register

    from strategy.registry import get_strategy

    symbol_list = [s.strip() for s in symbols.split(",")]
    universe = Universe.from_symbols(symbol_list, timeframe)

    start_dt = datetime.fromisoformat(start) if start else datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)

    ctx = BacktestContext(
        universe=universe,
        start=start_dt,
        end=end_dt,
        initial_cash=Decimal(initial_cash),
        data_dir=Path(env.path) / ".persistra" / "market_data",
    )

    strategy_cls = get_strategy("momentum_rsi")
    strategy = strategy_cls(ctx, {
        "symbols": symbol_list,
        "quantity": quantity,
        "rsi_period": rsi_period,
        "trend_period": trend_period,
    })

    results = ctx.run(strategy)
    metrics = compute_performance(
        equity_curve=results["equity_curve"],
        fills=results["fills"],
    )

    log.info("Total Return: %.2f%%", metrics["total_return"] * 100)
    log.info("Sharpe Ratio: %.4f", metrics["sharpe_ratio"])
    log.info("Max Drawdown: %.2f%%", metrics["max_drawdown"] * 100)
```

Then run:

```bash
persistra process start momentum_rsi \
  -p symbols=BTC/USD \
  -p timeframe=1h \
  -p rsi_period=14 \
  -p trend_period=50
```

Or use batch backtesting to sweep parameters:

```bash
persistra process start batch_backtest \
  -p strategy=momentum_rsi \
  -p symbols=BTC/USD \
  -p grid='{"rsi_period": [10, 14, 21], "trend_period": [30, 50, 100]}'
```

## Multi-Symbol Strategies

The `PricePanel` supports multiple symbols natively. The inner-join ensures all symbols have data at each timestamp.

```python
def on_bar(self, panel: pd.DataFrame) -> list[Order]:
    # Pivot closes into a DataFrame: timestamps x symbols
    closes = panel["close"].unstack(level="symbol")

    # Cross-symbol signal: BTC/ETH ratio
    ratio = closes["BTC/USD"] / closes["ETH/USD"]
    ratio_sma = ratio.rolling(20).mean()

    if ratio.iloc[-1] < ratio_sma.iloc[-1]:
        # Ratio below mean: long BTC, short ETH (mean reversion)
        ...
```

## Tips

- **Parameter types**: Process args are always strings. Convert explicitly in `on_bar()` or in the process file before passing to the constructor.
- **Decimal vs float**: The `Order` model uses `Decimal` for quantities and prices. The `PricePanel` uses `float64`. Convert at the boundary.
- **Indicator warm-up**: Set `lookback()` large enough that indicators produce valid output from the first `on_bar()` call. Add a buffer (e.g., `period + 5`) to be safe.
- **Idempotent signals**: Check existing positions before placing orders to avoid doubling up.
- **Risk manager**: The `BacktestContext` runs `risk_manager.check()` on every order before submission. Orders that exceed `max_position_size` are silently rejected (logged as rejected).

## Further Reading

- [Architecture](architecture.md) — ABC hierarchy and data flow
- [Data Management](data-management.md) — Data ingestion and storage
- [Configuration Reference](configuration-reference.md) — SimulatedBroker defaults, exchange parameters
