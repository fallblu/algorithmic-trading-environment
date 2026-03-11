"""Backtest workflow — load data, run strategy, compute analytics."""

import logging
import sys
from pathlib import Path

from persistra import Workflow

log = logging.getLogger(__name__)


def _ensure_lib_path(env):
    """Add lib/ to sys.path for workflow function nodes (they run in-process)."""
    lib_path = str(Path(env.path) / "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def load_and_validate_data(env):
    """Verify that market data is available for backtesting."""
    _ensure_lib_path(env)
    from data.store import MarketDataStore

    data_dir = Path(env.path) / ".persistra" / "market_data"
    store = MarketDataStore(data_dir)

    symbol = env.state.get("backtest_symbol", "BTC/USD")
    timeframe = env.state.get("backtest_timeframe", "1h")
    exchange = env.state.get("backtest_exchange", "kraken")

    if not store.has_data(exchange, symbol, timeframe):
        raise RuntimeError(
            f"No market data available for {symbol} {timeframe} on {exchange}. "
            "Run the data_ingestor process first."
        )

    date_range = store.get_date_range(exchange, symbol, timeframe)
    if date_range is not None:
        start, end = date_range
        log.info("Data available for %s %s: %s to %s", symbol, timeframe, start, end)

    return {"symbol": symbol, "timeframe": timeframe, "exchange": exchange}


def compute_performance_analytics(env, **kwargs):
    """Read backtest results from state and log summary."""
    ns = env.state.ns("backtest")
    results = ns.get("results", {})

    if not results:
        log.warning("No backtest results found in state")
        return

    log.info("=== Backtest Performance Summary ===")
    log.info("Total Return:     %.2f%%", results.get("total_return", 0) * 100)
    log.info("Annualized Return: %.2f%%", results.get("annualized_return", 0) * 100)
    log.info("Sharpe Ratio:     %.4f", results.get("sharpe_ratio", 0))
    log.info("Sortino Ratio:    %.4f", results.get("sortino_ratio", 0))
    log.info("Max Drawdown:     %.2f%%", results.get("max_drawdown", 0) * 100)
    log.info("Calmar Ratio:     %.4f", results.get("calmar_ratio", 0))
    log.info("Win Rate:         %.2f%%", results.get("win_rate", 0) * 100)
    log.info("Profit Factor:    %.4f", results.get("profit_factor", 0))
    log.info("Num Trades:       %d", results.get("num_trades", 0))
    log.info("Total Fees:       $%.2f", results.get("total_fees", 0))

    return results


def build(env) -> Workflow:
    """Build the backtest workflow DAG."""
    w = Workflow("backtest")

    # Step 1: Load and validate data
    w.add("load_data", load_and_validate_data)

    # Step 2: Run the SMA crossover strategy backtest
    w.process(
        "run_strategy",
        process="sma_crossover",
        params={"mode": "backtest"},
        depends_on=["load_data"],
    )

    # Step 3: Compute and display performance analytics
    w.add(
        "analyze",
        compute_performance_analytics,
        depends_on=["run_strategy"],
    )

    return w
