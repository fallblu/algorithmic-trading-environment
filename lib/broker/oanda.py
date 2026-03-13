"""OandaBroker — live order execution via OANDA REST API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import requests

from broker.base import Account, Broker
from models.fill import Fill
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.position import Position, PositionSide

log = logging.getLogger(__name__)

BASE_URL = "https://api-fxpractice.oanda.com/v3"

SYMBOL_MAP = {
    "EUR/USD": "EUR_USD",
    "GBP/USD": "GBP_USD",
    "USD/JPY": "USD_JPY",
    "AUD/USD": "AUD_USD",
    "USD/CAD": "USD_CAD",
    "NZD/USD": "NZD_USD",
    "USD/CHF": "USD_CHF",
    "EUR/GBP": "EUR_GBP",
    "EUR/JPY": "EUR_JPY",
    "GBP/JPY": "GBP_JPY",
}


class OandaBroker(Broker):
    """Live OANDA exchange broker.

    Uses Decimal at the API boundary for precision, converts back
    to float for internal model compatibility.
    """

    def __init__(
        self,
        api_key: str,
        account_id: str,
        tick_size: float = 0.00001,
        lot_size: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._account_id = account_id
        self._tick_size = Decimal(str(tick_size))
        self._lot_size = Decimal(str(lot_size))
        self._orders: dict[str, Order] = {}

    def submit_order(self, order: Order) -> str:
        """Submit order to OANDA REST API."""
        instrument = SYMBOL_MAP.get(order.symbol, order.symbol.replace("/", "_"))
        qty = Decimal(str(order.quantity)).quantize(self._lot_size)

        # OANDA uses negative units for sell
        units = str(qty) if order.side == OrderSide.BUY else str(-qty)

        if order.type == OrderType.MARKET:
            body = {
                "order": {
                    "type": "MARKET",
                    "instrument": instrument,
                    "units": units,
                    "timeInForce": "FOK",
                }
            }
        else:
            price = Decimal(str(order.price)).quantize(self._tick_size)
            body = {
                "order": {
                    "type": "LIMIT",
                    "instrument": instrument,
                    "units": units,
                    "price": str(price),
                    "timeInForce": "GTC",
                }
            }

        try:
            resp = self._request("POST", f"/accounts/{self._account_id}/orders", json=body)
            if "orderFillTransaction" in resp:
                order.status = OrderStatus.FILLED
                fill_tx = resp["orderFillTransaction"]
                order.fill_price = float(fill_tx.get("price", 0))
                order.filled_quantity = abs(float(fill_tx.get("units", 0)))
            elif "orderCreateTransaction" in resp:
                order.status = OrderStatus.OPEN
            else:
                order.status = OrderStatus.REJECTED

            self._orders[order.id] = order
            return order.id
        except Exception as e:
            order.status = OrderStatus.REJECTED
            log.error("Failed to submit order to OANDA: %s", e)
            raise

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order on OANDA."""
        try:
            self._request("PUT", f"/accounts/{self._account_id}/orders/{order_id}/cancel")
            if order_id in self._orders:
                self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        except Exception as e:
            log.error("Failed to cancel order %s: %s", order_id, e)
            return False

    def get_positions(self) -> list[Position]:
        """Get open positions from OANDA."""
        try:
            resp = self._request("GET", f"/accounts/{self._account_id}/openPositions")
            positions = []
            for pos_data in resp.get("positions", []):
                instrument = pos_data.get("instrument", "").replace("_", "/")
                long_units = float(pos_data.get("long", {}).get("units", 0))
                short_units = abs(float(pos_data.get("short", {}).get("units", 0)))

                if long_units > 0:
                    avg_price = float(pos_data.get("long", {}).get("averagePrice", 0))
                    unrealized = float(pos_data.get("long", {}).get("unrealizedPL", 0))
                    positions.append(Position(
                        symbol=instrument,
                        side=PositionSide.LONG,
                        quantity=long_units,
                        avg_entry_price=avg_price,
                        unrealized_pnl=unrealized,
                    ))
                if short_units > 0:
                    avg_price = float(pos_data.get("short", {}).get("averagePrice", 0))
                    unrealized = float(pos_data.get("short", {}).get("unrealizedPL", 0))
                    positions.append(Position(
                        symbol=instrument,
                        side=PositionSide.SHORT,
                        quantity=short_units,
                        avg_entry_price=avg_price,
                        unrealized_pnl=unrealized,
                    ))
            return positions
        except Exception as e:
            log.error("Failed to get positions: %s", e)
            return []

    def get_open_orders(self) -> list[Order]:
        """Get pending orders from OANDA."""
        try:
            resp = self._request("GET", f"/accounts/{self._account_id}/pendingOrders")
            orders = []
            for odata in resp.get("orders", []):
                units = float(odata.get("units", 0))
                orders.append(Order(
                    symbol=odata.get("instrument", "").replace("_", "/"),
                    side=OrderSide.BUY if units > 0 else OrderSide.SELL,
                    type=OrderType.LIMIT if odata.get("type") == "LIMIT" else OrderType.MARKET,
                    quantity=abs(units),
                    price=float(odata.get("price", 0)) or None,
                ))
            return orders
        except Exception as e:
            log.error("Failed to get open orders: %s", e)
            return []

    def get_account(self) -> Account:
        """Get account summary from OANDA."""
        try:
            resp = self._request("GET", f"/accounts/{self._account_id}/summary")
            acct = resp.get("account", {})
            return Account(
                cash=float(acct.get("balance", 0)),
                equity=float(acct.get("NAV", 0)),
                unrealized_pnl=float(acct.get("unrealizedPL", 0)),
                realized_pnl=float(acct.get("pl", 0)),
            )
        except Exception as e:
            log.error("Failed to get account: %s", e)
            return Account()

    def get_fills(self, since: datetime | None = None) -> list[Fill]:
        """Get trade fills from OANDA."""
        try:
            params = {"type": "ORDER_FILL", "count": 100}
            if since:
                params["from"] = since.isoformat()
            resp = self._request(
                "GET", f"/accounts/{self._account_id}/transactions", params=params
            )
            fills = []
            for tx in resp.get("transactions", []):
                if tx.get("type") != "ORDER_FILL":
                    continue
                units = float(tx.get("units", 0))
                fills.append(Fill(
                    order_id=tx.get("orderID", ""),
                    symbol=tx.get("instrument", "").replace("_", "/"),
                    side=OrderSide.BUY if units > 0 else OrderSide.SELL,
                    quantity=abs(units),
                    price=float(tx.get("price", 0)),
                    fee=abs(float(tx.get("commission", 0))),
                    timestamp=datetime.fromisoformat(
                        tx.get("time", "").replace("Z", "+00:00")
                    ),
                ))
            return fills
        except Exception as e:
            log.error("Failed to get fills: %s", e)
            return []

    def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Make authenticated OANDA API request."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.request(
            method, f"{BASE_URL}{path}", headers=headers, json=json, params=params, timeout=30
        )
        resp.raise_for_status()
        return resp.json()
