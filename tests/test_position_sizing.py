"""Tests for position sizing strategies."""

from decimal import Decimal

import pytest

from models.account import Account
from risk.sizing import (
    FixedFractionalSizer,
    ATRSizer,
    VolatilityScaledSizer,
    KellySizer,
)


@pytest.fixture
def account():
    return Account(
        equity=Decimal("100000"),
        balances={"USD": Decimal("100000")},
        margin_available=Decimal("100000"),
    )


class TestFixedFractionalSizer:
    def test_calculates_size(self, btc_instrument, account):
        sizer = FixedFractionalSizer(
            risk_per_trade=Decimal("0.01"),
            stop_distance_pct=Decimal("0.02"),
        )
        size = sizer.calculate_size(
            instrument=btc_instrument,
            signal_strength=1.0,
            account=account,
            current_price=Decimal("50000"),
        )
        assert size > Decimal("0")
        # Risk $1000 (1% of 100K), stop 2% away ($1000)
        # Size = $1000 / $1000 = 1.0 BTC (approx)
        assert size <= Decimal("2")

    def test_zero_equity_returns_zero(self, btc_instrument):
        account = Account(equity=Decimal("0"))
        sizer = FixedFractionalSizer()
        size = sizer.calculate_size(
            instrument=btc_instrument, signal_strength=1.0,
            account=account, current_price=Decimal("50000"),
        )
        assert size == Decimal("0")


class TestATRSizer:
    def test_calculates_size_with_volatility(self, btc_instrument, account):
        sizer = ATRSizer(
            risk_per_trade=Decimal("0.01"),
            atr_multiplier=Decimal("2"),
        )
        size = sizer.calculate_size(
            instrument=btc_instrument,
            signal_strength=1.0,
            account=account,
            current_price=Decimal("50000"),
            volatility=Decimal("1500"),  # ATR = 1500
        )
        assert size > Decimal("0")
        # Risk = $1000, stop distance = 2 * 1500 = 3000
        # Size ≈ 1000 / 3000 ≈ 0.333

    def test_no_volatility_uses_fallback(self, btc_instrument, account):
        sizer = ATRSizer()
        size = sizer.calculate_size(
            instrument=btc_instrument, signal_strength=1.0,
            account=account, current_price=Decimal("50000"),
            volatility=None,
        )
        assert size >= Decimal("0")


class TestVolatilityScaledSizer:
    def test_calculates_size(self, btc_instrument, account):
        sizer = VolatilityScaledSizer(target_vol_contribution=Decimal("0.02"))
        size = sizer.calculate_size(
            instrument=btc_instrument,
            signal_strength=1.0,
            account=account,
            current_price=Decimal("50000"),
            volatility=Decimal("0.60"),  # 60% annualized vol
        )
        assert size > Decimal("0")

    def test_high_vol_gives_smaller_size(self, btc_instrument, account):
        sizer = VolatilityScaledSizer(target_vol_contribution=Decimal("0.02"))
        size_low_vol = sizer.calculate_size(
            instrument=btc_instrument, signal_strength=1.0,
            account=account, current_price=Decimal("50000"),
            volatility=Decimal("0.20"),
        )
        size_high_vol = sizer.calculate_size(
            instrument=btc_instrument, signal_strength=1.0,
            account=account, current_price=Decimal("50000"),
            volatility=Decimal("0.80"),
        )
        assert size_low_vol > size_high_vol


class TestKellySizer:
    def test_calculates_size(self, btc_instrument, account):
        sizer = KellySizer(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            kelly_fraction=0.5,
        )
        size = sizer.calculate_size(
            instrument=btc_instrument,
            signal_strength=1.0,
            account=account,
            current_price=Decimal("50000"),
        )
        assert size > Decimal("0")

    def test_losing_stats_returns_zero(self, btc_instrument, account):
        sizer = KellySizer(
            win_rate=0.3,
            avg_win_loss_ratio=0.5,
            kelly_fraction=0.5,
        )
        size = sizer.calculate_size(
            instrument=btc_instrument, signal_strength=1.0,
            account=account, current_price=Decimal("50000"),
        )
        # Kelly = 0.3 - (0.7/0.5) = 0.3 - 1.4 = -1.1 → clamped to 0
        assert size == Decimal("0")

    def test_update_stats(self, btc_instrument, account):
        sizer = KellySizer(win_rate=0.5, avg_win_loss_ratio=1.0)
        sizer.update_stats(win_rate=0.6, avg_win_loss_ratio=2.0)

        size = sizer.calculate_size(
            instrument=btc_instrument, signal_strength=1.0,
            account=account, current_price=Decimal("50000"),
        )
        assert size > Decimal("0")
