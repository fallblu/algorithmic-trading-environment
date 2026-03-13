"""PortfolioOrchestrator — runs manage_portfolio() and applies allocation changes."""

from __future__ import annotations

import logging
from typing import Callable

import pandas as pd

from models.order import Order
from portfolio.function_adapter import (
    compile_orchestration_source,
    default_manage_portfolio,
)

log = logging.getLogger(__name__)


class PortfolioOrchestrator:
    """Runs the optional manage_portfolio() function each bar.

    If no orchestration code is provided, allocations pass through unchanged.
    """

    def __init__(self, orchestration_code: str | None = None) -> None:
        self._fn: Callable = default_manage_portfolio
        if orchestration_code:
            try:
                self._fn = compile_orchestration_source(orchestration_code)
            except Exception as e:
                log.error("Failed to compile orchestration code: %s", e)

    def run(
        self,
        strategy_signals: dict[str, list[Order]],
        allocations: dict[str, float],
        positions: dict[str, dict[str, float]],
        market_data: dict[str, pd.DataFrame],
        params: dict | None = None,
    ) -> dict[str, float]:
        """Execute the orchestration function.

        Returns adjusted allocations dict. Allocation of 0.0 pauses a strategy.
        """
        try:
            result = self._fn(
                strategy_signals,
                allocations,
                positions,
                market_data,
                params or {},
            )
            if not isinstance(result, dict):
                log.warning("manage_portfolio() returned %s, expected dict", type(result))
                return allocations
            return result
        except Exception as e:
            log.error("Error in manage_portfolio(): %s", e)
            return allocations
