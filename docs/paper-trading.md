# Paper Trading Guide

## Overview

Paper trading uses real-time market data from the Kraken WebSocket feed but executes orders through a simulated broker. This lets you validate strategy behavior against live market conditions without risking real money. No API keys are required — the WebSocket feed is public. The system supports trading multiple symbols simultaneously.

## Quick Start

```bash
# Start paper trading BTC/USD and ETH/USD with 1-minute bars
persistra process start sma_crossover_live \
  -p mode=paper \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1m

# Monitor
persistra state get paper.equity
persistra process logs sma_crossover_live-1

# Stop
persistra process stop sma_crossover_live-1
```

## How It Works

### Architecture

```
Kraken WebSocket v2 (wss://ws.kraken.com/v2)
        │
        ▼
   LiveFeed (background thread, batch subscribe)
        │ completed bars via thread-safe queue
        ▼
   PricePanel (rolling MultiIndex DataFrame)
        │
        ▼
   Strategy.on_bar(panel) ←→ SimulatedBroker
        │                         │
        ▼                         ▼
   Order generation          Fill simulation
                                  │
                                  ▼
                          Persistra State (equity, fills, positions)
```

### Daemon Lifecycle

The `sma_crossover_live` process runs as a daemon with a **10-second polling interval**:

1. **First tick** (initialization):
   - Builds a `Universe` from the comma-separated `symbols` parameter
   - Creates PaperContext (LiveFeed + SimulatedBroker + PricePanel)
   - Connects to Kraken WebSocket and batch-subscribes to OHLC bars for all symbols
   - Fetches historical bars via REST API for all symbols to warm up the strategy's SMA indicators
   - Module-level state persists between ticks

2. **Subsequent ticks** (every 10 seconds):
   - Drains all completed bars from the WebSocket queue
   - Groups bars by timestamp
   - For each timestamp group: fills pending orders → appends to PricePanel → calls strategy with panel → risk checks → submits new orders
   - Persists equity and trade state

3. **Shutdown** (on `persistra process stop`):
   - WebSocket connection closed gracefully
   - Final state persisted

### Bar Completion Detection

The WebSocket streams in-progress candle updates every few seconds. A bar is only enqueued when the next candle begins (detected by the `interval_begin` field changing). This means:

- For **1m bars**: A completed bar arrives within seconds of the minute boundary. The 10-second daemon interval picks it up promptly.
- For **1h bars**: Same mechanism, but you wait up to ~60 minutes for each signal. The daemon still polls every 10 seconds.

With multiple symbols, bars complete independently — the PricePanel's inner-join ensures the strategy only sees timestamps where all symbols have data.

## Parameters

```bash
persistra process start sma_crossover_live \
  -p mode=paper \
  -p symbols=BTC/USD,ETH/USD \
  -p timeframe=1m \
  -p fast_period=10 \
  -p slow_period=30 \
  -p quantity=0.01 \
  -p initial_cash=10000 \
  -p fee_rate=0.0026 \
  -p slippage_pct=0.0001 \
  -p max_position_size=1.0
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `paper` | Must be `paper` for simulated execution |
| `symbols` | `BTC/USD` | Comma-separated trading pairs |
| `timeframe` | `1m` | Bar period (1m, 5m, 15m, 30m, 1h, 4h, 1d) |
| `fast_period` | `10` | Fast SMA window (bars) |
| `slow_period` | `30` | Slow SMA window (bars) |
| `quantity` | `0.01` | Trade size per signal per symbol (base asset) |
| `initial_cash` | `10000` | Starting simulated USD balance |
| `fee_rate` | `0.0026` | Simulated taker fee (0.26%) |
| `slippage_pct` | `0.0001` | Simulated slippage (0.01%) |
| `max_position_size` | `1.0` | Risk limit: max position per instrument (base asset) |

### Timeframe Considerations

| Timeframe | Bars/day | Signals/day (approx) | Use Case |
|-----------|----------|---------------------|----------|
| 1m | 1,440 | Many | Fast iteration, noisy |
| 5m | 288 | Moderate | Good balance |
| 15m | 96 | Few | Less noise |
| 1h | 24 | Rare | Swing trading |

The daemon always polls every 10 seconds regardless of timeframe, so there's no latency issue with any choice.

## Monitoring

### Check Current State

```bash
# Current equity
persistra state get paper.equity

# Last execution time
persistra state get paper.last_tick

# Bars processed in last tick
persistra state get paper.bars_processed

# Fills in last tick
persistra state get paper.fills

# Strategy mode and equity
persistra state get strategy.sma_crossover.mode
persistra state get strategy.sma_crossover.equity
```

### View Logs

```bash
# Live logs (shows signals, fills, errors)
persistra process logs sma_crossover_live-1

