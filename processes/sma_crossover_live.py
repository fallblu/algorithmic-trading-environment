"""SMA Crossover live process — daemon for paper and live trading.

Polls every 10s for new bars from the Kraken WebSocket feed.
On first tick: creates context, subscribes, warms up indicators.
On subsequent ticks: calls ctx.run_once() and persists state.

Usage:
    persistra process start sma_crossover_live -p mode=paper -p symbol=BTC/USD -p timeframe=1m
    persistra process start sma_crossover_live -p mode=live -p symbol=BTC/USD -p timeframe=1m
"""

import atexit
import logging
from datetime import datetime, timezone
from decimal import Decimal

from persistra import process

log = logging.getLogger(__name__)

# Module-level state persists between daemon ticks
_ctx = None
_strategy = None
_initialized = False


@process("daemon", interval="10s")
def run(
    env,
    mode: str = "paper",
    symbol: str = "BTC/USD",
    timeframe: str = "1m",
    fast_period: int = 10,
    slow_period: int = 30,
    quantity: str = "0.01",
    initial_cash: str = "10000",
    fee_rate: str = "0.0026",
    slippage_pct: str = "0.0001",
    max_position_size: str = "1.0",
):
    """Run the SMA crossover strategy in paper or live mode."""
    global _ctx, _strategy, _initialized

    from models.instrument import Instrument
    from strategy.sma_crossover import SmaCrossover

    instrument = Instrument(
        symbol=symbol,
        base=symbol.split("/")[0],
        quote=symbol.split("/")[1],
        exchange="kraken",
        asset_class="crypto",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.00001"),
        min_notional=Decimal("5"),
    )

    strategy_params = {
        "fast_period": fast_period,
        "slow_period": slow_period,
        "quantity": quantity,
        "_instrument": instrument,
    }

    if not _initialized:
        if mode == "paper":
            from execution.paper import PaperContext
            _ctx = PaperContext(
                initial_cash=Decimal(initial_cash),
                fee_rate=Decimal(fee_rate),
                slippage_pct=Decimal(slippage_pct),
                max_position_size=Decimal(max_position_size),
            )
        elif mode == "live":
            from execution.live import LiveContext
            _ctx = LiveContext(
                max_position_size=Decimal(max_position_size),
            )
        else:
            raise ValueError(f"Unknown mode: {mode}. Use 'paper' or 'live'.")

        _strategy = SmaCrossover(_ctx, strategy_params)

        _ctx.subscribe(instrument, timeframe)
        _ctx.warmup(_strategy, instrument, timeframe,
                     warmup_bars=slow_period + 10)

        atexit.register(_ctx.shutdown)
        _initialized = True
        log.info("%s trading initialized for %s %s", mode.upper(), symbol, timeframe)

    try:
        result = _ctx.run_once(_strategy, instrument)

        ns = env.state.ns(mode)
        ns.set("last_tick", datetime.now(timezone.utc).isoformat())

        if mode == "paper":
            ns.set("equity", str(result["equity"]))
            ns.set("bars_processed", result["bars_processed"])
            ns.set("fills", result["fills"])

            strat_ns = env.state.ns("strategy.sma_crossover")
            strat_ns.set("mode", mode)
            strat_ns.set("equity", str(result["equity"]))

            if result["bars_processed"] > 0:
                log.info(
                    "Tick: %d bars, %d fills, equity=%s",
                    result["bars_processed"], result["fills"], result["equity"],
                )
        elif mode == "live":
            ns.set("account", result.get("account", {}))

            if result["bars_processed"] > 0:
                log.info("Tick: %d bars processed", result["bars_processed"])

    except Exception:
        log.exception("Error in %s trading tick", mode)
