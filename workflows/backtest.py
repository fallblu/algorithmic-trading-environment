"""Backtest workflow — load data, run strategy, compute analytics."""

import logging
from pathlib import Path

from persistra import Workflow

from _common import ensure_lib_path

log = logging.getLogger(__name__)


def build(env) -> Workflow:
    """Build the backtest workflow DAG."""
    wf = env.state.ns("wf.backtest")
    symbols = wf.get("symbols", "BTC/USD")
    timeframe = wf.get("timeframe", "1h")
    exchange = wf.get("exchange", "kraken")

    def load_and_validate_data(env):
        """Verify that market data is available for all symbols in the universe."""
        ensure_lib_path(env)
        from helpers import parse_symbols, require_data

        symbol_list = parse_symbols(symbols)
        require_data(env.path, exchange, symbol_list, timeframe)

        from helpers import make_store
        store = make_store(env.path)
        for symbol in symbol_list:
            date_range = store.get_date_range(exchange, symbol, timeframe)
            if date_range is not None:
                start, end = date_range
                log.info("Data available for %s %s: %s to %s", symbol, timeframe, start, end)

        return {"symbols": symbols, "timeframe": timeframe, "exchange": exchange}

    def compute_performance_analytics(env, **kwargs):
        """Read backtest results from state and log summary."""
        ns = env.state.ns("backtest")
        results = ns.get("results", {})

        if not results:
            log.warning("No backtest results found in state")
            return

        log.info("=== Backtest Performance Summary ===")
        log.info("Universe:         %s", ns.get("universe", "unknown"))
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

    w = Workflow("backtest")
    w.add("load_data", load_and_validate_data)
    w.process(
        "run_strategy",
        process="sma_crossover",
        params={"symbols": symbols, "timeframe": timeframe},
        depends_on=["load_data"],
    )
    w.add(
        "analyze",
        compute_performance_analytics,
        depends_on=["run_strategy"],
    )
    return w
