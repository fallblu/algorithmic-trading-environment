"""Dynamic position sizing — multiple methods for calculating optimal trade size."""

import logging
from abc import ABC, abstractmethod
from decimal import Decimal

from models.account import Account
from models.instrument import Instrument

log = logging.getLogger(__name__)


class PositionSizer(ABC):
    """Base class for position sizing strategies."""

    @abstractmethod
    def calculate_size(
        self,
        instrument: Instrument,
        signal_strength: float,
        account: Account,
        current_price: Decimal,
        volatility: Decimal | None = None,
    ) -> Decimal:
        """Calculate position size for a trade.

        Args:
            instrument: The instrument to trade.
            signal_strength: Signal strength (0.0 to 1.0).
            account: Current account state.
            current_price: Current market price.
            volatility: Optional ATR or realized vol for the instrument.

        Returns:
            Position size as Decimal quantity.
        """
        ...


class FixedFractionalSizer(PositionSizer):
    """Risk a fixed percentage of equity per trade.

    Sizes position so that a stop-loss at `risk_per_trade` % of equity
    determines the quantity.
    """

    def __init__(self, risk_per_trade: Decimal = Decimal("0.01"), stop_distance_pct: Decimal = Decimal("0.02")):
        self.risk_per_trade = risk_per_trade
        self.stop_distance_pct = stop_distance_pct

    def calculate_size(
        self,
        instrument: Instrument,
        signal_strength: float,
        account: Account,
        current_price: Decimal,
        volatility: Decimal | None = None,
    ) -> Decimal:
        equity = account.equity
        risk_amount = equity * self.risk_per_trade
        stop_distance = current_price * self.stop_distance_pct

        if stop_distance <= 0:
            return Decimal("0")

        size = risk_amount / stop_distance
        log.debug("FixedFractional: equity=%s risk=%s stop_dist=%s -> size=%s",
                  equity, risk_amount, stop_distance, size)
        return size


class ATRSizer(PositionSizer):
    """Size inversely proportional to ATR — volatile assets get smaller positions.

    Targets a fixed dollar risk per ATR unit.
    """

    def __init__(self, risk_per_trade: Decimal = Decimal("0.01"), atr_multiplier: Decimal = Decimal("2.0")):
        self.risk_per_trade = risk_per_trade
        self.atr_multiplier = atr_multiplier

    def calculate_size(
        self,
        instrument: Instrument,
        signal_strength: float,
        account: Account,
        current_price: Decimal,
        volatility: Decimal | None = None,
    ) -> Decimal:
        if volatility is None or volatility <= 0:
            log.warning("ATRSizer: no volatility provided for %s, using fixed fractional fallback", instrument.symbol)
            stop_distance = current_price * Decimal("0.02")
        else:
            stop_distance = volatility * self.atr_multiplier

        equity = account.equity
        risk_amount = equity * self.risk_per_trade

        if stop_distance <= 0:
            return Decimal("0")

        size = risk_amount / stop_distance
        log.debug("ATRSizer: equity=%s vol=%s stop=%s -> size=%s",
                  equity, volatility, stop_distance, size)
        return size


class VolatilityScaledSizer(PositionSizer):
    """Target a fixed portfolio volatility contribution per position.

    Each position contributes approximately `target_vol_contribution` to
    the portfolio's annualized volatility.
    """

    def __init__(self, target_vol_contribution: Decimal = Decimal("0.02")):
        self.target_vol_contribution = target_vol_contribution

    def calculate_size(
        self,
        instrument: Instrument,
        signal_strength: float,
        account: Account,
        current_price: Decimal,
        volatility: Decimal | None = None,
    ) -> Decimal:
        if volatility is None or volatility <= 0:
            log.warning("VolScaledSizer: no volatility for %s", instrument.symbol)
            return Decimal("0")

        equity = account.equity
        # Position notional = equity * target_vol / asset_vol
        target_notional = equity * self.target_vol_contribution / volatility

        if current_price <= 0:
            return Decimal("0")

        size = target_notional / current_price
        log.debug("VolScaled: equity=%s vol=%s target_notional=%s -> size=%s",
                  equity, volatility, target_notional, size)
        return size


class KellySizer(PositionSizer):
    """Kelly criterion — optimal sizing based on win rate and payoff ratio.

    Uses fractional Kelly (default half-Kelly) for practical risk management.
    """

    def __init__(self, win_rate: float = 0.5, avg_win_loss_ratio: float = 1.5, kelly_fraction: float = 0.5):
        self.win_rate = win_rate
        self.avg_win_loss_ratio = avg_win_loss_ratio
        self.kelly_fraction = kelly_fraction

    def calculate_size(
        self,
        instrument: Instrument,
        signal_strength: float,
        account: Account,
        current_price: Decimal,
        volatility: Decimal | None = None,
    ) -> Decimal:
        # Kelly formula: f* = (p * b - q) / b
        # where p = win rate, q = 1 - p, b = avg win / avg loss
        p = self.win_rate
        q = 1.0 - p
        b = self.avg_win_loss_ratio

        if b <= 0:
            return Decimal("0")

        kelly_pct = (p * b - q) / b
        kelly_pct = max(0.0, kelly_pct)  # Never go negative
        adjusted_pct = kelly_pct * self.kelly_fraction

        equity = account.equity
        target_notional = equity * Decimal(str(adjusted_pct))

        if current_price <= 0:
            return Decimal("0")

        size = target_notional / current_price
        log.debug("Kelly: win_rate=%.2f ratio=%.2f kelly=%.4f adjusted=%.4f -> size=%s",
                  p, b, kelly_pct, adjusted_pct, size)
        return size

    def update_stats(self, win_rate: float, avg_win_loss_ratio: float) -> None:
        """Update Kelly parameters from recent trade history."""
        self.win_rate = win_rate
        self.avg_win_loss_ratio = avg_win_loss_ratio
