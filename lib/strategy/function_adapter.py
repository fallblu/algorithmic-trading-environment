"""FunctionStrategy — wraps a bare on_bar() function into the Strategy interface."""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import pandas as pd

from models.order import Order, OrderSide, OrderType
from strategy.base import Strategy

log = logging.getLogger(__name__)


def compile_strategy_source(source_code: str, name: str = "<strategy>") -> Callable:
    """Compile strategy source code and extract the on_bar function.

    The source must define a function named on_bar(bars, positions, params).
    The following are available in the namespace:
    - pd (pandas), np (numpy)
    - Order, OrderSide, OrderType
    - pandas_ta (if installed)
    """
    namespace: dict = {
        "__builtins__": __builtins__,
        "pd": pd,
        "np": np,
        "Order": Order,
        "OrderSide": OrderSide,
        "OrderType": OrderType,
    }

    # Try to add pandas_ta
    try:
        import pandas_ta
        namespace["ta"] = pandas_ta
    except ImportError:
        pass

    compiled = compile(source_code, f"<strategy:{name}>", "exec")
    exec(compiled, namespace)

    if "on_bar" not in namespace:
        raise ValueError(f"Strategy source must define an on_bar() function")
    if not callable(namespace["on_bar"]):
        raise ValueError(f"on_bar must be a callable function")

    return namespace["on_bar"]


class FunctionStrategy(Strategy):
    """Adapts a plain on_bar function into the Strategy interface.

    Can be created from:
    - A callable directly
    - Source code string (compiled via exec)
    """

    def __init__(
        self,
        fn: Callable | None = None,
        source_code: str | None = None,
        name: str = "unnamed",
        symbols: list[str] | None = None,
        lookback_bars: int = 50,
        params: dict | None = None,
    ) -> None:
        super().__init__(params)
        self._name = name
        self._symbols = symbols or []
        self._lookback = lookback_bars

        if fn is not None:
            self._fn = fn
        elif source_code is not None:
            self._fn = compile_strategy_source(source_code, name)
        else:
            raise ValueError("Must provide either fn or source_code")

    def universe(self) -> list[str]:
        return self._symbols

    def lookback(self) -> int:
        return self._lookback

    def on_bar(
        self,
        bars: pd.DataFrame,
        positions: dict[str, float],
    ) -> list[Order]:
        return self._fn(bars, positions, self.params)
