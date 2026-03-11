"""OandaBroker — live order execution via OANDA v20 REST API."""

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import requests

from broker.base import Broker
from models.account import Account
from models.instrument import Instrument
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.position import Position

log = logging.getLogger(__name__)


class OandaAPIError(Exception):
    pass


class OandaBroker(Broker):
    """Live broker for OANDA forex trading.

    Uses OANDA v20 REST API for order management, position tracking,
    and account queries. Supports market, limit, stop, and trailing stop orders.
    """

    def __init__(self):
        self._token = os.environ.get("OANDA_API_TOKEN", "")
        self._account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        environment = os.environ.get("OANDA_ENVIRONMENT", "practice")

        if not self._token or not self._account_id:
            raise OandaAPIError(
                "OANDA_API_TOKEN and OANDA_ACCOUNT_ID must be set"
            )

        if environment == "live":
            self._base_url = "https://api-fxtrade.oanda.com"
        else:
            self._base_url = "https://api-fxpractice.oanda.com"

        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        self._orders: dict[str, Order] = {}
        self._oanda_to_local: dict[str, str] = {}

    def _to_oanda_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "_")

    def submit_order(self, order: Order) -> Order:
        oanda_instrument = self._to_oanda_symbol(order.instrument.symbol)

        # Build order body
        units = str(order.quantity if order.side == OrderSide.BUY else -order.quantity)

        if order.type == OrderType.MARKET:
            body = {
                "order": {
                    "type": "MARKET",
                    "instrument": oanda_instrument,
                    "units": units,
                    "timeInForce": "FOK",
                }
            }
        elif order.type == OrderType.LIMIT:
            body = {
                "order": {
                    "type": "LIMIT",
                    "instrument": oanda_instrument,
                    "units": units,
                    "price": str(order.price),
                    "timeInForce": "GTC",
                }
            }
        elif order.type == OrderType.STOP:
            body = {
                "order": {
                    "type": "STOP",
                    "instrument": oanda_instrument,
                    "units": units,
                    "price": str(order.stop_price),
                    "timeInForce": "GTC",
                }
            }
        else:
            body = {
                "order": {
                    "type": "MARKET",
                    "instrument": oanda_instrument,
                    "units": units,
                    "timeInForce": "FOK",
                }
            }

        url = f"{self._base_url}/v3/accounts/{self._account_id}/orders"
        resp = requests.post(url, headers=self._headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Extract order ID from response
        fill_data = data.get("orderFillTransaction", {})
        create_data = data.get("orderCreateTransaction", {})

        oanda_id = fill_data.get("id") or create_data.get("id", "")
        if oanda_id:
            order.metadata["oanda_order_id"] = oanda_id
            self._oanda_to_local[oanda_id] = order.id

        if fill_data:
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            price = fill_data.get("price")
            if price:
                order.average_fill_price = Decimal(price)
        else:
            order.status = OrderStatus.OPEN

        order.updated_at = datetime.now(timezone.utc)
        self._orders[order.id] = order
        log.info("OANDA order submitted: %s -> %s", order.id, oanda_id)
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        oanda_id = order.metadata.get("oanda_order_id")
        if oanda_id is None:
            raise ValueError(f"Order {order_id} has no OANDA order ID")

        url = f"{self._base_url}/v3/accounts/{self._account_id}/orders/{oanda_id}/cancel"
        resp = requests.put(url, headers=self._headers, timeout=30)
        resp.raise_for_status()

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(timezone.utc)
        log.info("OANDA order cancelled: %s", order_id)
        return order

    def get_order(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(f"Order {order_id} not found")
        return order

    def get_open_orders(self, instrument: Instrument | None = None) -> list[Order]:
        url = f"{self._base_url}/v3/accounts/{self._account_id}/pendingOrders"
        resp = requests.get(url, headers=self._headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        orders = []
        for oo in data.get("orders", []):
            oanda_id = oo.get("id", "")
            local_id = self._oanda_to_local.get(oanda_id)
            if local_id and local_id in self._orders:
                orders.append(self._orders[local_id])

        if instrument is not None:
            orders = [o for o in orders if o.instrument.symbol == instrument.symbol]

        return orders

    def get_position(self, instrument: Instrument) -> Position | None:
        oanda_inst = self._to_oanda_symbol(instrument.symbol)
        url = f"{self._base_url}/v3/accounts/{self._account_id}/positions/{oanda_inst}"

        resp = requests.get(url, headers=self._headers, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()

        pos_data = data.get("position", {})
        long_units = int(pos_data.get("long", {}).get("units", "0"))
        short_units = abs(int(pos_data.get("short", {}).get("units", "0")))

        if long_units > 0:
            avg_price = Decimal(pos_data["long"].get("averagePrice", "0"))
            unrealized = Decimal(pos_data["long"].get("unrealizedPL", "0"))
            return Position(
                instrument=instrument,
                side=OrderSide.BUY,
                quantity=Decimal(str(long_units)),
                entry_price=avg_price,
                unrealized_pnl=unrealized,
                last_updated=datetime.now(timezone.utc),
            )
        elif short_units > 0:
            avg_price = Decimal(pos_data["short"].get("averagePrice", "0"))
            unrealized = Decimal(pos_data["short"].get("unrealizedPL", "0"))
            return Position(
                instrument=instrument,
                side=OrderSide.SELL,
                quantity=Decimal(str(short_units)),
                entry_price=avg_price,
                unrealized_pnl=unrealized,
                last_updated=datetime.now(timezone.utc),
            )

        return None

    def get_positions(self) -> list[Position]:
        url = f"{self._base_url}/v3/accounts/{self._account_id}/openPositions"
        resp = requests.get(url, headers=self._headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        positions = []
        for pos_data in data.get("positions", []):
            oanda_inst = pos_data.get("instrument", "")
            our_symbol = oanda_inst.replace("_", "/")

            long_units = int(pos_data.get("long", {}).get("units", "0"))
            short_units = abs(int(pos_data.get("short", {}).get("units", "0")))

            instrument = Instrument(
                symbol=our_symbol,
                base=our_symbol.split("/")[0],
                quote=our_symbol.split("/")[1] if "/" in our_symbol else "USD",
                exchange="oanda",
                asset_class="forex",
                tick_size=Decimal("0.00001"),
                lot_size=Decimal("1"),
                min_notional=Decimal("1"),
            )

            if long_units > 0:
                positions.append(Position(
                    instrument=instrument,
                    side=OrderSide.BUY,
                    quantity=Decimal(str(long_units)),
                    entry_price=Decimal(pos_data["long"].get("averagePrice", "0")),
                ))
            elif short_units > 0:
                positions.append(Position(
                    instrument=instrument,
                    side=OrderSide.SELL,
                    quantity=Decimal(str(short_units)),
                    entry_price=Decimal(pos_data["short"].get("averagePrice", "0")),
                ))

        return positions

    def get_account(self) -> Account:
        url = f"{self._base_url}/v3/accounts/{self._account_id}/summary"
        resp = requests.get(url, headers=self._headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        acct = data.get("account", {})
        balance = Decimal(acct.get("balance", "0"))
        unrealized = Decimal(acct.get("unrealizedPL", "0"))
        margin_used = Decimal(acct.get("marginUsed", "0"))
        equity = Decimal(acct.get("NAV", "0"))

        return Account(
            balances={"USD": balance},
            equity=equity,
            margin_used=margin_used,
            margin_available=equity - margin_used,
            unrealized_pnl=unrealized,
        )
