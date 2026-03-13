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
        return self._state.setdefault("portfolios", {})

    def list_all(self) -> list[Portfolio]:
        return [Portfolio.from_dict(p) for p in self._portfolios().values()]

    def get(self, portfolio_id: str) -> Portfolio | None:
        data = self._portfolios().get(portfolio_id)
        if data is None:
            return None
        return Portfolio.from_dict(data)

    def save(self, portfolio: Portfolio) -> None:
        portfolio.updated_at = datetime.now(timezone.utc)
        portfolios = self._portfolios()
        portfolios[portfolio.id] = portfolio.to_dict()
        self._state.set("portfolios", portfolios)

    def delete(self, portfolio_id: str) -> bool:
        portfolios = self._portfolios()
        if portfolio_id in portfolios:
            del portfolios[portfolio_id]
            self._state.set("portfolios", portfolios)
            return True
        return False
