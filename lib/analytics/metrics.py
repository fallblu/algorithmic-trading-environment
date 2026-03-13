"""Performance metrics — compute trading performance statistics."""

from __future__ import annotations

import math
from datetime import datetime

from models.fill import Fill
from models.order import OrderSide


def compute_metrics(
    equity_curve: list[tuple[datetime, float]],
    fills: list[Fill],
    initial_cash: float = 10_000.0,
    periods_per_year: float = 8760.0,
    risk_free_rate: float = 0.0,
) -> dict:
    """Compute comprehensive performance metrics.

    Args:
        equity_curve: List of (timestamp, equity) tuples.
        fills: List of Fill objects from the backtest.
        initial_cash: Starting capital.
        periods_per_year: Bars per year (8760 for hourly).
        risk_free_rate: Annual risk-free rate.

    Returns:
        Dict with performance metrics.
    """
    if len(equity_curve) < 2:
        return _empty_metrics(initial_cash)

    equities = [e for _, e in equity_curve]
    final_equity = equities[-1]
    total_return = (final_equity - initial_cash) / initial_cash

    # Returns series
    returns = []
    for i in range(1, len(equities)):
        if equities[i - 1] > 0:
            returns.append((equities[i] - equities[i - 1]) / equities[i - 1])
        else:
            returns.append(0.0)

    # Annualized return
    n_periods = len(returns)
    if n_periods > 0 and total_return > -1:
        annualized_return = (1 + total_return) ** (periods_per_year / n_periods) - 1
    else:
        annualized_return = 0.0

    # Sharpe ratio
    sharpe = _sharpe_ratio(returns, risk_free_rate, periods_per_year)

    # Max drawdown
    max_dd, max_dd_duration = _max_drawdown(equities)

    # Trade analysis
    trades = _analyze_trades(fills)

    return {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "max_drawdown_duration_bars": max_dd_duration,
        "total_trades": trades["total"],
        "win_rate": trades["win_rate"],
        "profit_factor": trades["profit_factor"],
        "avg_win": trades["avg_win"],
        "avg_loss": trades["avg_loss"],
        "total_fees": trades["total_fees"],
        "initial_equity": initial_cash,
        "final_equity": final_equity,
        "num_bars": len(equity_curve),
    }


def compute_drawdown_series(
    equity_curve: list[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Compute drawdown percentage series for charting."""
    if not equity_curve:
        return []

    result: list[tuple[datetime, float]] = []
    peak = equity_curve[0][1]

    for ts, equity in equity_curve:
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        result.append((ts, dd))

    return result


def _sharpe_ratio(
    returns: list[float],
    risk_free_rate: float,
    periods_per_year: float,
) -> float:
    if len(returns) < 2:
        return 0.0

    mean_r = sum(returns) / len(returns)
    rf_per_period = risk_free_rate / periods_per_year
    excess = mean_r - rf_per_period

    variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std == 0:
        return 0.0

    return (excess / std) * math.sqrt(periods_per_year)


def _max_drawdown(equities: list[float]) -> tuple[float, int]:
    """Returns (max_drawdown_pct, max_drawdown_duration_bars)."""
    if not equities:
        return 0.0, 0

    peak = equities[0]
    max_dd = 0.0
    max_duration = 0
    current_duration = 0

    for equity in equities:
        if equity > peak:
            peak = equity
            current_duration = 0
        else:
            current_duration += 1

        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        if current_duration > max_duration:
            max_duration = current_duration

    return max_dd, max_duration


def _analyze_trades(fills: list[Fill]) -> dict:
    """Analyze trades from fills to compute win rate, profit factor, etc."""
    if not fills:
        return {
            "total": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "total_fees": 0.0,
        }

    # Group fills into round-trip trades by symbol
    open_trades: dict[str, list[Fill]] = {}
    completed_pnls: list[float] = []
    total_fees = 0.0

    for fill in fills:
        total_fees += fill.fee
        symbol = fill.symbol

        if symbol not in open_trades:
            open_trades[symbol] = []

        entries = open_trades[symbol]

        if not entries:
            entries.append(fill)
        elif entries[0].side == fill.side:
            entries.append(fill)
        else:
            # Closing trade — compute P&L
            entry_fill = entries[0]
            if entry_fill.side == OrderSide.BUY:
                pnl = (fill.price - entry_fill.price) * min(fill.quantity, entry_fill.quantity)
            else:
                pnl = (entry_fill.price - fill.price) * min(fill.quantity, entry_fill.quantity)

            completed_pnls.append(pnl)

            # Remove matched entry
            if fill.quantity >= entry_fill.quantity:
                entries.pop(0)
            if not entries:
                # Check if there's remaining fill quantity to start new position
                pass

    total = len(completed_pnls)
    if total == 0:
        return {
            "total": len(fills) // 2,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "total_fees": total_fees,
        }

    wins = [p for p in completed_pnls if p > 0]
    losses = [p for p in completed_pnls if p < 0]
    win_rate = len(wins) / total if total > 0 else 0.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    return {
        "total": total,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_fees": total_fees,
    }


def _empty_metrics(initial_cash: float) -> dict:
    return {
        "total_return": 0.0,
        "annualized_return": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_duration_bars": 0,
        "total_trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "total_fees": 0.0,
        "initial_equity": initial_cash,
        "final_equity": initial_cash,
        "num_bars": 0,
    }
