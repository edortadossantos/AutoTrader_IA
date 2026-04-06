"""
Gestión de riesgo multi-activo.

Mejoras implementadas:
  - Trailing stop-loss: sigue el precio hacia arriba, cierra X% bajo el máximo
  - Cooldown post stop-loss: bloquea re-entrada tras ser parado
  - Check de correlación sectorial: máx MAX_POSITIONS_PER_SECTOR por sector
"""
from config import (
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_OPEN_POSITIONS,
    MAX_EXPOSURE_CRYPTO, MAX_EXPOSURE_COMMODITY, MAX_EXPOSURE_INTL,
    CRYPTO, COMMODITIES, INTERNATIONAL,
    TRAILING_STOP_PCT, TRAILING_STOP_ACTIVATION,
    SECTOR_MAP, MAX_POSITIONS_PER_SECTOR,
    get_asset_class, get_asset_params,
)
from modules.portfolio import (
    get_cash, get_positions, get_equity,
    update_trailing_high, set_cooldown, is_in_cooldown,
)


def calc_position_size(ticker: str, price: float, current_prices: dict) -> float:
    """
    Calcula cantidad a comprar respetando:
      1. Límite de posición por clase de activo
      2. Límite de exposición total por clase
      3. Cash disponible
    """
    if price <= 0:
        return 0.0

    equity = get_equity(current_prices)
    cash   = get_cash()
    params = get_asset_params(ticker)

    max_dollars = min(equity * params["max_pos"], cash * 0.95)

    asset_class = get_asset_class(ticker)
    positions   = get_positions()

    class_exposure = sum(
        p["qty"] * current_prices.get(p["ticker"], p["avg_price"])
        for p in positions
        if get_asset_class(p["ticker"]) == asset_class
    )

    class_limit_map = {
        "crypto":    MAX_EXPOSURE_CRYPTO    * equity,
        "commodity": MAX_EXPOSURE_COMMODITY * equity,
        "intl":      MAX_EXPOSURE_INTL      * equity,
        "etf":       equity * 0.40,
        "stock":     equity * 0.60,
    }
    class_limit     = class_limit_map.get(asset_class, equity * 0.50)
    class_remaining = max(0.0, class_limit - class_exposure)

    max_dollars = min(max_dollars, class_remaining)

    if max_dollars < price:
        return 0.0
    return round(max_dollars / price, 6)


def calc_stops(ticker: str, price: float, atr: float) -> tuple[float, float]:
    """
    Stop-loss y take-profit dinámicos basados en ATR + parámetros de clase.
    """
    params = get_asset_params(ticker)

    atr_stop    = atr * 1.5
    fixed_stop  = price * params["stop"]
    stop_loss   = price - max(atr_stop, fixed_stop)

    atr_tp      = atr * 3.0
    fixed_tp    = price * params["tp"]
    take_profit = price + max(atr_tp, fixed_tp)

    return round(stop_loss, 6), round(take_profit, 6)


def can_open_position(ticker: str, current_prices: dict | None = None) -> tuple[bool, str]:
    """
    Verifica si se puede abrir posición en el ticker.
    Comprueba: posición existente, máx posiciones, cash, exposición por clase,
               correlación sectorial y cooldown post stop-loss.
    """
    positions    = get_positions()
    tickers_held = [p["ticker"] for p in positions]

    if ticker in tickers_held:
        return False, "ya tenemos posición abierta"
    if len(positions) >= MAX_OPEN_POSITIONS:
        return False, f"máximo de {MAX_OPEN_POSITIONS} posiciones alcanzado"
    if get_cash() < 50:
        return False, "cash insuficiente (<$50)"

    # ── Cooldown post stop-loss ───────────────────────────────────
    if is_in_cooldown(ticker):
        return False, "en cooldown (stop-loss reciente)"

    # ── Correlación sectorial ─────────────────────────────────────
    sector = SECTOR_MAP.get(ticker, "screener")
    same_sector = [
        p for p in positions
        if SECTOR_MAP.get(p["ticker"], "screener") == sector
    ]
    if len(same_sector) >= MAX_POSITIONS_PER_SECTOR:
        return False, (
            f"límite sectorial '{sector}' alcanzado "
            f"({len(same_sector)}/{MAX_POSITIONS_PER_SECTOR}): "
            f"{[p['ticker'] for p in same_sector]}"
        )

    # ── Exposición por clase ──────────────────────────────────────
    if current_prices:
        equity      = get_equity(current_prices)
        asset_class = get_asset_class(ticker)
        class_exposure = sum(
            p["qty"] * current_prices.get(p["ticker"], p["avg_price"])
            for p in positions
            if get_asset_class(p["ticker"]) == asset_class
        )
        limits = {
            "crypto":    MAX_EXPOSURE_CRYPTO    * equity,
            "commodity": MAX_EXPOSURE_COMMODITY * equity,
            "intl":      MAX_EXPOSURE_INTL      * equity,
        }
        if asset_class in limits and class_exposure >= limits[asset_class]:
            return False, (
                f"límite de exposición {asset_class} alcanzado "
                f"({class_exposure:.0f}/${limits[asset_class]:.0f})"
            )

    return True, "ok"


