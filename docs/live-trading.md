# Live Trading Guide

## Overview

Live trading executes real orders on the Kraken exchange using the same strategy and data feed as paper trading. The only differences are:

- Orders are submitted to Kraken via authenticated REST API (real money)
- Fills are determined by the exchange (real market conditions)
- Account balances come from Kraken (no simulated broker)

The system supports trading multiple symbols simultaneously.

**Start with paper trading first.** Validate your strategy, parameters, and risk limits before going live.

## Prerequisites

### 1. Funded Kraken Account

Your Kraken account needs a USD balance to trade spot pairs. Deposit funds via the Kraken web interface.

### 2. API Keys

Create an API key at [https://www.kraken.com/u/security/api](https://www.kraken.com/u/security/api).

**Required permissions:**
- Query funds
- Create & modify orders
- Query open orders & trades
- Cancel & close orders

**Recommended restrictions:**
- Enable IP whitelist if running from a fixed server
- Do not enable withdrawal permissions

### 3. Environment Variables

Add your credentials to your shell profile:

```bash
echo 'export KRAKEN_API_KEY="your-api-key"' >> ~/.bashrc
echo 'export KRAKEN_API_SECRET="your-base64-secret"' >> ~/.bashrc
source ~/.bashrc
```

Never store credentials in code, config files, or git repositories.

### 4. Verify API Access

```bash
cd ~/trading
PYTHONPATH=lib python -c "
from broker.kraken import KrakenBroker
broker = KrakenBroker()
account = broker.get_account()
print(f'Equity: {account.equity}')
print(f'Balances: {account.balances}')
"
```

## Quick Start

```bash
# Start with small quantities across multiple symbols
persistra process start sma_crossover_live \
  -p mode=live \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1m \
  -p quantity=0.0001 \
  -p max_position_size=0.001

# Monitor
persistra process logs sma_crossover_live-1
persistra state get live.account

# Stop
persistra process stop sma_crossover_live-1
```

## Parameters

```bash
persistra process start sma_crossover_live \
  -p mode=live \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1m \
  -p fast_period=10 \
  -p slow_period=30 \
  -p quantity=0.0001 \
  -p max_position_size=0.001
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `paper` | Must be `live` for real execution |
| `symbols` | `BTC/USD` | Comma-separated trading pairs |
| `timeframe` | `1m` | Bar period |
| `fast_period` | `10` | Fast SMA window (bars) |
| `slow_period` | `30` | Slow SMA window (bars) |
| `quantity` | `0.01` | Trade size per signal per symbol (base asset) |
| `max_position_size` | `1.0` | Risk limit: max position per instrument (base asset) |

**Note:** `initial_cash`, `fee_rate`, and `slippage_pct` are ignored in live mode — the real exchange balance, fees, and fills apply.

### Recommended Starting Values

| Parameter | Conservative | Description |
|-----------|-------------|-------------|
| `quantity` | `0.0001` | ~$7 per trade at $70k BTC |
| `max_position_size` | `0.001` | ~$70 max exposure per symbol |
| `timeframe` | `1m` | Fast feedback loop |

Scale up gradually once you confirm the system behaves correctly.

## How It Works

### Architecture

```
Kraken WebSocket v2 (public, real-time bars for all symbols)
        │
        ▼
   LiveFeed (background thread, batch subscribe)
        │
        ▼
   PricePanel (rolling MultiIndex DataFrame)
        │
        ▼
   Strategy.on_bar(panel) ──→ [Order per symbol]
                                    │
                                    ▼
                             RiskManager (pre-trade checks per instrument)
                                    │
                                    ▼
                             KrakenBroker (authenticated REST)
                                    │
                              ┌─────┴─────┐
                              ▼           ▼
                          AddOrder    QueryOrders ← Kraken Exchange
```

### Execution Flow (per tick, every 10 seconds)

1. **Drain bar queue**: Read all completed bars from the WebSocket for all symbols
2. **Group by timestamp**: Bars at the same timestamp form a group
3. **For each group**:
   - Check open orders: Query Kraken for status updates
   - Append bars to PricePanel
   - Call strategy: `strategy.on_bar(panel)` generates buy/sell signals for any symbol
   - Risk check: Validate each order against per-instrument position limits
   - Submit to Kraken: `POST /0/private/AddOrder` for approved orders
4. **Persist state**: Write account state and last tick timestamp

### Order Submission

When the strategy generates a market buy order for a specific symbol:

```
Strategy → Order(BUY, MARKET, 0.0001 BTC/USD) → RiskManager.check() → KrakenBroker.submit_order()
  → POST /0/private/AddOrder {pair: XBTUSD, type: buy, ordertype: market, volume: 0.0001}
  → Kraken returns txid: "OXXXX-XXXXX-XXXXXX"
  → order.metadata["kraken_txid"] = txid
```

### Supported Order Types

| Type | Kraken Type | Behavior |
|------|-------------|----------|
| MARKET | `market` | Fills immediately at best price |
| LIMIT | `limit` | Fills when price reaches limit |
| STOP | `stop-loss` | Triggers market order when stop price hit |
| STOP_LIMIT | `stop-loss-limit` | Triggers limit order when stop price hit |

The SMA crossover strategy uses market orders only.

### Position Tracking

Kraken spot trading has no native "position" concept. The KrakenBroker derives position from account balances:

- `get_position(BTC/USD)` → queries Kraken balance → checks `XXBT` key → returns Position if nonzero
- This means any BTC in your account (from manual trades, deposits, etc.) appears as a position
- Each symbol's position is tracked independently

## Monitoring

### Real-Time Logs

```bash
persistra process logs sma_crossover_live-1
```

Expected log output:

```
[INFO] data.live: WebSocket connected to wss://ws.kraken.com/v2
[INFO] data.live: Subscribed to ohlc ['BTC/USD', 'ETH/USD'] interval=1
[INFO] execution.live: Warming up strategy with 42 bar groups across 2 symbols
[INFO] sma_crossover_live: LIVE trading initialized for BTC/USD,ETH/USD 1m
[INFO] strategy.sma_crossover: BUY BTC/USD at 2026-03-11 12:00:00: fast_sma=69500 > slow_sma=69480
[INFO] execution.live: LIVE order submitted: BUY MARKET BTC/USD qty=0.0001
[INFO] strategy.sma_crossover: BUY ETH/USD at 2026-03-11 12:00:00: fast_sma=3800 > slow_sma=3790
[INFO] execution.live: LIVE order submitted: BUY MARKET ETH/USD qty=0.0001
```

### State Queries

```bash
# Last tick time
persistra state get live.last_tick

# Account snapshot (balances, equity, margin)
persistra state get live.account

# Process status
persistra process status
```

### Verify Orders on Kraken

Always cross-check with the Kraken web interface or app. The system logs Kraken transaction IDs (`kraken_txid`) for every order submitted.

## Risk Management

### Built-in Risk Checks

Every order passes through the `RiskManager` before submission:

1. **Kill switch**: If active, all orders are rejected
2. **Max position size**: If the resulting position for that instrument would exceed `max_position_size`, the order is rejected
3. **Max order value**: If the order notional exceeds $100,000, the order is rejected

### Risk Monitor Daemon

Run alongside your trading daemon:

```bash
persistra process start risk_monitor
```

The risk monitor checks every 10 seconds:
- `daily_pnl < daily_loss_limit` → activates kill switch
- `max_drawdown > max_drawdown_limit` → activates kill switch

Configure:

```bash
persistra state set risk.daily_loss_limit -100
persistra state set risk.max_drawdown_limit 0.05
```

### Manual Kill Switch

Halt all trading immediately:

```bash
persistra state set risk.kill_switch true
```

Re-enable:

```bash
persistra state set risk.kill_switch false
```

### Emergency Stop

```bash
persistra process stop sma_crossover_live-1
```

This stops the daemon and closes the WebSocket connection. It does **not** cancel open orders on Kraken — cancel those manually via the Kraken interface if needed.

## Differences from Paper Trading

| Aspect | Paper | Live |
|--------|-------|------|
| Data feed | WebSocket (real) | WebSocket (real) |
| Order execution | SimulatedBroker | Kraken REST API |
| Fills | Simulated (bar open ± slippage) | Real exchange fills |
| Fees | Configurable (default 0.26%) | Kraken's actual fee schedule |
| Position tracking | Internal state per symbol | Derived from Kraken balance per symbol |
| Account balance | Simulated ($10,000 default) | Real Kraken balance |
| API keys needed | No | Yes |
| Risk of loss | None | Real |

## Kraken API Rate Limits

Kraken has rate limits on private API endpoints. The system makes REST calls when:

- Submitting orders (~1 call per signal per symbol)
- Checking order status (~1 call per open order per tick)
- The RiskManager calls `get_position()` for pre-trade checks (~1 call per order)

At the 10-second daemon interval with the SMA crossover strategy (infrequent signals), this is well within Kraken's limits even with multiple symbols. If you add more frequent strategies or many symbols, monitor for `429` errors in logs.

## Stopping

```bash
# Graceful stop
persistra process stop sma_crossover_live-1

# Check it's stopped
persistra process status
```

After stopping:
- The WebSocket connection is closed
- No new orders will be submitted
- Open orders on Kraken remain active (cancel manually if needed)
- State is persisted (last tick, account snapshot)

## Troubleshooting

**"KrakenAuthError: KRAKEN_API_KEY and KRAKEN_API_SECRET environment variables must be set"** — Credentials not in environment. Check `echo $KRAKEN_API_KEY`.

**"Kraken API error: ['EGeneral:Permission denied']"** — API key lacks required permissions. Enable "Query funds", "Create & modify orders", and "Query open orders & trades" in Kraken API settings.

**"Kraken API error: ['EOrder:Insufficient funds']"** — Account balance too low for the order. Reduce `quantity` or deposit more funds.

**"Kraken API error: ['EGeneral:Invalid arguments:volume']"** — Order quantity below Kraken's minimum. BTC/USD minimum is 0.0001 BTC.

**"Order rejected by risk manager"** — Position for that instrument would exceed `max_position_size`. Increase the limit or wait for the current position to close.

**"Failed to submit order to Kraken"** — Network error or Kraken outage. The error is logged and the daemon continues on the next tick. No partial state is left.

**WebSocket disconnects** — The feed reconnects automatically with exponential backoff (5s → 10s → 20s → ... → 60s max). Check logs for reconnection messages.

## Multi-Exchange Live Trading

The live trading system supports multiple exchanges. The exchange is auto-detected from the universe instruments.

### Kraken Futures Live Trading

```bash
persistra process start sma_crossover_live \
  -p mode=live \
  -p symbols=BTC-PERP,ETH-PERP \
  -p exchange=kraken_futures \
  -p timeframe=1m \
  -p quantity=0.001
```

Requires `KRAKEN_FUTURES_API_KEY` and `KRAKEN_FUTURES_API_SECRET` environment variables. Uses `KrakenFuturesBroker` for order execution and `LiveFuturesFeed` for WebSocket data. See the [Futures Trading Guide](futures-trading.md).

### OANDA Forex Live Trading

```bash
persistra process start sma_crossover_live \
  -p mode=live \
  -p symbols=EUR/USD,GBP/USD \
  -p exchange=oanda \
  -p timeframe=1m \
  -p quantity=100
```

Requires `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, and `OANDA_ENVIRONMENT` environment variables. Uses `OandaBroker` for order execution and `LiveOandaFeed` for streaming data. See the [Forex Trading Guide](forex-trading.md).

## Web Dashboard

View live positions, equity, signals, and account state in the interactive web dashboard:

```bash
persistra process start dashboard -p port=8050
```

Then open `http://localhost:8050` in your browser. See the [Dashboard Guide](dashboard.md).

## Checklist Before Going Live

- [ ] Paper traded the same strategy/parameters/symbols for at least several days
- [ ] Reviewed paper trading logs — signals and fills make sense for all symbols
- [ ] Exchange account funded (Kraken, Kraken Futures, or OANDA)
- [ ] API key created with correct permissions (no withdrawal permission)
- [ ] API credentials in environment variables
- [ ] Broker connection verified (e.g., `KrakenBroker().get_account()`)
- [ ] Starting with minimal `quantity`
- [ ] `max_position_size` set conservatively per instrument
- [ ] Risk monitor running
- [ ] Kill switch state is `false`: `persistra state get risk.kill_switch`
