"""SMA Crossover strategy process — backtest mode (job).

For paper/live trading, use sma_crossover_live instead.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)


@process("job")
def run(
    env,
    symbol: str = "BTC/USD",
    timeframe: str = "1h",
    fast_period: int = 10,
    slow_period: int = 30,
    quantity: str = "0.01",
    initial_cash: str = "10000",
    fee_rate: str = "0.0026",
    slippage_pct: str = "0.0001",
    max_position_size: str = "1.0",
    start: str = "",
    end: str = "",
):
    """Run the SMA crossover strategy in backtest mode."""
    from analytics.performance import compute_performance
    from execution.backtest import BacktestContext
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

    start_dt = datetime.fromisoformat(start) if start else datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)

    strategy_params = {
        "fast_period": fast_period,
        "slow_period": slow_period,
        "quantity": quantity,
        "_instrument": instrument,
    }

    ctx = BacktestContext(
        instrument=instrument,
        timeframe=timeframe,
        start=start_dt,
        end=end_dt,
        initial_cash=Decimal(initial_cash),
        fee_rate=Decimal(fee_rate),
        slippage_pct=Decimal(slippage_pct),
        max_position_size=Decimal(max_position_size),
        data_dir=Path(env.path) / ".persistra" / "market_data",
    )

    strategy = SmaCrossover(ctx, strategy_params)
    results = ctx.run(strategy)

    metrics = compute_performance(
        equity_curve=results["equity_curve"],
        fills=results["fills"],
    )

    ns = env.state.ns("backtest")
    ns.set("results", metrics)
    ns.set("equity_curve", [
        {"timestamp": ts.isoformat(), "equity": str(eq)}
        for ts, eq in results["equity_curve"]
    ])

    strat_ns = env.state.ns("strategy.sma_crossover")
    strat_ns.set("params", {
        "fast_period": fast_period,
        "slow_period": slow_period,
        "quantity": quantity,
        "symbol": symbol,
        "timeframe": timeframe,
    })
    strat_ns.set("metrics", metrics)

    log.info("=== Backtest Results ===")
    log.info("Total Return: %.2f%%", metrics["total_return"] * 100)
    log.info("Sharpe Ratio: %.4f", metrics["sharpe_ratio"])
    log.info("Max Drawdown: %.2f%%", metrics["max_drawdown"] * 100)
    log.info("Num Trades: %d", metrics["num_trades"])
    log.info("Win Rate: %.2f%%", metrics["win_rate"] * 100)
