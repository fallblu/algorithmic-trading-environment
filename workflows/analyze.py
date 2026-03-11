"""Data analysis workflow — statistical analysis and technical scanning."""

import logging
from pathlib import Path

from persistra import Workflow

from _common import ensure_lib_path

log = logging.getLogger(__name__)


def build(env) -> Workflow:
    """Build the data analysis workflow DAG."""
    wf = env.state.ns("wf.analyze")
    symbol = wf.get("symbol", "BTC/USD")
    timeframe = wf.get("timeframe", "1h")
    exchange = wf.get("exchange", "kraken")
    scan_symbols_str = wf.get("scan_symbols", "BTC/USD,ETH/USD")
    correlation_symbols_str = wf.get("correlation_symbols", "BTC/USD,ETH/USD")

    def analyze_symbol(env):
        """Run full statistical analysis on a single symbol."""
        ensure_lib_path(env)
        import pandas as pd
        from analytics.data_analyzer import (
            autocorrelation_analysis,
            return_distribution,
            tail_risk_analysis,
            volatility_analysis,
        )
        from helpers import make_store

        store = make_store(env.path)
        bars = store.read_bars(exchange, symbol, timeframe)
        if not bars:
            log.warning("No data for %s %s on %s", symbol, timeframe, exchange)
            return {"error": "no data"}

        bars_df = pd.DataFrame([{
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(b.volume),
        } for b in bars])

        results = {
            "symbol": symbol,
            "timeframe": timeframe,
            "n_bars": len(bars),
            "distribution": return_distribution(bars_df),
            "volatility": volatility_analysis(bars_df),
            "autocorrelation": autocorrelation_analysis(bars_df),
            "tail_risk": tail_risk_analysis(bars_df),
        }

        ns = env.state.ns("analysis")
        ns.set("results", results)

        log.info("=== Analysis Results for %s ===", symbol)
        dist = results["distribution"]
        log.info("Mean return: %.6f", dist["mean"])
        log.info("Volatility: %.4f", results["volatility"]["realized_vol"])
        log.info("Skewness: %.4f", dist["skewness"])
        log.info("Kurtosis: %.4f", dist["kurtosis"])

        return results

    def scan_universe_signals(env):
        """Scan all symbols in universe for technical signals."""
        ensure_lib_path(env)
        from analytics.data_analyzer import scan_universe
        from helpers import make_store, parse_symbols

        store = make_store(env.path)
        symbol_list = parse_symbols(scan_symbols_str)

        scan_config = [
            {"type": "crossover", "fast": "ema_10", "slow": "sma_30"},
        ]

        results = scan_universe(store, exchange, symbol_list, timeframe, scan_config)

        ns = env.state.ns("scan")
        ns.set("results", {sym: len(sigs) for sym, sigs in results.items()})

        for sym, sigs in results.items():
            log.info("%s: %d signals detected", sym, len(sigs))

        return results

    def correlation_report(env):
        """Compute cross-asset correlations."""
        ensure_lib_path(env)
        import pandas as pd
        from analytics.data_analyzer import correlation_matrix
        from helpers import make_store, parse_symbols

        store = make_store(env.path)
        symbol_list = parse_symbols(correlation_symbols_str)

        symbol_bars = {}
        for sym in symbol_list:
            bars = store.read_bars(exchange, sym, timeframe)
            if bars:
                symbol_bars[sym] = pd.DataFrame([{
                    "close": float(b.close),
                } for b in bars])

        if len(symbol_bars) < 2:
            log.warning("Need at least 2 symbols with data for correlation")
            return {}

        corr = correlation_matrix(symbol_bars)

        ns = env.state.ns("correlation")
        ns.set("matrix", corr.to_dict())

        log.info("=== Correlation Matrix ===")
        log.info("\n%s", corr.to_string())

        return corr.to_dict()

    w = Workflow("analyze")
    w.add("analyze_symbol", analyze_symbol)
    w.add("scan_universe", scan_universe_signals)
    w.add("correlation_report", correlation_report)
    return w
