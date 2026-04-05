"""
Gestión de riesgo: sizing, stop-loss, take-profit y chequeo de límites.
"""
from config import (
    MAX_POSITION_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    MAX_OPEN_POSITIONS
)
from modules.portfolio import get_cash, get_positions, get_equity


def calc_position_size(price: float, current_prices: dict) -> float:
    """Calcula cuántas acciones comprar según el capital disponible y límite de posición."""
    equity = get_equity(current_prices)
    cash = get_cash()
    max_dollars = min(equity * MAX_POSITION_PCT, cash * 0.95)  # no gastar más del 95% del cash
    if max_dollars < price:
        return 0.0
    qty = max_dollars / price
    return round(qty, 6)


def calc_stops(price: float, atr: float) -> tuple[float, float]:
    """
    Calcula stop-loss y take-profit dinámicos usando ATR.
    Si ATR > stop fijo, usa ATR*1.5 para dar más margen.
    """
    atr_stop = atr * 1.5
    fixed_stop = price * STOP_LOSS_PCT
    stop_loss = price - max(atr_stop, fixed_stop)

    atr_tp = atr * 3.0
    fixed_tp = price * TAKE_PROFIT_PCT
    take_profit = price + max(atr_tp, fixed_tp)

    return round(stop_loss, 4), round(take_profit, 4)


def can_open_position(ticker: str) -> tuple[bool, str]:
    positions = get_positions()
    tickers_held = [p["ticker"] for p in positions]

    if ticker in tickers_held:
        return False, "ya tenemos posición abierta"
    if len(positions) >= MAX_OPEN_POSITIONS:
        return False, f"máximo de {MAX_OPEN_POSITIONS} posiciones alcanzado"
    if get_cash() < 100:
        return False, "cash insuficiente (<$100)"
    return True, "ok"


def check_exits(current_prices: dict) -> list[dict]:
    """
    Revisa si alguna posición abierta ha tocado stop-loss o take-profit.
    Retorna lista de posiciones a cerrar.
    """
    to_close = []
    for pos in get_positions():
        ticker = pos["ticker"]
        price = current_prices.get(ticker)
        if not price:
            continue
        reason = None
        if pos["stop_loss"] and price <= pos["stop_loss"]:
            reason = "stop_loss"
        elif pos["take_profit"] and price >= pos["take_profit"]:
            reason = "take_profit"
        if reason:
            to_close.append({"ticker": ticker, "price": price, "reason": reason})
    return to_close


def risk_check_portfolio(current_prices: dict) -> dict:
    """Resumen del estado de riesgo del portafolio."""
    equity = get_equity(current_prices)
    cash = get_cash()
    positions = get_positions()

    position_values = {
        p["ticker"]: p["qty"] * current_prices.get(p["ticker"], p["avg_price"])
        for p in positions
    }
    exposure_pct = sum(position_values.values()) / equity if equity > 0 else 0

    return {
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "exposure_pct": round(exposure_pct, 3),
        "open_positions": len(positions),
        "position_details": [
            {
                "ticker": p["ticker"],
                "unrealized_pnl": round(
                    (current_prices.get(p["ticker"], p["avg_price"]) - p["avg_price"]) * p["qty"], 2
                ),
                "pnl_pct": round(
                    (current_prices.get(p["ticker"], p["avg_price"]) / p["avg_price"] - 1) * 100, 2
                ),
            }
            for p in positions
        ],
    }
