# Risk Management

The Trader platform provides a multi-layered risk management system with pre-trade checks, position sizing, exposure limits, and circuit breakers.

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

risk_mgr = RiskManager(config=config)
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

Each check returns a structured result:

```python
from risk.manager import RiskCheckResult

result = risk_mgr.check(order, broker)
if not result.passed:
    print(f"Rejected: [{result.check_name}] {result.reason}")
```

To see all check results:

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

sizer = FixedFractionalSizer(risk_pct=Decimal("0.01"))  # Risk 1% per trade

quantity = sizer.calculate_size(
    equity=Decimal("10000"),
    entry_price=Decimal("50000"),
    stop_price=Decimal("49000"),   # Stop loss level
)
# Risks $100 (1% of $10K). Distance to stop = $1000.
# Quantity = $100 / $1000 = 0.1
```

### ATR-Based

Size inversely proportional to ATR (volatile assets get smaller positions):

```python
from risk.sizing import ATRSizer

sizer = ATRSizer(
    risk_pct=Decimal("0.01"),
    atr_multiplier=Decimal("2"),
)

quantity = sizer.calculate_size(
    equity=Decimal("10000"),
    entry_price=Decimal("50000"),
    atr=Decimal("1500"),  # Current ATR
)
# Stop distance = 2 * ATR = $3000
# Quantity = ($10000 * 0.01) / $3000 = 0.033
```

### Volatility-Scaled

Target a fixed portfolio volatility contribution per position:

```python
from risk.sizing import VolatilityScaledSizer

sizer = VolatilityScaledSizer(
    target_vol=Decimal("0.10"),  # Target 10% annualized vol per position
)

quantity = sizer.calculate_size(
    equity=Decimal("10000"),
    entry_price=Decimal("50000"),
    annualized_vol=Decimal("0.60"),  # BTC annualized vol
)
# Scales down position size for high-vol assets
```

### Kelly Criterion

Optimal sizing based on historical win rate and payoff ratio:

```python
from risk.sizing import KellySizer

sizer = KellySizer(
    fraction=Decimal("0.25"),  # Use quarter-Kelly for safety
)

quantity = sizer.calculate_size(
    equity=Decimal("10000"),
    entry_price=Decimal("50000"),
    win_rate=Decimal("0.55"),
    avg_win=Decimal("200"),
    avg_loss=Decimal("150"),
)
```

### Sizer Comparison

| Sizer | Best For | Requires |
|-------|----------|----------|
| Fixed Fractional | General purpose, clear risk per trade | Stop loss level |
| ATR-Based | Adapting to current volatility | ATR indicator value |
| Volatility-Scaled | Equalizing risk contribution | Annualized volatility |
| Kelly | Maximizing long-term growth | Historical win/loss stats |

## Event Monitoring

Risk events are emitted via the event bus:

```python
from events import event_bus, EventType

def on_risk_event(event):
    print(f"Risk: {event.data.get('check_name')}: {event.data.get('reason')}")

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
