"""Strategy registry — register and resolve strategies by name."""

from strategy.base import Strategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}


def register(name: str):
    """Decorator to register a Strategy subclass by name.

    Usage:
        @register("sma_crossover")
        class SmaCrossover(Strategy):
            ...
    """
    def decorator(cls):
        if not issubclass(cls, Strategy):
            raise TypeError(f"{cls.__name__} must be a subclass of Strategy")
        STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator


def get_strategy(name: str) -> type[Strategy]:
    """Resolve a registered strategy class by name.

    Raises:
        KeyError: If no strategy is registered with the given name.
    """
    if name not in STRATEGY_REGISTRY:
        raise KeyError(
            f"Unknown strategy: {name!r}. "
            f"Available: {list(STRATEGY_REGISTRY.keys())}"
        )
    return STRATEGY_REGISTRY[name]


def list_strategies() -> list[str]:
    """Return all registered strategy names."""
    return list(STRATEGY_REGISTRY.keys())
