# Forex Trading

This guide covers forex (FX) trading via OANDA. OANDA provides access to major, minor, and exotic currency pairs with streaming quotes and a comprehensive REST API.

## Account Setup

1. Create an OANDA account at [oanda.com](https://www.oanda.com).
2. Choose between a **practice** (demo) account and a **live** account. Practice accounts use simulated money and connect to a separate API endpoint.
3. Navigate to Manage API Access in your account settings.
4. Generate a personal access token (API key).
5. Note your account ID (visible on your account summary page).

## Environment Variables

Set these environment variables before using OANDA functionality:

```bash
export OANDA_API_TOKEN="your-api-token"
export OANDA_ACCOUNT_ID="your-account-id"
export OANDA_ENVIRONMENT="practice"  # or "live"
```

| Variable | Required | Description |
|----------|----------|-------------|
| `OANDA_API_TOKEN` | Yes | Personal access token from OANDA |
| `OANDA_ACCOUNT_ID` | Yes | Your OANDA account ID |
| `OANDA_ENVIRONMENT` | No (default: `practice`) | `"practice"` for demo, `"live"` for real money |

The environment determines the API base URL:
- Practice: `https://api-fxpractice.oanda.com`
- Live: `https://api-fxtrade.oanda.com`

## Supported Pairs

OANDA supports a wide range of forex pairs. Discover available instruments programmatically:

```python
from data.oanda_api import fetch_instruments

instruments = fetch_instruments()
# Returns list of dicts: symbol, oanda_name, type, pip_location, display_precision
```

Common pairs include:

**Majors:** EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD, NZD/USD

**Crosses:** EUR/GBP, EUR/JPY, GBP/JPY, AUD/JPY, EUR/AUD, GBP/AUD

**Exotics:** USD/TRY, USD/ZAR, USD/MXN, EUR/TRY

The system uses slash notation internally (e.g., `EUR/USD`) and converts to OANDA's underscore notation (e.g., `EUR_USD`) automatically.

## Forex Concepts

### Pips

A pip is the smallest standard price movement in a currency pair:
- For most pairs (EUR/USD, GBP/USD): 1 pip = 0.0001 (4th decimal place).
- For JPY pairs (USD/JPY, EUR/JPY): 1 pip = 0.01 (2nd decimal place).

OANDA provides fractional pip pricing (5th/3rd decimal place).

### Lots

Lot sizes in forex:
- **Standard lot**: 100,000 units of the base currency.
- **Mini lot**: 10,000 units.
- **Micro lot**: 1,000 units.

OANDA allows trading in arbitrary unit sizes (no fixed lot requirement). The `lot_size` for OANDA instruments is set to `Decimal("1")`, meaning you can trade as little as 1 unit.

### Spread

The spread is the difference between the bid (sell) and ask (buy) price. Spreads are the primary trading cost in forex and vary by:
- Pair liquidity (majors have the tightest spreads).
- Time of day (spreads widen during low-liquidity sessions).
- Market volatility (spreads widen during news events).

Fetch current bid/ask spreads:

```python
from data.oanda_api import fetch_pricing

prices = fetch_pricing(["EUR/USD", "GBP/USD"])
# {"EUR/USD": {"bid": Decimal("1.08450"), "ask": Decimal("1.08465"),
#              "mid": Decimal("1.08457"), "spread": Decimal("0.00015")}}
```

### Leverage

OANDA provides leverage up to 50:1 for major pairs (varies by jurisdiction). Leverage allows you to control a larger position with less capital, but amplifies both profits and losses.

## Data Ingestion

### Candle Data

Fetch historical candle data from OANDA:

```python
from data.oanda_api import fetch_candles, backfill_candles
from datetime import datetime, timezone

# Single fetch (up to 5000 candles per request)
bars = fetch_candles(
    symbol="EUR/USD",
    timeframe="1h",
    since=datetime(2024, 1, 1, tzinfo=timezone.utc),
    count=5000,
)

# Paginated historical backfill
bars = backfill_candles(
    symbol="EUR/USD",
    timeframe="1h",
    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end=datetime(2024, 12, 31, tzinfo=timezone.utc),
    rate_limit_sleep=0.5,
)
```

**Supported timeframes:**

| Timeframe | OANDA Granularity |
|-----------|------------------|
| `1m` | `M1` |
| `5m` | `M5` |
| `15m` | `M15` |
| `30m` | `M30` |
| `1h` | `H1` |
| `4h` | `H4` |
| `1d` | `D` |
| `1w` | `W` |

Candle data uses mid prices by default. Incomplete candles (the current forming candle) are automatically excluded. The backfill function handles pagination, deduplication, and rate limiting.

## Spread Simulation in Backtests

When backtesting forex strategies, spread simulation is important because spreads represent a real trading cost. Configure the simulated broker with `spread_pips` to apply a realistic spread to every simulated fill.

Key considerations for forex backtests:
- **Weekend gaps**: Forex markets close from Friday evening to Sunday evening. Strategies should account for gap risk.
- **Session awareness**: Liquidity and spreads vary by trading session (London, New York, Tokyo). Session-aware strategies may avoid trading during low-liquidity periods.
- **Pip-based calculations**: Position sizing and stop-loss distances are often calculated in pips rather than absolute price for forex.

## Live Trading

### OandaBroker

The `OandaBroker` class (`lib/broker/oanda.py`) implements the `Broker` ABC for live forex trading via the OANDA v20 REST API. It requires `OANDA_API_TOKEN` and `OANDA_ACCOUNT_ID` to be set.

```python
from broker.oanda import OandaBroker

broker = OandaBroker()
```

#### Order Submission

```python
from models.order import Order, OrderSide, OrderType

order = Order(
    instrument=instrument,
    side=OrderSide.BUY,
    type=OrderType.MARKET,
    quantity=Decimal("10000"),  # 10,000 units (mini lot)
)
submitted = broker.submit_order(order)
```

**Supported order types:**

| OrderType | OANDA Type | Time in Force | Description |
|-----------|-----------|---------------|-------------|
| `MARKET` | `MARKET` | `FOK` (Fill or Kill) | Immediate execution at market price |
| `LIMIT` | `LIMIT` | `GTC` (Good Till Cancelled) | Execute at specified price or better |
| `STOP` | `STOP` | `GTC` | Triggers when stop price is reached |

For `LIMIT` orders, set `order.price`. For `STOP` orders, set `order.stop_price`. Other order types default to market orders.

Market orders use Fill-or-Kill (FOK) time-in-force, meaning the order is either fully filled immediately or cancelled entirely. Limit and stop orders remain active until filled or cancelled (GTC).

#### Position Management

OANDA uses position netting -- all trades in the same instrument are combined into a single net position (long or short):

```python
# Get position for a specific instrument
position = broker.get_position(instrument)
# Position(instrument=..., side=OrderSide.BUY, quantity=Decimal("10000"),
#          entry_price=Decimal("1.08500"), unrealized_pnl=Decimal("15.20"))

# Get all open positions
positions = broker.get_positions()
```

The position side is determined by whether the net units are positive (long) or negative (short). Instrument details are reconstructed with `tick_size=Decimal("0.00001")` for standard forex pairs.

#### Account Information

```python
account = broker.get_account()
# Account(balances={"USD": Decimal("10000")}, equity=Decimal("10150"),
#         margin_used=Decimal("200"), margin_available=Decimal("9950"),
#         unrealized_pnl=Decimal("150"))
```

The account summary provides balance, NAV (equity), margin used, and unrealized PnL from the OANDA v20 account summary endpoint.

#### Order Management

```python
# Cancel a pending order
broker.cancel_order(order_id)

# Get a specific order
order = broker.get_order(order_id)

# Get all pending (open) orders
open_orders = broker.get_open_orders(instrument=instrument)
```

## Risk Considerations

- **Leverage risk**: High leverage magnifies losses. A 100-pip adverse move on EUR/USD with 50:1 leverage on a standard lot produces a $5,000 loss on $2,000 margin.
- **Gap risk**: Weekend gaps and gaps around major economic events can move prices past stop-loss levels, resulting in larger-than-expected losses.
- **Liquidity variation**: Spreads and execution quality vary significantly across trading sessions. The London-New York overlap typically offers the best liquidity for major pairs.
- **Swap/rollover**: Positions held overnight incur swap charges (or credits) based on interest rate differentials between the two currencies. This is separate from futures funding rates.
