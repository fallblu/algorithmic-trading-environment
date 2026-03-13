"""Portfolio function adapter — compile manage_portfolio() source into callable."""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import pandas as pd

from models.order import Order, OrderSide, OrderType

log = logging.getLogger(__name__)


def compile_orchestration_source(
    source_code: str, name: str = "<portfolio>"
) -> Callable:
    """Compile portfolio orchestration source and extract manage_portfolio().

    The source must define:
        manage_portfolio(strategy_signals, allocations, positions, market_data, params)
            -> dict[str, float]

    Available in namespace: pd, np, Order, OrderSide, OrderType.
    """
    namespace: dict = {
        "__builtins__": __builtins__,
        "pd": pd,
        "np": np,
        "Order": Order,
        "OrderSide": OrderSide,
        "OrderType": OrderType,
    }

    compiled = compile(source_code, f"<portfolio:{name}>", "exec")
    exec(compiled, namespace)

    if "manage_portfolio" not in namespace:
        raise ValueError("Portfolio source must define a manage_portfolio() function")
    if not callable(namespace["manage_portfolio"]):
        raise ValueError("manage_portfolio must be a callable function")

    return namespace["manage_portfolio"]


def default_manage_portfolio(
    strategy_signals: dict[str, list[Order]],
    allocations: dict[str, float],
    positions: dict[str, dict[str, float]],
    market_data: dict[str, pd.DataFrame],
    params: dict,
) -> dict[str, float]:
    """Default pass-through — returns allocations unchanged."""
    return allocations
