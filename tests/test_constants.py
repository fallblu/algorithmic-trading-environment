"""Tests for shared constants and utilities."""

from constants import (
    TIMEFRAME_MINUTES,
    TIMEFRAME_PERIODS_PER_YEAR,
    OANDA_GRANULARITY_MAP,
    ExecutionMode,
    normalize_symbol,
    denormalize_symbol,
    timeframe_to_minutes,
    periods_per_year,
)


class TestTimeframeMappings:
    def test_standard_timeframes(self):
        assert TIMEFRAME_MINUTES["1m"] == 1
        assert TIMEFRAME_MINUTES["5m"] == 5
        assert TIMEFRAME_MINUTES["1h"] == 60
        assert TIMEFRAME_MINUTES["4h"] == 240
        assert TIMEFRAME_MINUTES["1d"] == 1440

    def test_periods_per_year_values(self):
        assert TIMEFRAME_PERIODS_PER_YEAR["1h"] > TIMEFRAME_PERIODS_PER_YEAR["1d"]
        assert TIMEFRAME_PERIODS_PER_YEAR["1d"] > TIMEFRAME_PERIODS_PER_YEAR["1w"]

    def test_timeframe_to_minutes(self):
        assert timeframe_to_minutes("1h") == 60
        assert timeframe_to_minutes("1d") == 1440

    def test_periods_per_year_func(self):
        result = periods_per_year("1h")
        assert result > 0

    def test_oanda_granularity_map(self):
        assert "1m" in OANDA_GRANULARITY_MAP or "M1" in OANDA_GRANULARITY_MAP.values()


class TestExecutionMode:
    def test_enum_values(self):
        assert ExecutionMode.BACKTEST.value == "backtest"
        assert ExecutionMode.PAPER.value == "paper"
        assert ExecutionMode.LIVE.value == "live"

    def test_all_modes(self):
        modes = list(ExecutionMode)
        assert len(modes) == 3


class TestSymbolNormalization:
    def test_normalize(self):
        assert normalize_symbol("BTC/USD") == "BTC_USD"
        assert normalize_symbol("EUR/USD") == "EUR_USD"

    def test_denormalize(self):
        assert denormalize_symbol("BTC_USD") == "BTC/USD"
        assert denormalize_symbol("EUR_USD") == "EUR/USD"

    def test_roundtrip(self):
        original = "BTC/USD"
        assert denormalize_symbol(normalize_symbol(original)) == original

    def test_no_separator(self):
        assert normalize_symbol("BTCUSD") == "BTCUSD"
        assert denormalize_symbol("BTCUSD") == "BTCUSD"
