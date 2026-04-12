"""
Gestión de riesgo multi-activo con soporte LONG y SHORT.

SHORT stops:
  stop_loss   → precio SOBRE el que se cierra (precio sube contra el corto)
  take_profit → precio BAJO el que se cierra (precio baja a favor del corto)
  trailing    → rastrea el mínimo histórico (trailing_high almacena el low)
"""
from config import (
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_OPEN_POSITIONS,
    MAX_EXPOSURE_CRYPTO, MAX_EXPOSURE_COMMODITY, MAX_EXPOSURE_INTL,
    CRYPTO, COMMODITIES, INTERNATIONAL,
    TRAILING_STOP_PCT, TRAILING_STOP_ACTIVATION,
    SECTOR_MAP, MAX_POSITIONS_PER_SECTOR,
    SHORT_ENABLED,
    get_asset_class, get_asset_params,
)
from modules.portfolio import (
    get_cash, get_positions, get_equity,
    update_trailing_high, set_cooldown, is_in_cooldown,
)
from modules.market_regime import get_market_regime

# Sizing según régimen — para LONG
_REGIME_SIZE_LONG  = {"bull": 2.0, "neutral": 1.0, "bear": 0.5}
# Sizing para SHORT — en BEAR es donde más se gana en corto
_REGIME_SIZE_SHORT = {"bull": 0.5, "neutral": 1.0, "bear": 1.5}

# ── Daily loss circuit breaker ────────────────────────────────────────────
# Detiene TODAS las nuevas entradas si la pérdida del día supera este % del equity.
MAX_DAILY_LOSS_PCT = 0.03   # 3 % del equity de inicio de sesión

_daily_loss_state: dict = {
    "date":             None,
    "starting_equity":  None,
    "halted":           False,
}


