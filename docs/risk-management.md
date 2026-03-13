# Risk Management

The Algorithmic Trading Environment provides a multi-layered risk management system with pre-trade checks, position sizing, exposure limits, and circuit breakers.

## Overview

Risk checks are applied to every order before execution:

```
Strategy generates Order
    |
    v
RiskManager.check(order, broker)
    |
    ├── Kill switch check
    ├── Max position size check
    ├── Max order notional check
    ├── Daily loss limit check
    ├── Max drawdown check
    └── Exposure / concentration check
    |
    v
Order submitted to broker (if all checks pass)
```

If any check fails, the order is rejected and a `RiskEvent` is emitted via the event bus.

## Configuration

All risk parameters are configured via the `RiskConfig` dataclass:

```python
from decimal import Decimal
from config import RiskConfig

config = RiskConfig(
    max_position_size=Decimal("1.0"),        # Max quantity per position
    max_order_value=Decimal("100000"),        # Max notional per order
    daily_loss_limit=Decimal("-500"),         # Daily loss threshold
    max_drawdown_limit=Decimal("0.20"),       # 20% max drawdown from HWM
    max_exposure=Decimal("500000"),           # Gross exposure cap (optional)
    max_leverage=Decimal("5"),               # Max leverage (optional)
    max_concentration_pct=Decimal("0.25"),    # 25% max per asset
)
```

Pass it when creating the risk manager:

```python
from risk.manager import RiskManager

risk_mgr = RiskManager(risk_config=config)
```

Or pass individual parameters:

```python
risk_mgr = RiskManager(
    max_position_size=Decimal("1.0"),
    max_order_value=Decimal("100000"),
    daily_loss_limit=Decimal("-500"),
)
```

### Parameter Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_size` | `1.0` | Maximum quantity for any single position |
| `max_order_value` | `100000` | Maximum notional value (qty x price) per order |
| `daily_loss_limit` | `-500` | Daily P&L threshold; kill switch engages when breached |
| `max_drawdown_limit` | `0.20` | Maximum drawdown from high-water mark (as fraction) |
| `max_exposure` | `None` | Maximum gross exposure across all positions |
| `max_leverage` | `None` | Maximum portfolio leverage |
| `max_concentration_pct` | `0.25` | Maximum single-asset notional as fraction of equity |

## Pre-Trade Checks

### Kill Switch

An emergency stop that rejects all new orders when engaged.

- **Auto-engages** when daily loss limit is breached
- **Manual engagement:** `risk_mgr.kill_switch = True`
- **Reset:** `risk_mgr.reset_kill_switch()`

### Position Size Limit

Rejects orders where the resulting position would exceed `max_position_size`:

```python
# With max_position_size=1.0:
# Current position: 0.8 BTC
# New order: BUY 0.3 BTC → REJECTED (0.8 + 0.3 = 1.1 > 1.0)
# New order: BUY 0.2 BTC → ALLOWED  (0.8 + 0.2 = 1.0)
```

### Order Notional Limit

Rejects orders where `quantity * price > max_order_value`.

### Daily Loss Limit

Tracks intraday P&L by comparing current equity to session-start equity:

- When `current_equity - session_start_equity < daily_loss_limit`, the kill switch engages automatically
- Call `risk_mgr.reset_daily()` at the start of each trading day to reset the tracker

### Drawdown Circuit Breaker

Tracks the high-water mark (HWM) of account equity:

- Drawdown = `(HWM - current_equity) / HWM`
- When drawdown exceeds `max_drawdown_limit`, all new orders are rejected
- Call `risk_mgr.update_high_water_mark(equity)` to update the HWM

### Check Results

The `check()` method returns a `bool` — `True` if all checks pass:

```python
allowed = risk_mgr.check(order, broker)
if not allowed:
    print("Order rejected by risk manager")
```

To see individual check results, use `check_all()`:

```python
results = risk_mgr.check_all(order, broker)
for r in results:
    status = "PASS" if r.passed else "FAIL"
    print(f"  {status}: {r.check_name} - {r.reason}")
```

## Portfolio Exposure Limits

The `ExposureManager` provides portfolio-level checks beyond single-order limits:

```python
from decimal import Decimal
from risk.exposure import ExposureManager

exposure_mgr = ExposureManager(
    max_gross_exposure=Decimal("500000"),     # Total position notional cap
    max_net_exposure=Decimal("200000"),       # Long-short imbalance cap
    max_concentration_pct=Decimal("0.25"),    # 25% max per asset
)

result = exposure_mgr.check_order(order, broker)
if not result.passed:
    print(f"Exposure breach: {result.reason}")
```

### Gross Exposure

Sum of all position notional values (absolute). Prevents overall portfolio from becoming too large:

```
Gross = |Position A notional| + |Position B notional| + ...
```

### Net Exposure

Difference between long and short notional. Prevents extreme directional bias:

```
Net = |Long notional - Short notional|
```

### Concentration

No single position's notional should exceed `max_concentration_pct` of total equity. Prevents over-concentration in one asset.

## Dynamic Position Sizing

