"""Data analyzer — backwards-compatible re-exports from split analytics modules.

This module has been split into:
    - analytics.statistics: return_distribution, volatility_analysis, autocorrelation_analysis, tail_risk_analysis
    - analytics.correlation: correlation_matrix, rolling_correlation
    - analytics.regime: regime_detection
    - analytics.scanner: scan_indicators, scan_signals, scan_patterns, support_resistance, scan_universe

Import directly from the new modules for new code.
"""

# Re-export everything for backwards compatibility
from analytics.statistics import (  # noqa: F401
    return_distribution,
    volatility_analysis,
    autocorrelation_analysis,
    tail_risk_analysis,
)
from analytics.correlation import (  # noqa: F401
    correlation_matrix,
    rolling_correlation,
)
from analytics.regime import regime_detection  # noqa: F401
from analytics.scanner import (  # noqa: F401
    scan_indicators,
    scan_signals,
    scan_patterns,
    support_resistance,
    scan_universe,
)
