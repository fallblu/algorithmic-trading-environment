"""PaperContext — live data feed with simulated broker, multi-symbol support."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from broker.simulated import SimulatedBroker
from data.universe import Universe
from execution.realtime import RealtimeContext, _detect_exchange, create_live_feed
from risk.manager import RiskManager
from strategy.base import Strategy

log = logging.getLogger(__name__)


class PaperContext(RealtimeContext):
    """Paper trading: live market data with simulated execution.

    Supports spot (Kraken) and forex (OANDA) via exchange auto-detection
    from universe instruments.

    Lifecycle:
        1. __init__() — creates LiveFeed and SimulatedBroker
        2. subscribe_all() — subscribes the feed to all universe instruments
        3. warmup() — feeds historical bars for indicator warmup
        4. run_once() — called by daemon each tick; drains bar queue
        5. shutdown() — stops the WebSocket feed
    """

    mode = "paper"

    def __init__(
        self,
        universe: Universe,
        initial_cash: Decimal = Decimal("10000"),
        fee_rate: Decimal = Decimal("0.0026"),
        slippage_pct: Decimal = Decimal("0.0001"),
        max_position_size: Decimal = Decimal("1.0"),
        exchange: str | None = None,
        margin_mode: bool = False,
        leverage: Decimal = Decimal("1"),
        spread_pips: Decimal = Decimal("0"),
    ):
        self._universe = universe
        self._exchange = exchange if exchange else _detect_exchange(universe)

        self._feed = create_live_feed(self._exchange)
        self._broker = SimulatedBroker(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_pct=slippage_pct,
            margin_mode=margin_mode,
            leverage=leverage,
            spread_pips=spread_pips,
        )
        self._risk_manager = RiskManager(max_position_size=max_position_size)
        self._current_time = datetime.now(timezone.utc)
        self._panel = None

    def _process_fills(self, group: list, strategy: Strategy) -> list:
        """Process pending simulated orders against all bars at this timestamp."""
        new_fills = self._broker.process_bars(group)
        for fill in new_fills:
            strategy.on_fill(fill)
            log.info("Fill: %s %s %s @ %s", fill.side.value,
                     fill.quantity, fill.instrument.symbol, fill.price)
        return new_fills

    def _submit_order(self, order, strategy: Strategy) -> None:
        """Submit order to simulated broker."""
        self._broker.submit_order(order)
        log.info("Order submitted: %s %s %s qty=%s",
                 order.side.value, order.type.value,
                 order.instrument.symbol, order.quantity)

    def _empty_result(self) -> dict:
        return {
            "bars_processed": 0,
            "fills": 0,
            "equity": self._broker.get_account().equity,
            "positions": len(self._broker.get_positions()),
        }

    def _build_result(self, bars_processed: int, fills: list) -> dict:
        return {
            "bars_processed": bars_processed,
            "fills": len(fills),
            "equity": self._broker.get_account().equity,
            "positions": len(self._broker.get_positions()),
        }
