"""Portfolio model — strategy container with allocations, risk, and execution mode."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from risk.rules import RiskConfig


class ExecutionMode(Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


@dataclass
class StrategyAllocation:
    """A strategy assignment within a portfolio."""

    strategy_id: str
    strategy_name: str
    allocation_pct: float
    """Fraction of portfolio capital (0.5 = 50%)."""
    symbols: list[str] = field(default_factory=list)
    timeframe: str = "1h"
    params: dict = field(default_factory=dict)
    source_code: str | None = None
    """Strategy on_bar() source (from editor). None = use registered class."""


@dataclass
class Portfolio:
    """A portfolio of strategies with shared risk rules and capital."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Portfolio"
    mode: ExecutionMode = ExecutionMode.BACKTEST
    strategies: list[StrategyAllocation] = field(default_factory=list)
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    initial_cash: float = 10_000.0
    orchestration_code: str | None = None
    """manage_portfolio() source code, or None for default pass-through."""
    exchange: str = "kraken"
    profile: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict for storage."""
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode.value,
            "strategies": [
                {
                    "strategy_id": s.strategy_id,
                    "strategy_name": s.strategy_name,
                    "allocation_pct": s.allocation_pct,
                    "symbols": s.symbols,
                    "timeframe": s.timeframe,
                    "params": s.params,
                    "source_code": s.source_code,
                }
                for s in self.strategies
            ],
            "risk_config": {
                "max_position_pct": self.risk_config.max_position_pct,
                "max_drawdown_pct": self.risk_config.max_drawdown_pct,
                "max_gross_exposure": self.risk_config.max_gross_exposure,
                "max_net_exposure": self.risk_config.max_net_exposure,
                "max_daily_loss_pct": self.risk_config.max_daily_loss_pct,
            },
            "initial_cash": self.initial_cash,
            "orchestration_code": self.orchestration_code,
            "exchange": self.exchange,
            "profile": self.profile,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Portfolio:
        """Deserialize from a dict."""
        strategies = [
            StrategyAllocation(
                strategy_id=s["strategy_id"],
                strategy_name=s["strategy_name"],
                allocation_pct=s["allocation_pct"],
                symbols=s.get("symbols", []),
                timeframe=s.get("timeframe", "1h"),
                params=s.get("params", {}),
                source_code=s.get("source_code"),
            )
            for s in data.get("strategies", [])
        ]
        rc = data.get("risk_config", {})
        risk_config = RiskConfig(
            max_position_pct=rc.get("max_position_pct", 0.25),
            max_drawdown_pct=rc.get("max_drawdown_pct", 0.20),
            max_gross_exposure=rc.get("max_gross_exposure", 2.0),
            max_net_exposure=rc.get("max_net_exposure", 1.0),
            max_daily_loss_pct=rc.get("max_daily_loss_pct", 0.05),
        )
        return cls(
            id=data["id"],
            name=data.get("name", "Untitled Portfolio"),
            mode=ExecutionMode(data.get("mode", "backtest")),
            strategies=strategies,
            risk_config=risk_config,
            initial_cash=data.get("initial_cash", 10_000.0),
            orchestration_code=data.get("orchestration_code"),
            exchange=data.get("exchange", "kraken"),
            profile=data.get("profile", "default"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(timezone.utc),
        )