Instead of using fixed quantities, use position sizers that adapt to market conditions and account equity.

### Fixed Fractional

Risk a fixed percentage of equity per trade:

```python
from decimal import Decimal
from risk.sizing import FixedFractionalSizer

sizer = FixedFractionalSizer(
    risk_per_trade=Decimal("0.01"),      # Risk 1% of equity per trade
    stop_distance_pct=Decimal("0.02"),   # Stop loss at 2% from entry
)

quantity = sizer.calculate_size(
    instrument=instrument,
    signal_strength=1.0,
    account=broker.get_account(),
    current_price=Decimal("50000"),
)
# With equity=$10K: risk_amount = $100, stop_distance = $1000
# Quantity = $100 / $1000 = 0.1
```

### ATR-Based

Size inversely proportional to ATR (volatile assets get smaller positions):

```python
from risk.sizing import ATRSizer

sizer = ATRSizer(
    risk_per_trade=Decimal("0.01"),
    atr_multiplier=Decimal("2"),
)

quantity = sizer.calculate_size(
    instrument=instrument,
    signal_strength=1.0,
    account=broker.get_account(),
    current_price=Decimal("50000"),
    volatility=Decimal("1500"),  # Current ATR value
)
# Stop distance = 2 * ATR = $3000
# Quantity = ($10000 * 0.01) / $3000 = 0.033
```

### Volatility-Scaled

Target a fixed portfolio volatility contribution per position:

```python
from risk.sizing import VolatilityScaledSizer

sizer = VolatilityScaledSizer(
    target_vol_contribution=Decimal("0.02"),  # 2% vol contribution per position
)

quantity = sizer.calculate_size(
    instrument=instrument,
    signal_strength=1.0,
    account=broker.get_account(),
    current_price=Decimal("50000"),
    volatility=Decimal("0.60"),  # Annualized volatility
)
# Scales down position size for high-vol assets
```

### Kelly Criterion

Optimal sizing based on historical win rate and payoff ratio:

```python
from risk.sizing import KellySizer

sizer = KellySizer(
    win_rate=0.55,               # 55% win rate
    avg_win_loss_ratio=1.33,     # Avg win / avg loss
    kelly_fraction=0.25,         # Use quarter-Kelly for safety
)

quantity = sizer.calculate_size(
    instrument=instrument,
    signal_strength=1.0,
    account=broker.get_account(),
    current_price=Decimal("50000"),
)

# Update stats from recent trades
sizer.update_stats(win_rate=0.58, avg_win_loss_ratio=1.4)
```

### Sizer Comparison

All sizers share the same `calculate_size(instrument, signal_strength, account, current_price, volatility=None)` interface.

| Sizer | Best For | Key Constructor Params |
|-------|----------|----------------------|
| Fixed Fractional | General purpose, clear risk per trade | `risk_per_trade`, `stop_distance_pct` |
| ATR-Based | Adapting to current volatility | `risk_per_trade`, `atr_multiplier` + pass `volatility` |
| Volatility-Scaled | Equalizing risk contribution | `target_vol_contribution` + pass `volatility` |
| Kelly | Maximizing long-term growth | `win_rate`, `avg_win_loss_ratio`, `kelly_fraction` |

## Event Monitoring

Risk events are emitted via the event bus:

```python
from events import event_bus, EventType

def on_risk_event(event):
    print(f"Risk: {event.reason}")

event_bus.subscribe(EventType.RISK, on_risk_event)
```

## Recommended Defaults

### Conservative (New Strategies)

```python
RiskConfig(
    max_position_size=Decimal("0.1"),
    max_order_value=Decimal("5000"),
    daily_loss_limit=Decimal("-100"),
    max_drawdown_limit=Decimal("0.05"),   # 5% max drawdown
    max_concentration_pct=Decimal("0.15"),
)
```

### Moderate (Validated Strategies)

```python
RiskConfig(
    max_position_size=Decimal("0.5"),
    max_order_value=Decimal("25000"),
    daily_loss_limit=Decimal("-500"),
    max_drawdown_limit=Decimal("0.15"),
    max_concentration_pct=Decimal("0.25"),
)
```

### Aggressive (High-Confidence Strategies)

```python
RiskConfig(
    max_position_size=Decimal("2.0"),
    max_order_value=Decimal("100000"),
    daily_loss_limit=Decimal("-2000"),
    max_drawdown_limit=Decimal("0.25"),
    max_concentration_pct=Decimal("0.40"),
)
```

## Daily Operations

### Start of Day

```python
risk_mgr.reset_daily()
risk_mgr.update_high_water_mark(broker.get_account().equity)
```

### End of Day

Review risk events and position exposure:

```python
account = broker.get_account()
print(f"Daily P&L: {account.daily_pnl}")
print(f"Equity: {account.equity}")
print(f"Max drawdown: {account.max_drawdown}")

positions = broker.get_positions()
for pos in positions:
    print(f"  {pos.instrument.symbol}: {pos.side} {pos.quantity} "
          f"@ {pos.entry_price}, PnL={pos.unrealized_pnl}")
```
