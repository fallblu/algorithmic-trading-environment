"""KrakenBroker — live order execution via Kraken REST API."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from broker.base import Broker
from data.kraken_api import SYMBOL_TO_KRAKEN
from data.kraken_auth import KrakenAuthError, private_request
from models.account import Account
from models.instrument import Instrument
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.position import Position

log = logging.getLogger(__name__)

ORDER_TYPE_MAP = {
    OrderType.MARKET: "market",
    OrderType.LIMIT: "limit",
    OrderType.STOP: "stop-loss",
    OrderType.STOP_LIMIT: "stop-loss-limit",
}

ORDER_SIDE_MAP = {
    OrderSide.BUY: "buy",
    OrderSide.SELL: "sell",
}

# Kraken balance keys for common assets
KRAKEN_BALANCE_KEYS = {
    "BTC": ["XXBT", "XBT"],
    "ETH": ["XETH", "ETH"],
    "SOL": ["SOL"],
    "XRP": ["XXRP", "XRP"],
    "USD": ["ZUSD", "USD"],
}


class KrakenBroker(Broker):
    """Live broker executing orders against Kraken spot exchange.

    Uses the Kraken private REST API with HMAC-SHA512 authentication.
    Credentials are loaded from KRAKEN_API_KEY and KRAKEN_API_SECRET
    environment variables.
    """

    def __init__(self):
        from data.kraken_auth import get_credentials
        get_credentials()  # validate credentials exist

        self._orders: dict[str, Order] = {}
        self._kraken_to_local: dict[str, str] = {}  # kraken txid -> our order ID

    def submit_order(self, order: Order) -> Order:
        pair = SYMBOL_TO_KRAKEN.get(
            order.instrument.symbol,
            order.instrument.symbol.replace("/", ""),
        )

        data = {
            "pair": pair,
            "type": ORDER_SIDE_MAP[order.side],
            "ordertype": ORDER_TYPE_MAP[order.type],
            "volume": str(order.quantity),
        }

        if order.type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and order.price is not None:
            data["price"] = str(order.price)
        if order.type == OrderType.STOP and order.stop_price is not None:
            data["price"] = str(order.stop_price)
        elif order.type == OrderType.STOP_LIMIT and order.stop_price is not None:
            data["price2"] = str(order.stop_price)

        result = private_request("/0/private/AddOrder", data)

        txids = result.get("txid", [])
        if txids:
            order.metadata["kraken_txid"] = txids[0]
            self._kraken_to_local[txids[0]] = order.id
            log.info("Order submitted: %s -> kraken txid %s", order.id, txids[0])

        order.status = OrderStatus.OPEN
        order.updated_at = datetime.now(timezone.utc)
        self._orders[order.id] = order
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        txid = order.metadata.get("kraken_txid")
        if txid is None:
            raise ValueError(f"Order {order_id} has no Kraken txid")

        private_request("/0/private/CancelOrder", {"txid": txid})

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(timezone.utc)
        log.info("Order cancelled: %s (kraken txid %s)", order_id, txid)
        return order

    def get_order(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(f"Order {order_id} not found in local cache")

        txid = order.metadata.get("kraken_txid")
        if txid is None:
            return order

        result = private_request("/0/private/QueryOrders", {"txid": txid})

        if txid in result:
            info = result[txid]
            order.status = _map_order_status(info.get("status", ""))
            order.filled_quantity = Decimal(info.get("vol_exec", "0"))
            avg_price = info.get("price")
            if avg_price and avg_price != "0.00000":
                order.average_fill_price = Decimal(avg_price)
            order.updated_at = datetime.now(timezone.utc)

        return order

    def get_open_orders(self, instrument: Instrument | None = None) -> list[Order]:
        result = private_request("/0/private/OpenOrders")
        open_orders_data = result.get("open", {})

        orders = []
        for txid, info in open_orders_data.items():
            local_id = self._kraken_to_local.get(txid)
            if local_id and local_id in self._orders:
                order = self._orders[local_id]
                order.status = OrderStatus.OPEN
                orders.append(order)

        if instrument is not None:
            orders = [o for o in orders if o.instrument.symbol == instrument.symbol]

        return orders

    def get_position(self, instrument: Instrument) -> Position | None:
        """Derive position from base currency balance.

        Kraken spot has no native "position" concept. Position is inferred
        from the base currency balance (e.g., XXBT balance for BTC/USD).
        """
        result = private_request("/0/private/Balance")

        keys_to_check = KRAKEN_BALANCE_KEYS.get(instrument.base, [instrument.base])

        balance = Decimal("0")
        for key in keys_to_check:
            if key in result:
                balance = Decimal(result[key])
                break

        if balance <= 0:
            return None

        return Position(
            instrument=instrument,
            side=OrderSide.BUY,
            quantity=balance,
            entry_price=Decimal("0"),  # Cannot determine from balance alone
            opened_at=datetime.now(timezone.utc),
            last_updated=datetime.now(timezone.utc),
        )

    def get_positions(self) -> list[Position]:
        result = private_request("/0/private/Balance")
        positions = []
        for key, val in result.items():
            balance = Decimal(val)
            if balance > 0 and key not in ("ZUSD", "USD"):
                positions.append(Position(
                    instrument=Instrument(
                        symbol=f"{key}/USD",
                        base=key,
                        quote="USD",
                        exchange="kraken",
                        asset_class="crypto",
                        tick_size=Decimal("0.01"),
                        lot_size=Decimal("0.00001"),
                        min_notional=Decimal("5"),
                    ),
                    side=OrderSide.BUY,
                    quantity=balance,
                    entry_price=Decimal("0"),
                ))
        return positions

    def get_account(self) -> Account:
        balances_raw = private_request("/0/private/Balance")
        trade_balance = private_request("/0/private/TradeBalance")

        balances = {}
        for key, val in balances_raw.items():
            d = Decimal(val)
            if d != 0:
                balances[key] = d

        equity = Decimal(trade_balance.get("eb", "0"))
        margin_used = Decimal(trade_balance.get("m", "0"))
        unrealized = Decimal(trade_balance.get("n", "0"))

        return Account(
            balances=balances,
            equity=equity,
            margin_used=margin_used,
            margin_available=equity - margin_used,
            unrealized_pnl=unrealized,
        )


def _map_order_status(kraken_status: str) -> OrderStatus:
    mapping = {
        "pending": OrderStatus.PENDING,
        "open": OrderStatus.OPEN,
        "closed": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELLED,
        "expired": OrderStatus.CANCELLED,
    }
    return mapping.get(kraken_status, OrderStatus.PENDING)
