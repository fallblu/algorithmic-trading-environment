# Futures Trading

This guide covers trading Kraken perpetual futures contracts. Futures provide leveraged exposure to cryptocurrency prices without owning the underlying asset.

## Account Setup

Kraken Futures uses a separate account and API key system from Kraken spot:

1. Create a Kraken Futures account at [futures.kraken.com](https://futures.kraken.com).
2. Navigate to Settings > API Keys.
3. Create a new API key with the permissions you need (trading, account access).
4. Store the API key and secret securely.

## Environment Variables

Set these environment variables before using futures functionality:

```bash
export KRAKEN_FUTURES_API_KEY="your-api-key"
export KRAKEN_FUTURES_API_SECRET="your-api-secret"
```

Both are required for any authenticated operation (order placement, position queries, account information). The data API (OHLCV fetching, instrument listing) does not require authentication.

## Supported Contracts

The system maps internal symbol names to Kraken Futures API symbols:

| Internal Symbol | Kraken Symbol | Description |
|----------------|---------------|-------------|
| `BTC-PERP` | `PF_XBTUSD` | Bitcoin perpetual |
| `ETH-PERP` | `PF_ETHUSD` | Ethereum perpetual |
| `SOL-PERP` | `PF_SOLUSD` | Solana perpetual |
| `XRP-PERP` | `PF_XRPUSD` | XRP perpetual |
| `DOGE-PERP` | `PF_DOGEUSD` | Dogecoin perpetual |
| `ADA-PERP` | `PF_ADAUSD` | Cardano perpetual |
| `AVAX-PERP` | `PF_AVAXUSD` | Avalanche perpetual |
| `DOT-PERP` | `PF_DOTUSD` | Polkadot perpetual |
| `LINK-PERP` | `PF_LINKUSD` | Chainlink perpetual |

Additional instruments can be discovered via:

```python
from data.kraken_futures_api import fetch_instruments

instruments = fetch_instruments()
# Returns list of dicts with: symbol, kraken_symbol, type, tick_size, max_leverage
```

Only instruments of type `"flexible_futures"` (perpetuals) are included.

## Futures Concepts

### Perpetual Contracts

Perpetual contracts (perps) have no expiry date, unlike traditional futures. You can hold a position indefinitely, but you pay or receive funding every 8 hours.

### Funding Rates

Funding rates keep the perpetual price anchored to the spot index price:

- When the perp trades above spot (contango), longs pay shorts.
- When the perp trades below spot (backwardation), shorts pay longs.
- Funding is settled every 8 hours.

Fetch the current funding rate:

```python
from data.kraken_futures_api import fetch_funding_rate

fr = fetch_funding_rate("BTC-PERP")
# FundingRate(instrument_symbol="BTC-PERP", timestamp=..., rate=Decimal("0.0001"), next_funding_time=...)
```

Over time, funding can significantly drag on returns for directional positions. A 0.01% funding rate every 8 hours compounds to roughly 10% per year.

### Margin and Leverage

- **Initial margin**: The collateral required to open a position. At 10x leverage, opening a $10,000 position requires $1,000 initial margin.
- **Maintenance margin**: The minimum collateral to keep a position open. If equity drops below this, liquidation begins.
- **Leverage**: Multiplies both gains and losses. Kraken Futures supports up to 50x leverage on some contracts.

### Liquidation

If unrealized losses cause your equity to fall below the maintenance margin, the exchange liquidates your position to prevent further losses. Liquidation typically occurs at a worse price than the mark price due to forced selling.

## Data Ingestion

### OHLCV Data

Fetch historical candle data from Kraken Futures:

```python
from data.kraken_futures_api import fetch_ohlcv_futures, backfill_ohlcv_futures
from datetime import datetime, timezone

# Single fetch
bars = fetch_ohlcv_futures("BTC-PERP", timeframe="1h", since=since_dt)

# Paginated historical backfill
bars = backfill_ohlcv_futures(
    symbol="BTC-PERP",
    timeframe="1h",
    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end=datetime(2024, 12, 31, tzinfo=timezone.utc),
    rate_limit_sleep=1.0,  # Seconds between API requests
)
```

**Supported timeframes:**

| Timeframe | Resolution |
|-----------|-----------|
| `1m` | 1 minute |
| `5m` | 5 minutes |
| `15m` | 15 minutes |
| `30m` | 30 minutes |
| `1h` | 1 hour |
| `4h` | 4 hours |
| `1d` | 1 day |
| `1w` | 1 week |

The backfill function handles pagination, deduplication, and rate limiting automatically. It uses the `/api/charts/v1/trade/{symbol}/{resolution}` endpoint.

### Funding Rate History

Use `fetch_funding_rate()` to get the current rate. For historical funding rates, ingest and store them via the data ingestion process.

## Backtesting with Futures

When backtesting futures strategies, configure the simulated broker for margin mode:

- **`margin_mode=True`**: Enables margin accounting and leverage.
- **Funding rate simulation**: If funding rate data is available, the backtest simulates periodic funding charges/credits.
- **Liquidation simulation**: The backtest engine simulates forced liquidation if equity drops below the maintenance margin.

Use `FuturesInstrument` (instead of `Instrument`) for futures backtests. It carries additional fields:

```python
from models.instrument import FuturesInstrument

instrument = FuturesInstrument(
    symbol="BTC-PERP",
    base="BTC",
    quote="USD",
    exchange="kraken_futures",
    asset_class="crypto_futures",
    tick_size=Decimal("0.5"),
    lot_size=Decimal("0.001"),
    min_notional=Decimal("5"),
    contract_type="perpetual",
    max_leverage=Decimal("50"),
    initial_margin_rate=Decimal("0.02"),      # 2% = 50x max leverage
    maintenance_margin_rate=Decimal("0.01"),  # 1%
    funding_interval_hours=8,
    expiry=None,  # perpetuals have no expiry
)
```

## Live Trading

### KrakenFuturesBroker

The `KrakenFuturesBroker` class (`lib/broker/kraken_futures.py`) implements the `Broker` ABC for live futures trading. It requires `KRAKEN_FUTURES_API_KEY` and `KRAKEN_FUTURES_API_SECRET` to be set.

```python
from broker.kraken_futures import KrakenFuturesBroker

broker = KrakenFuturesBroker()
```

#### Order Submission

```python
from models.order import Order, OrderSide, OrderType

order = Order(
    instrument=instrument,
    side=OrderSide.BUY,
    type=OrderType.MARKET,
    quantity=Decimal("0.01"),
)
submitted = broker.submit_order(order)
```

**Supported order types:**

| OrderType | Kraken Type | Description |
|-----------|------------|-------------|
| `MARKET` | `mkt` | Immediate execution at market price |
| `LIMIT` | `lmt` | Execute at specified price or better |
| `STOP` | `stp` | Triggers a market order when stop price is reached |
| `STOP_LIMIT` | `take_profit` | Take-profit order |

For `LIMIT` and `STOP_LIMIT` orders, set `order.price`. For `STOP` and `STOP_LIMIT` orders, set `order.stop_price`.

#### Position Management

```python
# Get position for a specific instrument
position = broker.get_position(instrument)
# Position(instrument=..., side=OrderSide.BUY, quantity=Decimal("0.01"),
#          entry_price=Decimal("42000"), unrealized_pnl=Decimal("50"))

# Get all open positions
positions = broker.get_positions()
```

#### Leverage

```python
broker.set_leverage(instrument, leverage=10)
```

This calls the Kraken Futures leverage preferences endpoint to set the maximum leverage for a contract.

#### Account Information

```python
account = broker.get_account()
# Account(balances={"USD": Decimal("5000")}, equity=Decimal("5200"),
#         margin_used=Decimal("1000"), margin_available=Decimal("4200"),
#         unrealized_pnl=Decimal("200"))
```

The account endpoint returns the flex (or cash) account values including portfolio value, initial margin, unrealized funding, and available margin.

#### Order Management

```python
# Cancel an order
broker.cancel_order(order_id)

# Get a specific order
order = broker.get_order(order_id)

# Get all open orders (optionally filtered by instrument)
open_orders = broker.get_open_orders(instrument=instrument)
```

## Risk Considerations

- **Liquidation risk**: High leverage amplifies losses. At 50x, a 2% adverse move wipes out your margin. Use conservative leverage (2-5x) unless you have a specific reason for more.
- **Funding rate drag**: Persistent positive funding (common in bull markets) erodes long positions over time. Factor funding into your strategy's expected returns.
- **Basis risk**: The perpetual price can deviate from spot, especially during volatile periods. This affects PnL calculations and hedge effectiveness.
- **API rate limits**: Kraken Futures enforces rate limits. The data client handles 429 responses with a `Retry-After` header, but aggressive polling can still cause issues.
