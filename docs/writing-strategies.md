# Writing a Custom Strategy

This guide walks you through creating a trading strategy from scratch, using the Strategy ABC and built-in indicators.

## Strategy Interface

Every strategy extends `Strategy` and implements three required methods:

```python
from strategy.base import Strategy
from strategy.registry import register
from models.order import Order

@register("my_strategy")
class MyStrategy(Strategy):

    def universe(self) -> list[str]:
        """Symbols this strategy trades."""
        return ["BTC/USD"]

    def lookback(self) -> int:
        """Number of historical bars needed for indicators."""
        return 50

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        """Called on each new bar. Return orders to submit."""
        return []
```

Two optional methods are also available:

```python
    def on_fill(self, fill: Fill) -> None:
        """Called when an order is filled."""
        pass

    def on_stop(self) -> None:
        """Called on shutdown."""
        pass
```

## Step-by-Step Example: RSI + SMA Strategy

Let's build a strategy that buys when RSI is oversold AND price is above a long SMA (confirming uptrend), and sells when RSI is overbought.

### Step 1: Define the Class

```python
"""RSI trend-filtered strategy."""

import logging
from decimal import Decimal

import pandas as pd

from analytics.indicators import rsi, sma
from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy
from strategy.registry import register

log = logging.getLogger(__name__)


@register("rsi_trend")
class RSITrend(Strategy):
    def __init__(self, ctx, params=None):
        super().__init__(ctx, params)
        self.rsi_period = int(self.params.get("rsi_period", 14))
        self.sma_period = int(self.params.get("sma_period", 50))
        self.oversold = float(self.params.get("oversold", 30))
        self.overbought = float(self.params.get("overbought", 70))
        self.quantity = Decimal(str(self.params.get("quantity", "0.01")))
```

**Key points:**
- `super().__init__(ctx, params)` stores `self.ctx` and `self.params`
- Use `self.params.get(key, default)` for configurable parameters
- Always use `Decimal` for quantities and prices

### Step 2: Define Universe and Lookback

```python
    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return max(self.rsi_period, self.sma_period) + 5
```

The lookback should be large enough for all indicator computations plus a small buffer.

### Step 3: Implement on_bar

```python
    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        if panel.empty:
            return []

        orders = []
        symbols = panel.index.get_level_values("symbol").unique()

        for symbol in symbols:
            order = self._process_symbol(panel, symbol)
            if order is not None:
                orders.append(order)

        return orders
```

### Step 4: Process Each Symbol

```python
    def _process_symbol(self, panel, symbol):
        sym_data = panel.xs(symbol, level="symbol")
        if len(sym_data) < self.lookback():
            return None

        closes = sym_data["close"].values.astype(float)

        # Compute indicators
        rsi_values = rsi(closes, self.rsi_period)
        sma_values = sma(closes, self.sma_period)

        if len(rsi_values) == 0 or len(sma_values) == 0:
            return None

        current_rsi = rsi_values[-1]
        current_price = closes[-1]
        current_sma = sma_values[-1]

        # Access broker and position state
        broker = self.ctx.get_broker()
        instrument = self.ctx.get_universe().instruments[symbol]
        position = broker.get_position(instrument)
        has_position = position is not None and position.quantity > 0

        # BUY: RSI oversold + price above SMA (uptrend confirmation)
        if current_rsi < self.oversold and current_price > current_sma:
            if not has_position:
                log.info("BUY %s: RSI=%.1f, price above SMA", symbol, current_rsi)
                return Order(
                    instrument=instrument,
                    side=OrderSide.BUY,
                    type=OrderType.MARKET,
                    quantity=self.quantity,
                    strategy_id="rsi_trend",
                )

        # SELL: RSI overbought
        elif current_rsi > self.overbought and has_position:
            log.info("SELL %s: RSI=%.1f", symbol, current_rsi)
            return Order(
                instrument=instrument,
                side=OrderSide.SELL,
                type=OrderType.MARKET,
                quantity=position.quantity,
                strategy_id="rsi_trend",
            )

        return None
```

## Working with the Price Panel

The `panel` argument to `on_bar()` is a MultiIndex DataFrame with levels `(timestamp, symbol)`:

```python
# Get data for a single symbol
sym_data = panel.xs("BTC/USD", level="symbol")

# Available columns
closes = sym_data["close"].values.astype(float)
opens = sym_data["open"].values.astype(float)
highs = sym_data["high"].values.astype(float)
lows = sym_data["low"].values.astype(float)
volumes = sym_data["volume"].values.astype(float)

# Get all symbols in the panel
symbols = panel.index.get_level_values("symbol").unique()
```

For convenience, use `bars_to_arrays()`:

```python
from analytics.utils import bars_to_arrays

ohlcv = bars_to_arrays(sym_data)
# ohlcv.opens, ohlcv.highs, ohlcv.lows, ohlcv.closes, ohlcv.volumes
```

## Available Indicators

All indicators are in `analytics/indicators.py` and operate on NumPy arrays:

