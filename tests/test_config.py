import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from config import (
    EXCHANGE_DEFAULTS,
    RISK_DEFAULTS,
    ConfigError,
    get_kraken_credentials,
    get_kraken_futures_credentials,
    get_oanda_credentials,
)


def test_exchange_defaults_has_expected_keys():
    assert "kraken" in EXCHANGE_DEFAULTS
    assert "kraken_futures" in EXCHANGE_DEFAULTS
    assert "oanda" in EXCHANGE_DEFAULTS

    for name, defaults in EXCHANGE_DEFAULTS.items():
        assert "fee_rate" in defaults
        assert "quote_currency" in defaults


def test_risk_defaults_has_expected_keys():
    assert "max_position_size" in RISK_DEFAULTS
    assert "max_order_value" in RISK_DEFAULTS
    assert "daily_loss_limit" in RISK_DEFAULTS
    assert "max_drawdown_limit" in RISK_DEFAULTS


def test_get_kraken_credentials_raises_when_env_vars_missing(monkeypatch):
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    with pytest.raises(ConfigError):
        get_kraken_credentials()


def test_get_kraken_futures_credentials_raises_when_env_vars_missing(monkeypatch):
    monkeypatch.delenv("KRAKEN_FUTURES_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_FUTURES_API_SECRET", raising=False)
    with pytest.raises(ConfigError):
        get_kraken_futures_credentials()


def test_get_oanda_credentials_raises_when_env_vars_missing(monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)
    with pytest.raises(ConfigError):
        get_oanda_credentials()
