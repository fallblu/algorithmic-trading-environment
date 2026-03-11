"""Data analysis workflow — statistical analysis and technical scanning."""

import logging
import sys
from pathlib import Path

from persistra import Workflow

log = logging.getLogger(__name__)


def _ensure_lib_path(env):
    lib_path = str(Path(env.path) / "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def analyze_symbol(env):
    """Run full statistical analysis on a single symbol."""
    _ensure_lib_path(env)
    import pandas as pd
    from analytics.data_analyzer import (
        autocorrelation_analysis,
        return_distribution,
        tail_risk_analysis,
        volatility_analysis,
    )
    from data.store import MarketDataStore

    data_dir = Path(env.path) / ".persistra" / "market_data"
    store = MarketDataStore(data_dir)

    symbol = env.state.get("analysis_symbol", "BTC/USD")
    timeframe = env.state.get("analysis_timeframe", "1h")
    exchange = env.state.get("analysis_exchange", "kraken")

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
    _ensure_lib_path(env)
    import pandas as pd
    from analytics.data_analyzer import scan_universe
    from data.store import MarketDataStore

    data_dir = Path(env.path) / ".persistra" / "market_data"
    store = MarketDataStore(data_dir)

    symbols_str = env.state.get("scan_symbols", "BTC/USD,ETH/USD")
    symbol_list = [s.strip() for s in symbols_str.split(",")]
    timeframe = env.state.get("scan_timeframe", "1h")
    exchange = env.state.get("scan_exchange", "kraken")

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
    _ensure_lib_path(env)
    import pandas as pd
    from analytics.data_analyzer import correlation_matrix
    from data.store import MarketDataStore

    data_dir = Path(env.path) / ".persistra" / "market_data"
    store = MarketDataStore(data_dir)

    symbols_str = env.state.get("correlation_symbols", "BTC/USD,ETH/USD")
    symbol_list = [s.strip() for s in symbols_str.split(",")]
    timeframe = env.state.get("correlation_timeframe", "1h")
    exchange = env.state.get("correlation_exchange", "kraken")

    symbol_bars = {}
    for symbol in symbol_list:
        bars = store.read_bars(exchange, symbol, timeframe)
        if bars:
            symbol_bars[symbol] = pd.DataFrame([{
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


def build(env) -> Workflow:
    """Build the data analysis workflow DAG."""
    w = Workflow("analyze")

    w.add("analyze_symbol", analyze_symbol)
    w.add("scan_universe", scan_universe_signals)
    w.add("correlation_report", correlation_report)

    return w
