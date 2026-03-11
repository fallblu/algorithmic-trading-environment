"""Centralized configuration — exchange credentials, defaults, and settings."""

import os
from decimal import Decimal


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


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


def get_kraken_futures_credentials() -> tuple[str, str]:
    """Load Kraken Futures API credentials from env vars."""
    api_key = os.environ.get("KRAKEN_FUTURES_API_KEY")
    api_secret = os.environ.get("KRAKEN_FUTURES_API_SECRET")
    if not api_key or not api_secret:
        raise ConfigError(
            "KRAKEN_FUTURES_API_KEY and KRAKEN_FUTURES_API_SECRET must be set "
            "for Kraken Futures."
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

EXCHANGE_DEFAULTS: dict[str, dict] = {
    "kraken": {
        "fee_rate": Decimal("0.0026"),
        "slippage_pct": Decimal("0.0001"),
        "quote_currency": "USD",
    },
    "kraken_futures": {
        "fee_rate": Decimal("0.0005"),
        "slippage_pct": Decimal("0.0001"),
        "quote_currency": "USD",
        "default_leverage": Decimal("10"),
    },
    "oanda": {
        "fee_rate": Decimal("0"),
        "slippage_pct": Decimal("0"),
        "spread_pips": Decimal("1.5"),
        "quote_currency": "USD",
        "default_leverage": Decimal("50"),
    },
}


def get_exchange_defaults(exchange: str) -> dict:
    """Get default parameters for an exchange."""
    defaults = EXCHANGE_DEFAULTS.get(exchange)
    if defaults is None:
        raise ConfigError(
            f"No defaults for exchange {exchange!r}. "
            f"Available: {list(EXCHANGE_DEFAULTS.keys())}"
        )
    return dict(defaults)


# -- Risk defaults --

RISK_DEFAULTS = {
    "max_position_size": Decimal("1.0"),
    "max_order_value": Decimal("100000"),
    "daily_loss_limit": Decimal("-500"),
    "max_drawdown_limit": Decimal("0.20"),
}


# -- Dashboard settings --

DASHBOARD_DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8050,
}
