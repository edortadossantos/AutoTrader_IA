"""
Circuit breaker — protección del capital en 3 niveles.

Nivel 0 — OK:        operar con normalidad
Nivel 1 — WARN:      drawdown > 10%  → alerta, sigue operando
Nivel 2 — REDUCE:    drawdown > 20%  → cierra posiciones, no abre nuevas
Nivel 3 — HALT:      drawdown > 50%  → para todo el bot

También activa si:
  - Pérdida diaria supera DAILY_LOSS_LIMIT_PCT
  - Pérdidas consecutivas >= MAX_CONSECUTIVE_LOSSES
"""
import sqlite3
import logging
from datetime import datetime, date
from config import (
    DRAWDOWN_WARN_PCT,
    DRAWDOWN_REDUCE_PCT,
    DRAWDOWN_HALT_PCT,
    DAILY_LOSS_LIMIT_PCT,
    MAX_CONSECUTIVE_LOSSES,
    DB_PATH,
)

logger = logging.getLogger(__name__)

# Estado en memoria (se reinicia si se reinicia el proceso)
_state = {
    "level": 0,           # 0=OK, 1=WARN, 2=REDUCE, 3=HALT
    "reason": "",
    "halted_at": None,
    "day_open_equity": None,
    "day_date": None,
}


def _get_consecutive_losses() -> int:
    """Cuenta pérdidas consecutivas desde el trade más reciente."""
    try:
        with sqlite3.connect(DB_PATH) as con:
            rows = con.execute(
                "SELECT pnl FROM trades WHERE side='SELL' AND pnl IS NOT NULL ORDER BY executed_at DESC LIMIT ?",
                (MAX_CONSECUTIVE_LOSSES + 1,)
            ).fetchall()
        count = 0
        for (pnl,) in rows:
            if pnl < 0:
                count += 1
            else:
                break
        return count
    except Exception:
        return 0


def _init_day_equity(current_equity: float):
    today = date.today().isoformat()
    if _state["day_date"] != today:
        _state["day_date"] = today
        _state["day_open_equity"] = current_equity
        logger.info(f"Equity de apertura del dia: {current_equity:.2f}")


def check(current_equity: float) -> dict:
    """
    Evalúa el estado del circuit breaker.
    Retorna:
      {
        "level": int,          # 0-3
        "label": str,          # "OK" | "WARN" | "REDUCE" | "HALT"
        "reason": str,
        "can_open": bool,      # False si level >= 2
        "halted": bool,        # True si level == 3
        "drawdown_pct": float, # % respecto al capital inicial
        "daily_loss_pct": float,
        "consecutive_losses": int,
      }
    """
    _init_day_equity(current_equity)

    from modules.portfolio import get_initial_capital_usd
    initial_capital = get_initial_capital_usd()
    drawdown_pct = (initial_capital - current_equity) / initial_capital if initial_capital else 0.0
    daily_open = _state["day_open_equity"] or current_equity
    daily_loss_pct = (daily_open - current_equity) / daily_open if daily_open > 0 else 0
    consecutive_losses = _get_consecutive_losses()

    level = 0
    reason = "Operando con normalidad"

    # Evaluar niveles (el más alto prevalece)
    if drawdown_pct >= DRAWDOWN_WARN_PCT:
        level = 1
        reason = f"Drawdown {drawdown_pct:.1%} supera el umbral de aviso ({DRAWDOWN_WARN_PCT:.0%})"

    if drawdown_pct >= DRAWDOWN_REDUCE_PCT:
        level = 2
        reason = f"Drawdown {drawdown_pct:.1%} — reduccion de exposicion activada ({DRAWDOWN_REDUCE_PCT:.0%})"

    if daily_loss_pct >= DAILY_LOSS_LIMIT_PCT:
        level = max(level, 2)
        reason = f"Limite diario alcanzado: -{daily_loss_pct:.1%} en el dia"

    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        level = max(level, 2)
        reason = f"{consecutive_losses} perdidas consecutivas — pausando nuevas entradas"

    if drawdown_pct >= DRAWDOWN_HALT_PCT:
        level = 3
        reason = f"HALT: drawdown {drawdown_pct:.1%} supera el limite de seguridad ({DRAWDOWN_HALT_PCT:.0%}). Trading bloqueado."

    # Loguear si cambia de nivel
    if level != _state["level"]:
        if level == 3:
            logger.critical(f"[CIRCUIT BREAKER] NIVEL 3 - HALT TOTAL: {reason}")
            _state["halted_at"] = datetime.utcnow().isoformat()
        elif level == 2:
            logger.error(f"[CIRCUIT BREAKER] NIVEL 2 - REDUCCION: {reason}")
        elif level == 1:
            logger.warning(f"[CIRCUIT BREAKER] NIVEL 1 - AVISO: {reason}")
        else:
            logger.info(f"[CIRCUIT BREAKER] Recuperado a nivel 0: {reason}")

    _state["level"] = level
    _state["reason"] = reason

    labels = {0: "OK", 1: "AVISO", 2: "REDUCCION", 3: "HALT"}

    return {
        "level": level,
        "label": labels[level],
        "reason": reason,
        "can_open": level < 2,
        "halted": level >= 3,
        "drawdown_pct": round(drawdown_pct, 4),
        "daily_loss_pct": round(daily_loss_pct, 4),
        "consecutive_losses": consecutive_losses,
    }


def reset_halt():
    """Permite reiniciar manualmente el HALT (uso manual en emergencia)."""
    _state["level"] = 0
    _state["reason"] = "Reiniciado manualmente"
    _state["halted_at"] = None
    logger.warning("[CIRCUIT BREAKER] HALT reiniciado manualmente")
