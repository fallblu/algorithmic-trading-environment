"""Mean Reversion Strategy — Bollinger Bands + RSI for oversold/overbought detection.

Parameters:
    symbol (str): Symbol to trade. Default: "BTC/USD".
    bb_length (int): Bollinger Bands period. Default: 20.
    bb_std (float): Bollinger Bands std multiplier. Default: 2.0.
    rsi_length (int): RSI period. Default: 14.
    rsi_oversold (float): RSI oversold threshold. Default: 30.
    rsi_overbought (float): RSI overbought threshold. Default: 70.
    quantity (float): Order quantity. Default: 0.01.
"""

import pandas_ta as ta

from models.order import Order, OrderSide, OrderType


def on_bar(bars, positions, params):
    symbol = params.get("symbol", "BTC/USD")
    bb_length = params.get("bb_length", 20)
    bb_std = params.get("bb_std", 2.0)
    rsi_length = params.get("rsi_length", 14)
    rsi_oversold = params.get("rsi_oversold", 30)
    rsi_overbought = params.get("rsi_overbought", 70)
    quantity = params.get("quantity", 0.01)

    min_bars = max(bb_length, rsi_length) + 5
    if len(bars) < min_bars:
        return []

    closes = bars["close"]

    # Compute RSI
    rsi_series = ta.rsi(closes, length=rsi_length)
    rsi = rsi_series.iloc[-1]

    # Compute Bollinger Bands
    bbands = ta.bbands(closes, length=bb_length, std=bb_std)
    lower_col = f"BBL_{bb_length}_{bb_std}"
    upper_col = f"BBU_{bb_length}_{bb_std}"
    lower = bbands[lower_col].iloc[-1]
    upper = bbands[upper_col].iloc[-1]

    price = closes.iloc[-1]
    pos_qty = positions.get(symbol, 0.0)

    orders = []

    # Buy when price below lower band and RSI oversold
    if price < lower and rsi < rsi_oversold and pos_qty <= 0:
        orders.append(Order(
            symbol=symbol,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=quantity,
        ))

    # Sell when price above upper band and RSI overbought
    if price > upper and rsi > rsi_overbought and pos_qty > 0:
        orders.append(Order(
            symbol=symbol,
            side=OrderSide.SELL,
            type=OrderType.MARKET,
            quantity=pos_qty,
        ))

    return orders
