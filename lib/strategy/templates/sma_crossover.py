"""SMA Crossover Strategy — trend-following with fast/slow moving average crossover.

Parameters:
    fast_period (int): Fast SMA period. Default: 10.
    slow_period (int): Slow SMA period. Default: 30.
    symbol (str): Symbol to trade. Default: "BTC/USD".
    quantity (float): Order quantity. Default: 0.01.
"""

from models.order import Order, OrderSide, OrderType


def on_bar(bars, positions, params):
    fast = params.get("fast_period", 10)
    slow = params.get("slow_period", 30)
    symbol = params.get("symbol", "BTC/USD")
    quantity = params.get("quantity", 0.01)

    if len(bars) < slow:
        return []

    closes = bars["close"]
    fast_sma = closes.rolling(fast).mean()
    slow_sma = closes.rolling(slow).mean()

    current_fast = fast_sma.iloc[-1]
    current_slow = slow_sma.iloc[-1]
    prev_fast = fast_sma.iloc[-2]
    prev_slow = slow_sma.iloc[-2]

    orders = []
    pos_qty = positions.get(symbol, 0.0)

    # Golden cross: fast crosses above slow -> buy
    if prev_fast <= prev_slow and current_fast > current_slow:
        if pos_qty <= 0:
            orders.append(Order(
                symbol=symbol,
                side=OrderSide.BUY,
                type=OrderType.MARKET,
                quantity=quantity,
            ))

    # Death cross: fast crosses below slow -> sell
    if prev_fast >= prev_slow and current_fast < current_slow:
        if pos_qty > 0:
            orders.append(Order(
                symbol=symbol,
                side=OrderSide.SELL,
                type=OrderType.MARKET,
                quantity=pos_qty,
            ))

    return orders
