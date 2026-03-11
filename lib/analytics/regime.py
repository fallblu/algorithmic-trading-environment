"""Regime detection — Hidden Markov Model based market regime classification."""

import logging

import numpy as np
import pandas as pd

from analytics.utils import log_returns

log = logging.getLogger(__name__)


def regime_detection(bars_df: pd.DataFrame, n_regimes: int = 2) -> dict:
    """Hidden Markov Model regime detection.

    Args:
        bars_df: DataFrame with 'close' column.
        n_regimes: Number of regimes (states).

    Returns:
        Dict with regime labels, transition matrix, per-regime statistics.
    """
    from hmmlearn.hmm import GaussianHMM

    closes = bars_df["close"].values.astype(float)
    returns = log_returns(closes)

    if len(returns) < 20:
        log.debug("Insufficient returns (%d) for regime detection", len(returns))
        return {"regimes": [], "transition_matrix": [], "regime_stats": {}}

    X = returns.reshape(-1, 1)
    model = GaussianHMM(n_components=n_regimes, covariance_type="full", n_iter=100)
    model.fit(X)
    labels = model.predict(X)

    log.info("Regime detection complete: %d regimes, %d observations", n_regimes, len(returns))

    # Per-regime statistics
    regime_stats = {}
    for r in range(n_regimes):
        mask = labels == r
        r_returns = returns[mask]
        if len(r_returns) > 0:
            regime_stats[f"regime_{r}"] = {
                "mean": float(np.mean(r_returns)),
                "std": float(np.std(r_returns, ddof=1)) if len(r_returns) > 1 else 0.0,
                "count": int(np.sum(mask)),
                "fraction": float(np.mean(mask)),
            }

    return {
        "regimes": labels.tolist(),
        "transition_matrix": model.transmat_.tolist(),
        "regime_stats": regime_stats,
    }
