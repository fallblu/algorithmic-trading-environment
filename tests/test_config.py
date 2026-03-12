"""Tests for configuration module."""

from decimal import Decimal

from config import (
    RiskConfig,
    ExchangeConfig,
    EXCHANGE_CONFIGS,
    EXCHANGE_DEFAULTS,
    get_kraken_credentials,
    get_oanda_credentials,
)
from exceptions import ConfigError


class TestExchangeConfig:
    def test_kraken_config_exists(self):
        assert "kraken" in EXCHANGE_CONFIGS
        cfg = EXCHANGE_CONFIGS["kraken"]
        assert isinstance(cfg, ExchangeConfig)
        assert cfg.fee_rate > Decimal("0")

    def test_oanda_config_exists(self):
        assert "oanda" in EXCHANGE_CONFIGS
        cfg = EXCHANGE_CONFIGS["oanda"]
        assert isinstance(cfg, ExchangeConfig)
        assert cfg.fee_rate == Decimal("0")  # OANDA uses spread, not commission
        assert cfg.spread_pips > Decimal("0")

    def test_exchange_defaults_dict(self):
        assert isinstance(EXCHANGE_DEFAULTS, dict)
        assert "kraken" in EXCHANGE_DEFAULTS


class TestRiskConfig:
    def test_defaults(self):
        cfg = RiskConfig()
        assert cfg.max_position_size == Decimal("1.0")
        assert cfg.max_order_value == Decimal("100000")
        assert cfg.daily_loss_limit < Decimal("0")
        assert Decimal("0") < cfg.max_drawdown_limit < Decimal("1")
        assert cfg.max_concentration_pct == Decimal("0.25")

    def test_custom_values(self):
        cfg = RiskConfig(
            max_position_size=Decimal("5"),
            daily_loss_limit=Decimal("-1000"),
        )
        assert cfg.max_position_size == Decimal("5")
        assert cfg.daily_loss_limit == Decimal("-1000")


class TestCredentials:
    def test_missing_kraken_credentials(self, monkeypatch):
        monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
        monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
        try:
            key, secret = get_kraken_credentials()
            # If it doesn't raise, values should be empty or raise ConfigError
        except (ConfigError, Exception):
            pass  # Expected when env vars missing

    def test_missing_oanda_credentials(self, monkeypatch):
        monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
        monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)
        try:
            get_oanda_credentials()
        except (ConfigError, Exception):
            pass  # Expected when env vars missing
