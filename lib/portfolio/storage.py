"""Portfolio storage — CRUD operations via Persistra state."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from portfolio.portfolio import Portfolio

log = logging.getLogger(__name__)


class PortfolioStorage:
    """Manages portfolio persistence via Persistra state dict.

    Expects a `state` object with dict-like access for 'portfolios' key.
    For environments without Persistra, use InMemoryPortfolioStorage.
    """

    def __init__(self, state: dict) -> None:
        self._state = state

    def _portfolios(self) -> dict:
        if "portfolios" not in self._state:
            self._state["portfolios"] = {}
        return self._state["portfolios"]

    def list_all(self) -> list[Portfolio]:
        return [Portfolio.from_dict(p) for p in self._portfolios().values()]

    def get(self, portfolio_id: str) -> Portfolio | None:
        data = self._portfolios().get(portfolio_id)
        if data is None:
            return None
        return Portfolio.from_dict(data)

    def save(self, portfolio: Portfolio) -> None:
        portfolio.updated_at = datetime.now(timezone.utc)
        self._portfolios()[portfolio.id] = portfolio.to_dict()

    def delete(self, portfolio_id: str) -> bool:
        portfolios = self._portfolios()
        if portfolio_id in portfolios:
            del portfolios[portfolio_id]
            return True
        return False
