"""KrakenFuturesBroker — live order execution via Kraken Futures REST API."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from broker.base import Broker
from data.kraken_futures_api import SYMBOL_TO_KRAKEN_FUTURES
from data.kraken_futures_auth import KrakenFuturesAuthError, private_futures_request
from models.account import Account
from models.instrument import Instrument
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.position import Position

log = logging.getLogger(__name__)

ORDER_TYPE_MAP = {
    OrderType.MARKET: "mkt",
    OrderType.LIMIT: "lmt",
    OrderType.STOP: "stp",
    OrderType.STOP_LIMIT: "take_profit",
}

ORDER_SIDE_MAP = {
    OrderSide.BUY: "buy",
    OrderSide.SELL: "sell",
}


class KrakenFuturesBroker(Broker):
    """Live broker for Kraken Futures perpetual contracts.

    Uses the Kraken Futures private REST API for order management,
    position tracking, and account queries.
    """

    def __init__(self):
        from data.kraken_futures_auth import get_futures_credentials
        get_futures_credentials()  # validate credentials exist

        self._orders: dict[str, Order] = {}
        self._kraken_to_local: dict[str, str] = {}

    def submit_order(self, order: Order) -> Order:
        kraken_sym = SYMBOL_TO_KRAKEN_FUTURES.get(
            order.instrument.symbol, order.instrument.symbol
        )

        data = {
            "symbol": kraken_sym,
            "side": ORDER_SIDE_MAP[order.side],
            "orderType": ORDER_TYPE_MAP[order.type],
            "size": str(order.quantity),
        }

        if order.type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and order.price is not None:
            data["limitPrice"] = str(order.price)
        if order.type in (OrderType.STOP, OrderType.STOP_LIMIT) and order.stop_price is not None:
            data["stopPrice"] = str(order.stop_price)

        result = private_futures_request("/derivatives/api/v3/sendorder", data)

        order_status = result.get("sendStatus", {})
        order_id = order_status.get("order_id", "")
        if order_id:
            order.metadata["kraken_futures_order_id"] = order_id
            self._kraken_to_local[order_id] = order.id

        order.status = OrderStatus.OPEN
        order.updated_at = datetime.now(timezone.utc)
        self._orders[order.id] = order
        log.info("Futures order submitted: %s -> %s", order.id, order_id)
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        kraken_id = order.metadata.get("kraken_futures_order_id")
        if kraken_id is None:
            raise ValueError(f"Order {order_id} has no Kraken Futures order ID")

        private_futures_request(
            "/derivatives/api/v3/cancelorder",
            {"order_id": kraken_id},
        )

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(timezone.utc)
        log.info("Futures order cancelled: %s", order_id)
        return order

    def get_order(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(f"Order {order_id} not found")
        return order

    def get_open_orders(self, instrument: Instrument | None = None) -> list[Order]:
        result = private_futures_request("/derivatives/api/v3/openorders")
        open_orders = result.get("openOrders", [])

        orders = []
        for oo in open_orders:
            kraken_id = oo.get("order_id", "")
            local_id = self._kraken_to_local.get(kraken_id)
            if local_id and local_id in self._orders:
                order = self._orders[local_id]
                order.status = OrderStatus.OPEN
                orders.append(order)

        if instrument is not None:
            orders = [o for o in orders if o.instrument.symbol == instrument.symbol]

        return orders

    def get_position(self, instrument: Instrument) -> Position | None:
        result = private_futures_request("/derivatives/api/v3/openpositions")
        positions = result.get("openPositions", [])

        kraken_sym = SYMBOL_TO_KRAKEN_FUTURES.get(
            instrument.symbol, instrument.symbol
        )

        for pos_data in positions:
            if pos_data.get("symbol") == kraken_sym:
                size = Decimal(str(pos_data.get("size", 0)))
                if size == 0:
                    return None

                side = OrderSide.BUY if pos_data.get("side") == "long" else OrderSide.SELL
                entry = Decimal(str(pos_data.get("price", 0)))
                unrealized = Decimal(str(pos_data.get("unrealizedFunding", 0)))

                return Position(
                    instrument=instrument,
                    side=side,
                    quantity=abs(size),
                    entry_price=entry,
                    unrealized_pnl=unrealized,
                    last_updated=datetime.now(timezone.utc),
                )

        return None

    def get_positions(self) -> list[Position]:
        result = private_futures_request("/derivatives/api/v3/openpositions")
        positions = []
        for pos_data in result.get("openPositions", []):
            size = Decimal(str(pos_data.get("size", 0)))
            if size == 0:
                continue

            from data.kraken_futures_api import KRAKEN_TO_SYMBOL_FUTURES
            kraken_sym = pos_data.get("symbol", "")
            our_sym = KRAKEN_TO_SYMBOL_FUTURES.get(kraken_sym, kraken_sym)

            side = OrderSide.BUY if pos_data.get("side") == "long" else OrderSide.SELL

            positions.append(Position(
                instrument=Instrument(
                    symbol=our_sym, base=our_sym.split("-")[0], quote="USD",
                    exchange="kraken_futures", asset_class="crypto_futures",
                    tick_size=Decimal("0.01"), lot_size=Decimal("0.001"),
                    min_notional=Decimal("5"),
                ),
                side=side,
                quantity=abs(size),
                entry_price=Decimal(str(pos_data.get("price", 0))),
            ))

        return positions

    def get_account(self) -> Account:
        result = private_futures_request("/derivatives/api/v3/accounts")
        accounts = result.get("accounts", {})

        # Futures uses "flex" or "cash" account
        flex = accounts.get("flex", accounts.get("cash", {}))

        equity = Decimal(str(flex.get("portfolioValue", 0)))
        margin_used = Decimal(str(flex.get("initialMargin", 0)))
        unrealized = Decimal(str(flex.get("unrealizedFunding", 0)))
        available = Decimal(str(flex.get("availableMargin", 0)))

        balances = {"USD": available}

        return Account(
            balances=balances,
            equity=equity,
            margin_used=margin_used,
            margin_available=available,
            unrealized_pnl=unrealized,
        )

    def set_leverage(self, instrument: Instrument, leverage: int) -> None:
        """Set leverage preference for a futures contract."""
        kraken_sym = SYMBOL_TO_KRAKEN_FUTURES.get(
            instrument.symbol, instrument.symbol
        )
        private_futures_request(
            "/derivatives/api/v3/leveragepreferences",
            {"symbol": kraken_sym, "maxLeverage": str(leverage)},
        )
        log.info("Leverage set to %dx for %s", leverage, instrument.symbol)
