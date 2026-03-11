"""Performance analytics — compute trading metrics from equity curve and fills."""

from datetime import datetime, timedelta
from decimal import Decimal
from math import sqrt

from models.fill import Fill
from models.order import OrderSide


def compute_performance(
    equity_curve: list[tuple[datetime, Decimal]],
    fills: list[Fill],
    risk_free_rate: float = 0.0,
    periods_per_year: float = 8760,  # hourly bars → 365 * 24
) -> dict:
    """Compute performance metrics from backtest results.

    Args:
        equity_curve: List of (timestamp, equity) tuples.
        fills: List of Fill objects from the backtest.
        risk_free_rate: Annualized risk-free rate (decimal).
        periods_per_year: Number of bar periods per year (8760 for 1h bars).

    Returns:
        Dict of performance metrics.
    """
    if len(equity_curve) < 2:
        return _empty_metrics()

    equities = [float(eq) for _, eq in equity_curve]
    timestamps = [ts for ts, _ in equity_curve]

    initial_equity = equities[0]
    final_equity = equities[-1]

    # Returns series
    returns = []
    for i in range(1, len(equities)):
        if equities[i - 1] != 0:
            returns.append((equities[i] - equities[i - 1]) / equities[i - 1])
        else:
            returns.append(0.0)

    # Total return
    total_return = (final_equity - initial_equity) / initial_equity if initial_equity != 0 else 0.0

    # Annualized return
    n_periods = len(returns)
    if n_periods > 0 and total_return > -1.0:
        annualized_return = (1 + total_return) ** (periods_per_year / n_periods) - 1
    else:
        annualized_return = 0.0

    # Sharpe ratio
    sharpe = _sharpe_ratio(returns, risk_free_rate, periods_per_year)

    # Sortino ratio
    sortino = _sortino_ratio(returns, risk_free_rate, periods_per_year)

    # Max drawdown
    max_dd, max_dd_duration = _max_drawdown(equities, timestamps)

    # Trade analysis
    trade_stats = _trade_analysis(fills)

    # Calmar ratio
    calmar = annualized_return / abs(max_dd) if max_dd != 0 else 0.0

    return {
        "total_return": round(total_return, 6),
        "annualized_return": round(annualized_return, 6),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_duration": str(max_dd_duration) if max_dd_duration else "0:00:00",
        "calmar_ratio": round(calmar, 4),
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "num_bars": n_periods,
        **trade_stats,
    }


def _sharpe_ratio(
    returns: list[float], risk_free_rate: float, periods_per_year: float
) -> float:
    if not returns:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = [r - rf_per_period for r in returns]
    mean_excess = sum(excess) / len(excess)
    if len(excess) < 2:
        return 0.0
    variance = sum((r - mean_excess) ** 2 for r in excess) / (len(excess) - 1)
    std = sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    return (mean_excess / std) * sqrt(periods_per_year)


def _sortino_ratio(
    returns: list[float], risk_free_rate: float, periods_per_year: float
) -> float:
    if not returns:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = [r - rf_per_period for r in returns]
    mean_excess = sum(excess) / len(excess)
    downside = [r for r in excess if r < 0]
    if not downside:
        return 0.0 if mean_excess <= 0 else float("inf")
    downside_var = sum(r ** 2 for r in downside) / len(downside)
    downside_std = sqrt(downside_var) if downside_var > 0 else 0.0
    if downside_std == 0:
        return 0.0
    return (mean_excess / downside_std) * sqrt(periods_per_year)


def _max_drawdown(
    equities: list[float], timestamps: list[datetime]
) -> tuple[float, timedelta | None]:
    if not equities:
        return 0.0, None

    peak = equities[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_start = 0
    max_dd_end = 0

    for i, eq in enumerate(equities):
        if eq > peak:
            peak = eq
            peak_idx = i
        dd = (peak - eq) / peak if peak != 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_start = peak_idx
            max_dd_end = i

    duration = None
    if max_dd > 0 and max_dd_start < len(timestamps) and max_dd_end < len(timestamps):
        duration = timestamps[max_dd_end] - timestamps[max_dd_start]

    return max_dd, duration


def _trade_analysis(fills: list[Fill]) -> dict:
    if not fills:
        return {
            "num_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "total_fees": 0.0,
        }

    # Group fills into round-trip trades (simplified: pair buy/sell fills)
    buys: list[Fill] = []
    trades_pnl: list[float] = []
    total_fees = sum(float(f.fee) for f in fills)

    for fill in fills:
        if fill.side == OrderSide.BUY:
            buys.append(fill)
        elif fill.side == OrderSide.SELL and buys:
            buy = buys.pop(0)
            pnl = float((fill.price - buy.price) * min(fill.quantity, buy.quantity))
            pnl -= float(fill.fee + buy.fee)
            trades_pnl.append(pnl)

    if not trades_pnl:
        return {
            "num_trades": len(fills),
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "total_fees": round(total_fees, 2),
        }

    wins = [p for p in trades_pnl if p > 0]
    losses = [p for p in trades_pnl if p <= 0]

    win_rate = len(wins) / len(trades_pnl) if trades_pnl else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    return {
        "num_trades": len(trades_pnl),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "total_fees": round(total_fees, 2),
    }


def compute_per_symbol_performance(fills: list[Fill], symbols: list[str]) -> dict[str, dict]:
    """Compute trade statistics broken down by symbol.

    Returns a dict keyed by symbol, each containing trade stats for that symbol.
    """
    from collections import defaultdict

    fills_by_symbol: dict[str, list[Fill]] = defaultdict(list)
    for fill in fills:
        fills_by_symbol[fill.instrument.symbol].append(fill)

    results = {}
    for symbol in symbols:
        sym_fills = fills_by_symbol.get(symbol, [])
        results[symbol] = _trade_analysis(sym_fills)

    return results


def _empty_metrics() -> dict:
    return {
        "total_return": 0.0,
        "annualized_return": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_duration": "0:00:00",
        "calmar_ratio": 0.0,
        "initial_equity": 0.0,
        "final_equity": 0.0,
        "num_bars": 0,
        "num_trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "total_fees": 0.0,
    }
