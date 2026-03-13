from __future__ import annotations

from datetime import datetime, timezone

import pytest

from portfolio.portfolio import ExecutionMode, Portfolio, StrategyAllocation
from portfolio.orchestrator import PortfolioOrchestrator
from portfolio.function_adapter import (
    compile_orchestration_source,
    default_manage_portfolio,
)
from portfolio.storage import PortfolioStorage
from risk.rules import RiskConfig


# ---------------------------------------------------------------------------
# Portfolio model
# ---------------------------------------------------------------------------

class TestPortfolio:
    def test_portfolio_defaults(self):
        p = Portfolio()
        assert p.name == "Untitled Portfolio"
        assert p.mode == ExecutionMode.BACKTEST
        assert p.initial_cash == 10_000.0
        assert p.strategies == []
        assert p.orchestration_code is None
        assert p.exchange == "kraken"
        assert p.profile == "default"
        assert p.id  # non-empty uuid

    def test_portfolio_with_strategies(self):
        alloc = StrategyAllocation(
            strategy_id="s1",
            strategy_name="sma_crossover",
            allocation_pct=0.6,
            symbols=["BTC/USD"],
            params={"fast_period": 10},
        )
        p = Portfolio(
            name="Test Portfolio",
            strategies=[alloc],
            initial_cash=50_000.0,
        )
        assert len(p.strategies) == 1
        assert p.strategies[0].strategy_name == "sma_crossover"
        assert p.strategies[0].allocation_pct == 0.6

    def test_execution_mode_enum(self):
        assert ExecutionMode.BACKTEST.value == "backtest"
        assert ExecutionMode.PAPER.value == "paper"
        assert ExecutionMode.LIVE.value == "live"


class TestPortfolioSerialization:
    def _make_portfolio(self) -> Portfolio:
        return Portfolio(
            id="test-id-123",
            name="My Portfolio",
            mode=ExecutionMode.PAPER,
            strategies=[
                StrategyAllocation(
                    strategy_id="s1",
                    strategy_name="sma_crossover",
                    allocation_pct=0.5,
                    symbols=["BTC/USD"],
                    params={"fast_period": 10},
                    source_code="def on_bar(bars, positions, params): return []",
                ),
                StrategyAllocation(
                    strategy_id="s2",
                    strategy_name="mean_reversion",
                    allocation_pct=0.5,
                    symbols=["ETH/USD"],
                ),
            ],
            risk_config=RiskConfig(max_position_pct=0.30, max_drawdown_pct=0.15),
            initial_cash=25_000.0,
            orchestration_code="def manage_portfolio(*a): return a[1]",
            exchange="oanda",
            profile="testnet",
            created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 6, 15, tzinfo=timezone.utc),
        )

    def test_to_dict(self):
        p = self._make_portfolio()
        d = p.to_dict()
        assert d["id"] == "test-id-123"
        assert d["name"] == "My Portfolio"
        assert d["mode"] == "paper"
        assert len(d["strategies"]) == 2
        assert d["strategies"][0]["allocation_pct"] == 0.5
        assert d["risk_config"]["max_position_pct"] == 0.30
        assert d["initial_cash"] == 25_000.0
        assert d["exchange"] == "oanda"

    def test_roundtrip(self):
        original = self._make_portfolio()
        d = original.to_dict()
        restored = Portfolio.from_dict(d)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.mode == original.mode
        assert len(restored.strategies) == 2
        assert restored.strategies[0].strategy_name == "sma_crossover"
        assert restored.strategies[0].source_code is not None
        assert restored.strategies[1].source_code is None
        assert restored.risk_config.max_position_pct == 0.30
        assert restored.initial_cash == 25_000.0
        assert restored.orchestration_code is not None
        assert restored.exchange == "oanda"


# ---------------------------------------------------------------------------
# Function adapter
# ---------------------------------------------------------------------------

class TestOrchestrationAdapter:
    def test_compile_valid_source(self):
        source = """
def manage_portfolio(strategy_signals, allocations, positions, market_data, params):
    return allocations
"""
        fn = compile_orchestration_source(source)
        result = fn({}, {"s1": 0.5}, {}, {}, {})
        assert result == {"s1": 0.5}

    def test_compile_missing_function(self):
        with pytest.raises(ValueError, match="manage_portfolio"):
            compile_orchestration_source("x = 1")

    def test_default_manage_portfolio_passthrough(self):
        allocs = {"s1": 0.6, "s2": 0.4}
        result = default_manage_portfolio({}, allocs, {}, {}, {})
        assert result == allocs


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class TestPortfolioOrchestrator:
    def test_default_passthrough(self):
        orch = PortfolioOrchestrator()
        allocs = {"s1": 0.5, "s2": 0.5}
        result = orch.run({}, allocs, {}, {})
        assert result == allocs

    def test_custom_orchestration(self):
        code = """
def manage_portfolio(strategy_signals, allocations, positions, market_data, params):
    # Pause strategy s2
    adjusted = dict(allocations)
    adjusted["s2"] = 0.0
    return adjusted
"""
        orch = PortfolioOrchestrator(code)
        allocs = {"s1": 0.6, "s2": 0.4}
        result = orch.run({}, allocs, {}, {})
        assert result["s1"] == 0.6
        assert result["s2"] == 0.0

    def test_error_in_orchestration_returns_original(self):
        code = """
def manage_portfolio(strategy_signals, allocations, positions, market_data, params):
    raise ValueError("boom")
"""
        orch = PortfolioOrchestrator(code)
        allocs = {"s1": 0.5}
        result = orch.run({}, allocs, {}, {})
        assert result == allocs


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class TestPortfolioStorage:
    def test_save_and_get(self):
        store = PortfolioStorage({})
        p = Portfolio(name="Test")
        store.save(p)

        loaded = store.get(p.id)
        assert loaded is not None
        assert loaded.name == "Test"

    def test_list_all(self):
        store = PortfolioStorage({})
        store.save(Portfolio(name="A"))
        store.save(Portfolio(name="B"))
        assert len(store.list_all()) == 2

    def test_delete(self):
        store = PortfolioStorage({})
        p = Portfolio(name="To Delete")
        store.save(p)
        assert store.delete(p.id) is True
        assert store.get(p.id) is None

    def test_delete_nonexistent(self):
        store = PortfolioStorage({})
        assert store.delete("no-such-id") is False

    def test_get_nonexistent(self):
        store = PortfolioStorage({})
        assert store.get("no-such-id") is None
