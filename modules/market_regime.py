"""
Filtro de régimen de mercado — evita comprar contra la tendencia del mercado.

El mayor error de los bots automáticos es seguir abriendo longs en un mercado
bajista. Este módulo detecta el estado macro del mercado usando SPY + VIX y
ajusta el umbral mínimo de señal para abrir posiciones.

Regímenes:
  BULL    — SPY sobre SMA50 y SMA200, VIX < 20
              → Operación normal
  NEUTRAL — SPY entre SMAs o VIX entre 20-30
              → Subir umbral de señal un 15% (más selectivo)
  BEAR    — SPY bajo SMA200 O VIX > 30
              → Subir umbral un 40% (casi bloqueado, solo señales muy fuertes)

Cacheado 30 minutos para no sobrecargar yfinance.
"""
import logging
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

_cache: dict = {"regime": None, "updated_at": None}
_CACHE_MIN = 30


def _download_series(ticker: str, period: str = "6mo") -> pd.Series | None:
    """Descarga la serie de cierre diario de un ticker."""
    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df["Close"].squeeze().dropna()
    except Exception as e:
        logger.warning(f"market_regime: error descargando {ticker}: {e}")
        return None


def get_market_regime() -> dict:
    """
    Retorna el régimen de mercado actual.

    Devuelve:
        regime:         "bull" | "neutral" | "bear"
        min_score_mult: multiplicador para el umbral mínimo de señal
        detail:         descripción legible
        spy_vs_sma50:   % distancia SPY vs SMA50
        spy_vs_sma200:  % distancia SPY vs SMA200
        vix:            último valor del VIX
    """
    now = datetime.utcnow()
    if (
        _cache["updated_at"]
        and (now - _cache["updated_at"]) < timedelta(minutes=_CACHE_MIN)
        and _cache["regime"]
    ):
        return _cache["regime"]

    spy = _download_series("SPY")
    vix = _download_series("^VIX")

    # Valores por defecto si no hay datos (conservador: neutral)
    if spy is None or len(spy) < 50:
        result = {
            "regime": "neutral",
            "min_score_mult": 1.15,
            "detail": "Sin datos SPY — modo conservador",
            "spy_vs_sma50": 0.0,
            "spy_vs_sma200": 0.0,
            "vix": 20.0,
        }
        _cache["regime"] = result
        _cache["updated_at"] = now
        return result

    spy_last  = float(spy.iloc[-1])
    sma50     = float(spy.iloc[-50:].mean())
    sma200    = float(spy.iloc[-200:].mean()) if len(spy) >= 200 else float(spy.mean())
    vix_last  = float(vix.iloc[-1]) if vix is not None and not vix.empty else 20.0

    spy_vs_50  = (spy_last / sma50  - 1) * 100
    spy_vs_200 = (spy_last / sma200 - 1) * 100

    # ── Lógica de régimen ─────────────────────────────────────────
    if spy_last < sma200 or vix_last > 30:
        regime       = "bear"
        mult         = 1.40
        if spy_last < sma200 and vix_last > 30:
            detail = f"BEAR: SPY bajo SMA200 ({spy_vs_200:+.1f}%) y VIX={vix_last:.0f}"
        elif spy_last < sma200:
            detail = f"BEAR: SPY bajo SMA200 ({spy_vs_200:+.1f}%)"
        else:
            detail = f"BEAR: VIX={vix_last:.0f} (pánico extremo)"

    elif vix_last > 20 or spy_last < sma50:
        regime       = "neutral"
        mult         = 1.15
        if vix_last > 20:
            detail = f"NEUTRAL: VIX={vix_last:.0f} (incertidumbre), SPY {spy_vs_200:+.1f}% vs SMA200"
        else:
            detail = f"NEUTRAL: SPY bajo SMA50 ({spy_vs_50:+.1f}%) pero sobre SMA200"

    else:
        regime       = "bull"
        mult         = 1.00
        detail       = (
            f"BULL: SPY {spy_vs_50:+.1f}% vs SMA50, "
            f"{spy_vs_200:+.1f}% vs SMA200, VIX={vix_last:.0f}"
        )

    result = {
        "regime":         regime,
        "min_score_mult": mult,
        "detail":         detail,
        "spy_vs_sma50":   round(spy_vs_50, 2),
        "spy_vs_sma200":  round(spy_vs_200, 2),
        "vix":            round(vix_last, 1),
    }

    _cache["regime"] = result
    _cache["updated_at"] = now

    logger.info(f"Régimen mercado: {detail} | mult={mult}")
    return result
