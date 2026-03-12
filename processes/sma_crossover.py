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
    symbols: str = "BTC/USD",
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
    import pandas as pd

    from analytics.performance import compute_performance
    from data.state_parquet import ParquetStateStore
    from data.universe import Universe
    from execution.backtest import BacktestContext
    from strategy.sma_crossover import SmaCrossover

    from constants import periods_per_year
    from helpers import market_data_dir, parse_symbols, require_data

    symbol_list = parse_symbols(symbols)
    require_data(env.path, "kraken", symbol_list, timeframe)
    universe = Universe.from_symbols(symbol_list, timeframe)

    start_dt = datetime.fromisoformat(start) if start else datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)

    strategy_params = {
        "fast_period": fast_period,
        "slow_period": slow_period,
        "quantity": quantity,
        "symbols": symbol_list,
    }

    ctx = BacktestContext(
        universe=universe,
        start=start_dt,
        end=end_dt,
        initial_cash=Decimal(initial_cash),
        fee_rate=Decimal(fee_rate),
        slippage_pct=Decimal(slippage_pct),
        max_position_size=Decimal(max_position_size),
        data_dir=market_data_dir(env.path),
    )

    strategy = SmaCrossover(ctx, strategy_params)
    results = ctx.run(strategy)

    metrics = compute_performance(
        equity_curve=results["equity_curve"],
        fills=results["fills"],
        periods_per_year=periods_per_year(timeframe),
    )

    # Save equity curve and fills as Parquet
    pq_store = ParquetStateStore(Path(env.path) / ".persistra")

    if results["equity_curve"]:
        eq_df = pd.DataFrame(
            [(ts, float(eq)) for ts, eq in results["equity_curve"]],
            columns=["timestamp", "equity"],
        )
        eq_path = pq_store.save("backtest_equity_curve", eq_df)
    else:
        eq_path = ""

    if results["fills"]:
        fills_data = []
        for f in results["fills"]:
            fills_data.append({
                "timestamp": f.timestamp,
                "symbol": f.instrument.symbol,
                "side": f.side.value,
                "quantity": float(f.quantity),
                "price": float(f.price),
                "fee": float(f.fee),
                "order_id": f.order_id,
            })
        fills_df = pd.DataFrame(fills_data)
        fills_path = pq_store.save("backtest_fills", fills_df)
    else:
        fills_path = ""

    ns = env.state.ns("backtest")
    ns.set("results", metrics)
    ns.set("equity_curve_path", eq_path)
    ns.set("fills_path", fills_path)
    ns.set("universe", symbols)

    strat_ns = env.state.ns("strategy.sma_crossover")
    strat_ns.set("params", {
        "fast_period": fast_period,
        "slow_period": slow_period,
        "quantity": quantity,
        "symbols": symbols,
        "timeframe": timeframe,
    })
    strat_ns.set("metrics", metrics)

    log.info("=== Backtest Results ===")
    log.info("Universe: %s", symbols)
    log.info("Total Return: %.2f%%", metrics["total_return"] * 100)
    log.info("Sharpe Ratio: %.4f", metrics["sharpe_ratio"])
    log.info("Max Drawdown: %.2f%%", metrics["max_drawdown"] * 100)
    log.info("Num Trades: %d", metrics["num_trades"])
    log.info("Win Rate: %.2f%%", metrics["win_rate"] * 100)
