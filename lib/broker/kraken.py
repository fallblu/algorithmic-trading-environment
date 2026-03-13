"""KrakenBroker — live order execution via Kraken REST API."""

from __future__ import annotations

import hashlib
import hmac
import base64
import logging
import time
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import requests

from broker.base import Account, Broker
from models.fill import Fill
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.position import Position, PositionSide

log = logging.getLogger(__name__)

BASE_URL = "https://api.kraken.com"

SYMBOL_MAP = {
    "BTC/USD": "XXBTZUSD",
    "ETH/USD": "XETHZUSD",
    "SOL/USD": "SOLUSD",
    "XRP/USD": "XXRPZUSD",
    "ADA/USD": "ADAUSD",
    "DOT/USD": "DOTUSD",
    "AVAX/USD": "AVAXUSD",
    "LINK/USD": "LINKUSD",
}


class KrakenBroker(Broker):
    """Live Kraken exchange broker.

    Uses Decimal at the API boundary for precision, converts back
    to float for internal model compatibility.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        tick_size: float = 0.1,
        lot_size: float = 0.001,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._tick_size = Decimal(str(tick_size))
        self._lot_size = Decimal(str(lot_size))
        self._orders: dict[str, Order] = {}
        self._fills: list[Fill] = []

    def submit_order(self, order: Order) -> str:
        """Submit order to Kraken REST API."""
        pair = SYMBOL_MAP.get(order.symbol, order.symbol.replace("/", ""))
        qty = Decimal(str(order.quantity)).quantize(self._lot_size)

        params = {
            "pair": pair,
            "type": "buy" if order.side == OrderSide.BUY else "sell",
            "ordertype": "market" if order.type == OrderType.MARKET else "limit",
            "volume": str(qty),
        }

        if order.type == OrderType.LIMIT and order.price is not None:
            price = Decimal(str(order.price)).quantize(self._tick_size)
            params["price"] = str(price)

        try:
            resp = self._private_request("/0/private/AddOrder", params)
            txids = resp.get("txid", [])
            if txids:
                order.status = OrderStatus.OPEN
                self._orders[order.id] = order
                log.info("Order submitted to Kraken: %s -> %s", order.id, txids)
                return order.id
            else:
                order.status = OrderStatus.REJECTED
                log.error("Kraken order rejected: %s", resp)
                return order.id
        except Exception as e:
            order.status = OrderStatus.REJECTED
            log.error("Failed to submit order to Kraken: %s", e)
            raise

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order on Kraken."""
        if order_id not in self._orders:
            return False
        try:
            self._private_request("/0/private/CancelOrder", {"txid": order_id})
            order = self._orders[order_id]
            order.status = OrderStatus.CANCELLED
            return True
        except Exception as e:
            log.error("Failed to cancel order %s: %s", order_id, e)
            return False

    def get_positions(self) -> list[Position]:
        """Get open positions from Kraken."""
        try:
            resp = self._private_request("/0/private/OpenPositions", {})
            positions = []
            for pos_id, pos_data in resp.items():
                symbol = self._reverse_symbol(pos_data.get("pair", ""))
                vol = float(pos_data.get("vol", 0))
                cost = float(pos_data.get("cost", 0))
                avg_price = cost / vol if vol > 0 else 0
                side = PositionSide.LONG if pos_data.get("type") == "buy" else PositionSide.SHORT
                unrealized = float(pos_data.get("net", 0))

                positions.append(Position(
                    symbol=symbol,
                    side=side,
                    quantity=vol,
                    avg_entry_price=avg_price,
                    unrealized_pnl=unrealized,
                ))
            return positions
        except Exception as e:
            log.error("Failed to get positions: %s", e)
            return []

    def get_open_orders(self) -> list[Order]:
        """Get open orders from Kraken."""
        try:
            resp = self._private_request("/0/private/OpenOrders", {})
            orders = []
            for oid, odata in resp.get("open", {}).items():
                desc = odata.get("descr", {})
                orders.append(Order(
                    symbol=self._reverse_symbol(desc.get("pair", "")),
                    side=OrderSide.BUY if desc.get("type") == "buy" else OrderSide.SELL,
                    type=OrderType.LIMIT if desc.get("ordertype") == "limit" else OrderType.MARKET,
                    quantity=float(odata.get("vol", 0)),
                    price=float(desc.get("price", 0)) or None,
                ))
            return orders
        except Exception as e:
            log.error("Failed to get open orders: %s", e)
            return []

    def get_account(self) -> Account:
        """Get account balance from Kraken."""
        try:
            resp = self._private_request("/0/private/Balance", {})
            # Sum all balances as equity estimate
            total = sum(float(v) for v in resp.values())
            return Account(cash=total, equity=total)
        except Exception as e:
            log.error("Failed to get account: %s", e)
            return Account()

    def get_fills(self, since: datetime | None = None) -> list[Fill]:
        """Get trade history from Kraken."""
        try:
            params = {}
            if since:
                params["start"] = str(int(since.timestamp()))
            resp = self._private_request("/0/private/TradesHistory", params)
            fills = []
            for tid, tdata in resp.get("trades", {}).items():
                fills.append(Fill(
                    order_id=tdata.get("ordertxid", ""),
                    symbol=self._reverse_symbol(tdata.get("pair", "")),
                    side=OrderSide.BUY if tdata.get("type") == "buy" else OrderSide.SELL,
                    quantity=float(tdata.get("vol", 0)),
                    price=float(tdata.get("price", 0)),
                    fee=float(tdata.get("fee", 0)),
                    timestamp=datetime.fromtimestamp(
                        float(tdata.get("time", 0)), tz=timezone.utc
                    ),
                ))
            return fills
        except Exception as e:
            log.error("Failed to get fills: %s", e)
            return []

    def _private_request(self, path: str, params: dict) -> dict:
        """Make authenticated Kraken API request."""
        params["nonce"] = str(int(time.time() * 1000))
        post_data = urllib.parse.urlencode(params)

        # Create signature
        encoded = (str(params["nonce"]) + post_data).encode()
        message = path.encode() + hashlib.sha256(encoded).digest()
        signature = hmac.new(
            base64.b64decode(self._api_secret), message, hashlib.sha512
        )
        sig_b64 = base64.b64encode(signature.digest()).decode()

        headers = {
            "API-Key": self._api_key,
            "API-Sign": sig_b64,
        }

        resp = requests.post(f"{BASE_URL}{path}", data=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            raise RuntimeError(f"Kraken API error: {data['error']}")

        return data.get("result", {})

    def _reverse_symbol(self, pair: str) -> str:
        """Convert Kraken pair back to normalized symbol."""
        reverse = {v: k for k, v in SYMBOL_MAP.items()}
        return reverse.get(pair, pair)