def check_exits(current_prices: dict) -> list[dict]:
    """
    Revisa stop-loss, trailing stop y take-profit para todas las posiciones.

    Lógica del trailing stop:
      1. Actualiza trailing_high si el precio actual es mayor
      2. Activa el trailing solo cuando el beneficio supera TRAILING_STOP_ACTIVATION
      3. Cierra si precio < trailing_high * (1 - trailing_pct)
      4. El stop-loss fijo sigue protegiendo ante caídas iniciales
    """
    to_close = []

    for pos in get_positions():
        ticker = pos["ticker"]
        price  = current_prices.get(ticker)
        if not price:
            continue

        avg_price    = pos["avg_price"]
        stop_loss    = pos["stop_loss"]
        take_profit  = pos["take_profit"]
        trailing_high = pos.get("trailing_high") or avg_price

        # ── Actualizar máximo histórico ───────────────────────────
        if price > trailing_high:
            update_trailing_high(ticker, price)
            trailing_high = price

        # ── Trailing stop (solo cuando está en beneficio > umbral) ─
        asset_class   = get_asset_class(ticker)
        trailing_pct  = TRAILING_STOP_PCT.get(asset_class, 0.07)
        activation    = avg_price * (1 + TRAILING_STOP_ACTIVATION)
        trailing_active = trailing_high >= activation

        reason = None

        if trailing_active:
            trailing_floor = trailing_high * (1 - trailing_pct)
            if price <= trailing_floor:
                reason = "trailing_stop"
        elif stop_loss and price <= stop_loss:
            reason = "stop_loss"

        if reason is None and take_profit and price >= take_profit:
            reason = "take_profit"

        if reason:
            # Registrar cooldown si fue un stop (no take-profit)
            if reason in ("stop_loss", "trailing_stop"):
                set_cooldown(ticker, reason)
            to_close.append({"ticker": ticker, "price": price, "reason": reason})

    return to_close


def risk_check_portfolio(current_prices: dict) -> dict:
    """Resumen completo del estado de riesgo del portafolio por clase de activo."""
    equity    = get_equity(current_prices)
    cash      = get_cash()
    positions = get_positions()

    by_class: dict[str, float] = {}
    position_details = []
    for p in positions:
        val = p["qty"] * current_prices.get(p["ticker"], p["avg_price"])
        cls = get_asset_class(p["ticker"])
        by_class[cls] = by_class.get(cls, 0.0) + val

        th  = p.get("trailing_high") or p["avg_price"]
        position_details.append({
            "ticker":         p["ticker"],
            "class":          cls,
            "unrealized_pnl": round((current_prices.get(p["ticker"], p["avg_price"]) - p["avg_price"]) * p["qty"], 2),
            "pnl_pct":        round((current_prices.get(p["ticker"], p["avg_price"]) / p["avg_price"] - 1) * 100, 2),
            "trailing_high":  round(th, 4),
        })

    invested     = sum(by_class.values())
    exposure_pct = invested / equity if equity > 0 else 0

    return {
        "equity":           round(equity, 2),
        "cash":             round(cash, 2),
        "exposure_pct":     round(exposure_pct, 3),
        "open_positions":   len(positions),
        "by_class":         {k: round(v, 2) for k, v in by_class.items()},
        "position_details": position_details,
    }