| Function | Signature | Returns |
|----------|-----------|---------|
| `sma(closes, period)` | Simple moving average | `np.ndarray` |
| `ema(closes, period)` | Exponential moving average | `np.ndarray` |
| `rsi(closes, period)` | Relative Strength Index (0-100) | `np.ndarray` |
| `macd(closes, fast, slow, signal)` | MACD line, signal, histogram | `tuple[np.ndarray, ...]` |
| `bollinger_bands(closes, period, num_std)` | Upper, middle, lower bands | `tuple[np.ndarray, ...]` |
| `atr(highs, lows, closes, period)` | Average True Range | `np.ndarray` |
| `adx(highs, lows, closes, period)` | Average Directional Index | `np.ndarray` |

## Order Types

```python
from models.order import Order, OrderSide, OrderType

# Market order — fills at next available price
Order(instrument=inst, side=OrderSide.BUY, type=OrderType.MARKET,
      quantity=Decimal("0.01"), strategy_id="my_strat")

# Limit order — fills at specified price or better
Order(instrument=inst, side=OrderSide.BUY, type=OrderType.LIMIT,
      quantity=Decimal("0.01"), price=Decimal("50000"),
      strategy_id="my_strat")

# Stop order — triggers at stop price, then fills as market
Order(instrument=inst, side=OrderSide.SELL, type=OrderType.STOP,
      quantity=Decimal("0.01"), stop_price=Decimal("48000"),
      strategy_id="my_strat")

# Stop-limit — triggers at stop price, then fills as limit
Order(instrument=inst, side=OrderSide.SELL, type=OrderType.STOP_LIMIT,
      quantity=Decimal("0.01"), stop_price=Decimal("48000"),
      price=Decimal("47500"), strategy_id="my_strat")
```

## Accessing Broker State

From within `on_bar()`, access the broker through `self.ctx`:

```python
broker = self.ctx.get_broker()

# Current positions
position = broker.get_position(instrument)
if position is not None:
    print(position.quantity)      # Decimal
    print(position.side)          # OrderSide.BUY or SELL
    print(position.entry_price)   # Volume-weighted average

# Account info
account = broker.get_account()
print(account.equity)
print(account.margin_available)

# Open orders
open_orders = broker.get_open_orders(instrument)
```

## Using Dynamic Position Sizing

Instead of hardcoding quantities, use position sizers from `risk/sizing.py`:

```python
from risk.sizing import FixedFractionalSizer, ATRSizer

# Risk 1% of equity per trade, stop 2 ATRs away
sizer = FixedFractionalSizer(risk_pct=Decimal("0.01"))
quantity = sizer.calculate_size(
    equity=account.equity,
    entry_price=Decimal(str(current_price)),
    stop_price=Decimal(str(current_price - 2 * atr_value)),
)
```

## Registering Your Strategy

The `@register("name")` decorator adds your strategy to the global registry:

```python
from strategy.registry import register

@register("my_strategy")
class MyStrategy(Strategy):
    ...
```

Retrieve it later:

```python
from strategy.registry import get_strategy, list_strategies

# Get strategy class by name
cls = get_strategy("my_strategy")
strategy = cls(ctx, params={...})

# List all registered strategies
print(list_strategies())
```

## Multi-Symbol Strategies

Strategies can trade multiple symbols simultaneously. The `PricePanel` ensures all symbols have bars at the same timestamp before calling `on_bar()`:

```python
@register("spread_strategy")
class SpreadStrategy(Strategy):

    def universe(self) -> list[str]:
        return ["BTC/USD", "ETH/USD"]

    def on_bar(self, panel):
        btc = panel.xs("BTC/USD", level="symbol")
        eth = panel.xs("ETH/USD", level="symbol")

        btc_close = float(btc["close"].values[-1])
        eth_close = float(eth["close"].values[-1])

        ratio = btc_close / eth_close
        # Trade based on ratio...
```

## Running Your Strategy

```python
from data.universe import Universe
from execution.backtest import BacktestContext

universe = Universe.from_symbols(["BTC/USD"], "1h", "kraken")
ctx = BacktestContext(universe=universe, initial_cash=Decimal("10000"))

strategy = MyStrategy(ctx, params={"rsi_period": 14, "quantity": "0.01"})
results = ctx.run(strategy)
```

## Built-in Strategy Reference

| Name | Module | Description |
|------|--------|-------------|
| `sma_crossover` | `strategy/sma_crossover.py` | SMA fast/slow crossover |
| `bollinger_reversion` | `strategy/mean_reversion.py` | Bollinger band mean reversion |
| `rsi_reversion` | `strategy/mean_reversion.py` | RSI oversold/overbought |
| `breakout` | `strategy/momentum.py` | N-period high/low breakout |
| `macd_trend` | `strategy/momentum.py` | MACD histogram crossover |
| `adx_trend` | `strategy/momentum.py` | ADX-filtered SMA crossover |
| `pairs` | `strategy/pairs.py` | Statistical pairs trading |
| `regime_adaptive` | `strategy/regime_adaptive.py` | Volatility regime switching |
| `multi_tf` | `strategy/multi_timeframe.py` | Multi-timeframe confirmation |
| `portfolio_rebalance` | `strategy/portfolio.py` | Portfolio optimization rebalancing |
