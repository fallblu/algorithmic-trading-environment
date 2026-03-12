"""Centralized configuration — exchange credentials, defaults, and settings."""

import os
from dataclasses import dataclass, field
from decimal import Decimal

from exceptions import ConfigError  # noqa: F401 — re-exported for backwards compat


# -- Typed configuration dataclasses --

@dataclass
class ExchangeConfig:
    """Exchange-specific default parameters."""
    fee_rate: Decimal = Decimal("0")
    slippage_pct: Decimal = Decimal("0")
    quote_currency: str = "USD"
    spread_pips: Decimal = Decimal("0")
    default_leverage: Decimal = Decimal("1")


@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_position_size: Decimal = Decimal("1.0")
    max_order_value: Decimal = Decimal("100000")
    daily_loss_limit: Decimal = Decimal("-500")
    max_drawdown_limit: Decimal = Decimal("0.20")
    max_exposure: Decimal | None = None
    max_leverage: Decimal | None = None
    max_concentration_pct: Decimal = Decimal("0.25")


# -- Exchange credentials --

def get_kraken_credentials() -> tuple[str, str]:
    """Load Kraken spot API credentials from env vars."""
    api_key = os.environ.get("KRAKEN_API_KEY")
    api_secret = os.environ.get("KRAKEN_API_SECRET")
    if not api_key or not api_secret:
        raise ConfigError(
            "KRAKEN_API_KEY and KRAKEN_API_SECRET must be set for Kraken spot."
        )
    return api_key, api_secret


def get_oanda_credentials() -> tuple[str, str, str]:
    """Load OANDA API credentials from env vars.

    Returns:
        Tuple of (api_token, account_id, environment).
    """
    api_token = os.environ.get("OANDA_API_TOKEN")
    account_id = os.environ.get("OANDA_ACCOUNT_ID")
    environment = os.environ.get("OANDA_ENVIRONMENT", "practice")

    if not api_token or not account_id:
        raise ConfigError(
            "OANDA_API_TOKEN and OANDA_ACCOUNT_ID must be set for OANDA."
        )

    if environment not in ("practice", "live"):
        raise ConfigError(
            f"OANDA_ENVIRONMENT must be 'practice' or 'live', got: {environment!r}"
        )

    return api_token, account_id, environment


# -- Exchange default parameters --

EXCHANGE_CONFIGS: dict[str, ExchangeConfig] = {
    "kraken": ExchangeConfig(
        fee_rate=Decimal("0.0026"),
        slippage_pct=Decimal("0.0001"),
        quote_currency="USD",
    ),
    "oanda": ExchangeConfig(
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
        spread_pips=Decimal("1.5"),
        quote_currency="USD",
        default_leverage=Decimal("50"),
    ),
}

# Backwards-compatible dict-of-dicts
EXCHANGE_DEFAULTS: dict[str, dict] = {
    name: {
        "fee_rate": cfg.fee_rate,
        "slippage_pct": cfg.slippage_pct,
        "quote_currency": cfg.quote_currency,
        **({"spread_pips": cfg.spread_pips} if cfg.spread_pips else {}),
        **({"default_leverage": cfg.default_leverage} if cfg.default_leverage != Decimal("1") else {}),
    }
    for name, cfg in EXCHANGE_CONFIGS.items()
}


def get_exchange_config(exchange: str) -> ExchangeConfig:
    """Get typed exchange configuration."""
    config = EXCHANGE_CONFIGS.get(exchange)
    if config is None:
        raise ConfigError(
            f"No config for exchange {exchange!r}. "
            f"Available: {list(EXCHANGE_CONFIGS.keys())}"
        )
    return config


def get_exchange_defaults(exchange: str) -> dict:
    """Get default parameters for an exchange (dict form)."""
    defaults = EXCHANGE_DEFAULTS.get(exchange)
    if defaults is None:
        raise ConfigError(
            f"No defaults for exchange {exchange!r}. "
            f"Available: {list(EXCHANGE_DEFAULTS.keys())}"
        )
    return dict(defaults)


# -- Risk defaults --

DEFAULT_RISK_CONFIG = RiskConfig()

RISK_DEFAULTS = {
    "max_position_size": DEFAULT_RISK_CONFIG.max_position_size,
    "max_order_value": DEFAULT_RISK_CONFIG.max_order_value,
    "daily_loss_limit": DEFAULT_RISK_CONFIG.daily_loss_limit,
    "max_drawdown_limit": DEFAULT_RISK_CONFIG.max_drawdown_limit,
}


# -- Dashboard settings --

DASHBOARD_DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8050,
}
