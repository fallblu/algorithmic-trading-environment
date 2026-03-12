"""Backtest process — run any registered strategy in backtest mode (job).

For paper/live trading, use live_trader instead.

Usage:
    persistra process run backtest -p strategy=sma_crossover -p symbols=BTC/USD
    persistra process run backtest -p strategy=macd_trend -p params='{"fast_period":12}'
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)


@process("job")
def run(
    env,
    strategy: str = "sma_crossover",
    symbols: str = "BTC/USD",
    timeframe: str = "1h",
    exchange: str = "kraken",
    params: str = "{}",
    initial_cash: str = "10000",
    max_position_size: str = "1.0",
    start: str = "",
    end: str = "",
):
    """Run a registered strategy in backtest mode.

    Args:
        strategy: Registered strategy name (e.g. sma_crossover, macd_trend).
        symbols: Comma-separated symbol list.
        timeframe: Bar timeframe.
        exchange: Exchange name for config defaults and data.
        params: JSON string of strategy-specific parameters.
        initial_cash: Starting equity.
        max_position_size: Max position size as fraction of equity.
        start: Start date ISO format.
        end: End date ISO format.
    """
    import pandas as pd

    from analytics.performance import compute_performance
    from config import get_exchange_config
    from constants import periods_per_year
    from data.state_parquet import ParquetStateStore
    from data.universe import Universe
    from execution.backtest import BacktestContext
    from helpers import market_data_dir, parse_symbols, require_data
    from strategy.registry import get_strategy, load_all_strategies

    load_all_strategies()

    strategy_class = get_strategy(strategy)
    symbol_list = parse_symbols(symbols)
    require_data(env.path, exchange, symbol_list, timeframe)
    universe = Universe.from_symbols(symbol_list, timeframe)

    exchange_config = get_exchange_config(exchange)

    start_dt = datetime.fromisoformat(start) if start else datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)

    strategy_params = json.loads(params)
    strategy_params.setdefault("symbols", symbol_list)

    ctx = BacktestContext(
        universe=universe,
        start=start_dt,
        end=end_dt,
        initial_cash=Decimal(initial_cash),
        fee_rate=exchange_config.fee_rate,
        slippage_pct=exchange_config.slippage_pct,
        max_position_size=Decimal(max_position_size),
        data_dir=market_data_dir(env.path),
    )

    strat = strategy_class(ctx, strategy_params)
    results = ctx.run(strat)

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

    strat_ns = env.state.ns("strategy")
    strat_ns.set("name", strategy)
    strat_ns.set("params", strategy_params)
    strat_ns.set("metrics", metrics)

    log.info("=== Backtest Results ===")
    log.info("Strategy: %s", strategy)
    log.info("Universe: %s", symbols)
    log.info("Total Return: %.2f%%", metrics["total_return"] * 100)
    log.info("Sharpe Ratio: %.4f", metrics["sharpe_ratio"])
    log.info("Max Drawdown: %.2f%%", metrics["max_drawdown"] * 100)
    log.info("Num Trades: %d", metrics["num_trades"])
    log.info("Win Rate: %.2f%%", metrics["win_rate"] * 100)
