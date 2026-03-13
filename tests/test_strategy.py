from __future__ import annotations

import pytest

from strategy.base import Strategy
from strategy.function_adapter import FunctionStrategy, compile_strategy_source
from strategy.registry import _REGISTRY, register, get_strategy, list_strategies


# ---------------------------------------------------------------------------
# FunctionStrategy
# ---------------------------------------------------------------------------

class TestCompileStrategySource:
    def test_compile_valid_source(self):
        source = """
def on_bar(bars, positions, params):
    return []
"""
        fn = compile_strategy_source(source)
        assert callable(fn)
        assert fn(None, {}, {}) == []

    def test_compile_missing_on_bar(self):
        with pytest.raises(ValueError, match="on_bar"):
            compile_strategy_source("x = 1")

    def test_compile_syntax_error(self):
        with pytest.raises(SyntaxError):
            compile_strategy_source("def on_bar(")


class TestFunctionStrategy:
    def test_from_callable(self):
        def my_on_bar(bars, positions, params):
            return []

        strategy = FunctionStrategy(fn=my_on_bar, name="test", symbols=["BTC/USD"])
        assert strategy.universe() == ["BTC/USD"]
        assert strategy.lookback() == 50
        assert strategy.on_bar(None, {}) == []

    def test_from_source_code(self):
        source = """
def on_bar(bars, positions, params):
    return []
"""
        strategy = FunctionStrategy(source_code=source, name="test", symbols=["ETH/USD"])
        assert strategy.universe() == ["ETH/USD"]
        assert strategy.on_bar(None, {}) == []

    def test_must_provide_fn_or_source(self):
        with pytest.raises(ValueError, match="fn or source_code"):
            FunctionStrategy(name="bad")

    def test_params_passed_through(self):
        def my_on_bar(bars, positions, params):
            return params.get("value", 0)

        strategy = FunctionStrategy(fn=my_on_bar, params={"value": 42})
        result = strategy.on_bar(None, {})
        assert result == 42


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def setup_method(self):
        # Clear registry before each test
        _REGISTRY.clear()

    def test_register_and_get(self):
        @register("test_strat")
        class TestStrat(Strategy):
            def universe(self): return []
            def lookback(self): return 10
            def on_bar(self, bars, positions): return []

        cls = get_strategy("test_strat")
        assert cls is TestStrat

    def test_get_missing_raises(self):
        with pytest.raises(KeyError, match="not found"):
            get_strategy("nonexistent")

    def test_list_strategies(self):
        @register("alpha")
        class Alpha(Strategy):
            def universe(self): return []
            def lookback(self): return 10
            def on_bar(self, bars, positions): return []

        @register("beta")
        class Beta(Strategy):
            def universe(self): return []
            def lookback(self): return 10
            def on_bar(self, bars, positions): return []

        assert list_strategies() == ["alpha", "beta"]

    def test_register_non_strategy_raises(self):
        with pytest.raises(TypeError, match="subclass"):
            @register("bad")
            class NotAStrategy:
                pass