# Example log output:
# 2026-03-11 10:40:25 [INFO] execution.paper: Warming up strategy with 42 bar groups across 2 symbols
# 2026-03-11 10:40:25 [INFO] sma_crossover_live: PAPER trading initialized for BTC/USD,ETH/USD 1m
# 2026-03-11 10:41:05 [INFO] sma_crossover_live: Tick: 1 bars, 0 fills, equity=10000
# 2026-03-11 10:42:15 [INFO] strategy.sma_crossover: BUY BTC/USD at ...: fast_sma=69500 > slow_sma=69480
# 2026-03-11 10:42:15 [INFO] execution.paper: Order submitted: BUY MARKET BTC/USD qty=0.01
# 2026-03-11 10:43:05 [INFO] execution.paper: Fill: BUY 0.01 BTC/USD @ 69520.5
# 2026-03-11 10:45:30 [INFO] strategy.sma_crossover: BUY ETH/USD at ...: fast_sma=3800 > slow_sma=3790
```

### Check Process Status

```bash
persistra process status
```

## Warmup

On first tick, the strategy is warmed up with `slow_period + 10` historical bars for ALL symbols, fetched via the Kraken REST API. During warmup:

- Bars are grouped by timestamp and appended to the PricePanel
- `strategy.on_bar(panel)` is called to populate the SMA windows for all symbols
- Orders generated during warmup are **discarded** (not submitted to the broker)
- After warmup, the strategy has enough history to generate valid signals immediately when live bars arrive

## Simulated Execution

Paper trading uses the same `SimulatedBroker` as backtesting:

- **Market orders** fill at the bar's open price ± slippage
- **Fees** are deducted from the simulated USD balance
- **Position tracking** uses volume-weighted average entry price, tracked per symbol
- **Equity** = cash + unrealized P&L of all open positions

Multi-symbol bar groups are processed atomically — all pending orders for all symbols are filled, then equity is updated once via `update_equity_all()`.

## Running Alongside Risk Monitor

Start the risk monitor daemon to watch for extreme conditions:

```bash
persistra process start risk_monitor
```

The risk monitor checks every 10 seconds:
- If `daily_pnl` drops below the daily loss limit (default: -$500), it activates the kill switch
- If `max_drawdown` exceeds the limit (default: 20%), it activates the kill switch
- When the kill switch is active, the `RiskManager` rejects all new orders

Configure limits via state:

```bash
persistra state set risk.daily_loss_limit -200
persistra state set risk.max_drawdown_limit 0.10
```

## Stopping and Restarting

```bash
# Stop the daemon
persistra process stop sma_crossover_live-1

# Restart with same parameters
persistra process restart sma_crossover_live-1

# Start fresh with different parameters or symbols
persistra process start sma_crossover_live \
  -p mode=paper \
  -p symbols=BTC/USD,ETH/USD,SOL/USD \
  -p fast_period=5 \
  -p slow_period=20
```

Restarting re-initializes the context, re-connects the WebSocket, and re-warms the strategy. Paper trading state (equity, positions) does **not** carry over between restarts — each start begins fresh with `initial_cash`.

## Multi-Exchange Paper Trading

The paper trading system supports multiple exchanges. The exchange is auto-detected from the universe instruments, or can be set explicitly.

### Futures Paper Trading

```bash
persistra process start sma_crossover_live \
  -p mode=paper \
  -p symbols=BTC-PERP,ETH-PERP \
  -p exchange=kraken_futures \
  -p timeframe=1m
```

Uses `LiveFuturesFeed` for real-time Kraken Futures WebSocket data with `SimulatedBroker(margin_mode=True)` for margin simulation. See the [Futures Trading Guide](futures-trading.md) for details.

### Forex Paper Trading

```bash
persistra process start sma_crossover_live \
  -p mode=paper \
  -p symbols=EUR/USD,GBP/USD \
  -p exchange=oanda \
  -p timeframe=1m
```

Uses `LiveOandaFeed` for OANDA streaming data with `SimulatedBroker(spread_pips=...)` for spread simulation. See the [Forex Trading Guide](forex-trading.md) for details.

## Transitioning to Live

Once you're satisfied with paper trading results:

1. Fund your exchange account
2. Set API credentials (see the [Live Trading Guide](live-trading.md))
3. Change `mode=paper` to `mode=live` — the strategy, parameters, symbols, and data feed are identical

```bash
# Paper
persistra process start sma_crossover_live -p mode=paper -p symbols=BTC/USD,ETH/USD -p timeframe=1m

# Live (same strategy, real execution)
persistra process start sma_crossover_live -p mode=live -p symbols=BTC/USD,ETH/USD -p timeframe=1m -p quantity=0.0001
```

## Troubleshooting

**WebSocket connection not confirmed within 10s** — Network issue or Kraken downtime. The feed will retry with exponential backoff (5s → 10s → 20s → ... → 60s max). Check logs.

**No bars processed** — The daemon may be polling between bar boundaries. Wait at least one full bar period (e.g., 60 seconds for 1m bars).

**"Order rejected by risk manager"** — The order would exceed `max_position_size` for that instrument. Either increase the limit or reduce `quantity`.

**Process shows "failed"** — Check logs for the full traceback:

```bash
persistra process logs sma_crossover_live-1
```
