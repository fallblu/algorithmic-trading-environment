"""Risk rules — configurable risk constraints for portfolios."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RiskLevel(Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class RiskConfig:
    """Portfolio-level risk configuration."""

    max_position_pct: float = 0.25
    """Max single position as fraction of equity (0.25 = 25%)."""

    max_drawdown_pct: float = 0.20
    """Kill switch triggers at this drawdown level (0.20 = 20%)."""

    max_gross_exposure: float = 2.0
    """Max gross exposure as multiple of equity."""

    max_net_exposure: float = 1.0
    """Max net exposure as multiple of equity."""

    max_daily_loss_pct: float = 0.05
    """Stop trading after this daily loss (0.05 = 5%)."""


@dataclass
class RiskEvent:
    """A risk violation event."""

    rule: str
    message: str
    level: RiskLevel
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
