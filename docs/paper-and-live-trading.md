# Paper & Live Trading

This guide covers transitioning from backtesting to paper trading (simulated execution with live data) and live trading (real money).

## Paper Trading

Paper trading uses live market data from exchanges but executes orders through the `SimulatedBroker`. This lets you validate strategy behavior in real market conditions without risking capital.

### Setup

```python
from decimal import Decimal
from data.universe import Universe
from execution.paper import PaperContext
from strategy.sma_crossover import SmaCrossover

universe = Universe.from_symbols(
    symbols=["BTC/USD"],
    timeframe="1h",
    exchange="kraken",
)

ctx = PaperContext(
    universe=universe,
    initial_cash=Decimal("10000"),
    fee_rate=Decimal("0.0026"),
    slippage_pct=Decimal("0.0001"),
    max_position_size=Decimal("1.0"),
)

strategy = SmaCrossover(ctx, params={
    "fast_period": 10,
    "slow_period": 30,
    "quantity": "0.01",
    "symbols": ["BTC/USD"],
})
```

### Running

Paper trading follows a lifecycle:

```python
# 1. Subscribe to live data feeds
ctx.subscribe_all(timeframe="1h")

# 2. Warm up with historical bars for indicator computation
ctx.warmup(strategy, timeframe="1h", warmup_bars=50)

# 3. Process incoming bars (call in a loop or on a timer)
result = ctx.run_once(strategy)

# 4. Shutdown when done
ctx.shutdown()
```

### Running as a Daemon

Use the Persistra process for continuous paper trading:

```bash
persistra process start live_trader \
    -p mode=paper \
    -p strategy=sma_crossover \
    -p symbols=BTC/USD \
    -p timeframe=1m \
    -p params='{"fast_period":10,"slow_period":30,"quantity":"0.01"}' \
    -p initial_cash=10000
```

The daemon polls every 10 seconds, processing new bars as they arrive.

## Live Trading

Live trading sends real orders to exchange APIs. The `LiveContext` uses `KrakenBroker` or `OandaBroker` for order execution.

### Prerequisites

1. **Exchange account** with API access enabled
2. **API credentials** set as environment variables:

```bash
# Kraken
export KRAKEN_API_KEY="your-key"
export KRAKEN_API_SECRET="your-secret"

# OANDA
export OANDA_API_TOKEN="your-token"
export OANDA_ACCOUNT_ID="your-account-id"
export OANDA_ENVIRONMENT="practice"   # "practice" or "live"
```

3. **Thorough paper trading** — validate your strategy works correctly before going live

### Setup

```python
from decimal import Decimal
from data.universe import Universe
from execution.live import LiveContext
from strategy.sma_crossover import SmaCrossover

universe = Universe.from_symbols(
    symbols=["BTC/USD"],
    timeframe="1h",
    exchange="kraken",
)

ctx = LiveContext(
    universe=universe,
    max_position_size=Decimal("0.5"),
    max_order_value=Decimal("5000"),
    daily_loss_limit=Decimal("-200"),
)

strategy = SmaCrossover(ctx, params={
    "fast_period": 10,
    "slow_period": 30,
    "quantity": "0.01",
    "symbols": ["BTC/USD"],
})
```

### LiveContext Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `universe` | `Universe` | required | Instruments and timeframe |
| `max_position_size` | `Decimal` | `1.0` | Max quantity per position |
| `max_order_value` | `Decimal` | `100000` | Max notional per order |
| `daily_loss_limit` | `Decimal` | `-500` | Daily loss threshold (triggers kill switch) |

### Running Live

The lifecycle is identical to paper trading:

```python
ctx.subscribe_all(timeframe="1h")
ctx.warmup(strategy, timeframe="1h", warmup_bars=50)

# Main loop
while running:
    result = ctx.run_once(strategy)
    time.sleep(10)

ctx.shutdown()
```

Or via Persistra:

```bash
persistra process start live_trader \
    -p mode=live \
    -p strategy=sma_crossover \
    -p symbols=BTC/USD \
    -p timeframe=1m \
    -p params='{"fast_period":10,"slow_period":30,"quantity":"0.01"}'
```

### Error Handling

The `LiveContext` wraps order submission in try/except. If an exchange API call fails:

- The error is logged
- The order is skipped (not retried automatically)
- The strategy continues processing subsequent bars

Check logs for `APIError`, `KrakenAPIError`, or `OandaAPIError` messages.

## Risk Management in Live Trading

Live trading benefits from the full risk management pipeline. Configure via `RiskConfig`:

```python
from config import RiskConfig

risk_config = RiskConfig(
    max_position_size=Decimal("0.5"),
    max_order_value=Decimal("5000"),
    daily_loss_limit=Decimal("-200"),
    max_drawdown_limit=Decimal("0.10"),     # 10% max drawdown
    max_concentration_pct=Decimal("0.25"),  # 25% max per asset
)
```

See [Risk Management](risk-management.md) for the full configuration guide.

## Monitoring

### Dashboard

Start the dashboard to monitor live positions and performance:

```bash
persistra run dashboard
```

Key monitoring pages:

- **Portfolio** (`/portfolio/`) — current positions, balances, unrealized P&L
- **Signals** (`/signals/`) — recent strategy signals and trade entries

### Event Bus

Subscribe to events programmatically for custom monitoring:

```python
from events import event_bus, EventType

def on_fill(event):
    print(f"Filled: {event.symbol} {event.side} {event.quantity} @ {event.price}")

def on_risk(event):
    print(f"Risk alert: {event.data.get('reason', 'unknown')}")

event_bus.subscribe(EventType.FILL, on_fill)
event_bus.subscribe(EventType.RISK, on_risk)
```

### Kill Switch

The risk manager includes an emergency kill switch. When engaged:

- All new orders are rejected
- Existing positions remain open (close manually if needed)
- The kill switch activates automatically when daily loss limit is breached

To manually engage or reset:

```python
risk_manager = ctx.get_risk_manager()

# Engage
risk_manager.kill_switch = True

# Reset (e.g., at start of new trading day)
risk_manager.reset_kill_switch()
risk_manager.reset_daily()
```

## Transitioning from Paper to Live

1. **Paper trade for at least 2 weeks** with the same parameters you plan to use live
2. **Compare paper results** to backtest expectations — if they diverge significantly, investigate
3. **Start with small position sizes** in live — use `quantity` that's 10-25% of your eventual target
4. **Set conservative risk limits** — tighter daily loss limit and drawdown threshold
5. **Monitor actively** for the first few days of live trading
6. **Scale up gradually** once you're confident in the live behavior

## Troubleshooting

### WebSocket Disconnects

The Kraken WebSocket feed may disconnect due to network issues. The `LiveFeed` does not auto-reconnect. If you notice gaps in bar data, restart the process.

### API Rate Limits

Exchanges impose rate limits on API calls:
- **Kraken:** ~15 calls per minute for private endpoints
- **OANDA:** ~120 requests per second

The platform does not automatically throttle requests. If you run multiple strategies or frequent rebalancing, be mindful of rate limits.

### Stale Data

If `run_once()` returns empty results for extended periods, check:
- WebSocket connection is still active
- Exchange is not in maintenance
- Your symbols are valid and actively trading

### Order Rejections

Live orders may be rejected by the exchange for:
- Insufficient balance
- Order size below minimum lot
- Price outside allowed range
- Exchange-side risk checks

Check logs for the specific rejection reason from the exchange API.