def check_daily_loss_limit(current_equity: float) -> bool:
    """
    Retorna True si se ha alcanzado el límite de pérdida diaria.
    Se resetea automáticamente al inicio de cada día UTC.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    from datetime import date
    today = date.today()

    if _daily_loss_state["date"] != today:
        # Nuevo día — resetear estado
        _daily_loss_state.update({
            "date":            today,
            "starting_equity": current_equity,
            "halted":          False,
        })

    if _daily_loss_state["halted"]:
        return True

    starting = _daily_loss_state["starting_equity"] or current_equity
    if starting <= 0:
        return False

    loss_pct = (starting - current_equity) / starting

    if loss_pct >= MAX_DAILY_LOSS_PCT:
        _daily_loss_state["halted"] = True
        _log.warning(
            f"[DAILY LOSS LIMIT] Pérdida {loss_pct:.1%} ≥ {MAX_DAILY_LOSS_PCT:.0%} "
            f"del equity — nuevas entradas bloqueadas por hoy."
        )
        return True

    return False


def calc_position_size(ticker: str, price: float, current_prices: dict,
                       side: str = "LONG") -> float:
    """Calcula cantidad a comprar/shortar respetando límites de clase, cash y régimen."""
    if price <= 0:
        return 0.0

    equity = get_equity(current_prices)
    cash   = get_cash()
    params = get_asset_params(ticker)

    try:
        regime = get_market_regime()
        if side == "SHORT":
            size_mult = _REGIME_SIZE_SHORT.get(regime["regime"], 1.0)
        else:
            size_mult = _REGIME_SIZE_LONG.get(regime["regime"], 1.0)
    except Exception:
        size_mult = 1.0

    max_dollars = min(equity * params["max_pos"] * size_mult, cash * 0.95)

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
    """Stop-loss y take-profit para posición LONG (stop bajo, TP sobre)."""
    params = get_asset_params(ticker)

    atr_stop    = atr * 1.5
    fixed_stop  = price * params["stop"]
    stop_loss   = price - max(atr_stop, fixed_stop)

    atr_tp      = atr * 3.0
    fixed_tp    = price * params["tp"]
    take_profit = price + max(atr_tp, fixed_tp)

    return round(stop_loss, 6), round(take_profit, 6)


def calc_stops_short(ticker: str, price: float, atr: float) -> tuple[float, float]:
    """Stop-loss y take-profit para posición SHORT.
    stop_loss   → SOBRE el precio de entrada (precio sube = pérdida)
    take_profit → BAJO el precio de entrada (precio baja = ganancia)
    """
    params = get_asset_params(ticker)

    atr_stop    = atr * 1.5
    fixed_stop  = price * params["stop"]
    stop_loss   = price + max(atr_stop, fixed_stop)   # ← encima

    atr_tp      = atr * 3.0
    fixed_tp    = price * params["tp"]
    take_profit = price - max(atr_tp, fixed_tp)       # ← debajo
    take_profit = max(take_profit, price * 0.01)       # nunca negativo

    return round(stop_loss, 6), round(take_profit, 6)


def can_open_position(ticker: str, current_prices: dict | None = None,
                      side: str = "LONG") -> tuple[bool, str]:
    """Verifica si se puede abrir posición (LONG o SHORT) en el ticker."""
    if side == "SHORT" and not SHORT_ENABLED:
        return False, "SHORT deshabilitado en config"

    # ── Daily loss circuit breaker ────────────────────────────────────────
    if current_prices:
        equity = get_equity(current_prices)
        if check_daily_loss_limit(equity):
            return False, "daily loss limit alcanzado — sin nuevas entradas hoy"

    positions    = get_positions()
    tickers_held = [p["ticker"] for p in positions]

    if ticker in tickers_held:
        pos = next(p for p in positions if p["ticker"] == ticker)
        if pos["side"] == side:
            return False, f"ya tenemos posición {side} abierta"
        # Posición en la dirección contraria: no abrir nueva sin cerrar
        return False, f"posición {pos['side']} activa — ciérrala antes de abrir {side}"

    if len(positions) >= MAX_OPEN_POSITIONS:
        return False, f"máximo de {MAX_OPEN_POSITIONS} posiciones alcanzado"
    if get_cash() < 50:
        return False, "cash insuficiente (<$50)"

    if is_in_cooldown(ticker):
        return False, "en cooldown (stop-loss reciente)"

    sector = SECTOR_MAP.get(ticker, "screener")
    same_sector = [
        p for p in positions
        if SECTOR_MAP.get(p["ticker"], "screener") == sector
    ]
    if len(same_sector) >= MAX_POSITIONS_PER_SECTOR:
        return False, (
            f"límite sectorial '{sector}' alcanzado "
            f"({len(same_sector)}/{MAX_POSITIONS_PER_SECTOR})"
        )

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

    LONG:  stop si precio ≤ stop_loss | TP si precio ≥ take_profit
           trailing_high = máximo alcanzado, cierra si cae X% bajo ese máximo
    SHORT: stop si precio ≥ stop_loss | TP si precio ≤ take_profit
           trailing_high = mínimo alcanzado, cierra si sube X% sobre ese mínimo
    """
    to_close = []

    for pos in get_positions():
        ticker = pos["ticker"]
        price  = current_prices.get(ticker)
        if not price:
            continue

        side      = pos.get("side", "LONG")
        avg_price = pos["avg_price"]

        # ── Sanity check de precio ────────────────────────────────────────
        # Si el precio recibido difiere más de MAX_MOVE del precio de entrada,
        # es muy probable que sea un dato corrupto (yfinance glitch, feed error).
        # Ignoramos el precio y no ejecutamos ninguna salida.
        params   = get_asset_params(ticker)
        # Permitimos 4× el TP configurado como movimiento máximo creíble en un ciclo
        max_move = params["tp"] * 4.0
        pct_change = abs(price / avg_price - 1) if avg_price > 0 else 0
        if pct_change > max_move:
            logger.warning(
                f"[{ticker}] Precio sospechoso: {price:.4f} vs entrada {avg_price:.4f} "
                f"({pct_change*100:.1f}% > limite {max_move*100:.0f}%) "
                f"— salida ignorada, posible dato corrupto"
            )
            continue

        stop_loss   = pos["stop_loss"]
        take_profit = pos["take_profit"]
        asset_class = get_asset_class(ticker)
        trailing_pct = TRAILING_STOP_PCT.get(asset_class, 0.07)
        reason = None

        if side == "SHORT":
            # Para SHORT, trailing_high almacena el mínimo histórico
            trailing_low = pos.get("trailing_high") or avg_price

            # Actualizar mínimo si el precio bajó más
            if price < trailing_low:
                update_trailing_high(ticker, price)
                trailing_low = price

            # Trailing activo cuando el precio cayó > TRAILING_STOP_ACTIVATION desde entrada
            activation     = avg_price * (1 - TRAILING_STOP_ACTIVATION)
            trailing_active = trailing_low <= activation

            if trailing_active:
                trailing_ceiling = trailing_low * (1 + trailing_pct)
                if price >= trailing_ceiling:
                    reason = "trailing_stop"
            elif stop_loss and price >= stop_loss:
                reason = "stop_loss"

            if reason is None and take_profit and price <= take_profit:
                reason = "take_profit"

        else:  # LONG
            trailing_high = pos.get("trailing_high") or avg_price

            if price > trailing_high:
                update_trailing_high(ticker, price)
                trailing_high = price

            activation      = avg_price * (1 + TRAILING_STOP_ACTIVATION)
            trailing_active = trailing_high >= activation

            if trailing_active:
                trailing_floor = trailing_high * (1 - trailing_pct)
                if price <= trailing_floor:
                    reason = "trailing_stop"
            elif stop_loss and price <= stop_loss:
                reason = "stop_loss"

            if reason is None and take_profit and price >= take_profit:
                reason = "take_profit"

        if reason:
            if reason in ("stop_loss", "trailing_stop"):
                set_cooldown(ticker, reason)
            to_close.append({"ticker": ticker, "price": price,
                             "reason": reason, "side": side})

    return to_close


def risk_check_portfolio(current_prices: dict) -> dict:
    """Resumen completo del estado de riesgo del portafolio."""
    equity    = get_equity(current_prices)
    cash      = get_cash()
    positions = get_positions()

    by_class: dict[str, float] = {}
    position_details = []
    for p in positions:
        side  = p.get("side", "LONG")
        price = current_prices.get(p["ticker"], p["avg_price"])
        if side == "SHORT":
            val = p["qty"] * (2 * p["avg_price"] - price)
            unrealized = (p["avg_price"] - price) * p["qty"]
        else:
            val = p["qty"] * price
            unrealized = (price - p["avg_price"]) * p["qty"]

        cls = get_asset_class(p["ticker"])
        by_class[cls] = by_class.get(cls, 0.0) + val

        th  = p.get("trailing_high") or p["avg_price"]
        position_details.append({
            "ticker":         p["ticker"],
            "side":           side,
            "class":          cls,
            "unrealized_pnl": round(unrealized, 2),
            "pnl_pct":        round((price / p["avg_price"] - 1) * 100 * (1 if side == "LONG" else -1), 2),
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
