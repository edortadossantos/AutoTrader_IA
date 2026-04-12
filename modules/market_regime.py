"""
Filtro de régimen de mercado — adapta umbrales según la tendencia macro.

Regímenes:
  BULL    — SPY sobre SMA50 y SMA200, VIX < 20
              → Operación normal. Favorecer LONG.
  NEUTRAL — SPY entre SMAs o VIX entre 20-30
              → Más selectivo. LONG y SHORT equilibrados.
  BEAR    — SPY bajo SMA200 O VIX > 30
              → Favorecer SHORT. LONG solo con señal muy fuerte.

Multiplicadores de umbral (min_score × mult):
  long_mult:  cuánto subir el umbral para abrir LONG
  short_mult: cuánto bajar/subir el umbral para abrir SHORT
  < 1.0 = más fácil entrar | > 1.0 = más difícil entrar
"""
import logging
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

_cache: dict = {"regime": None, "updated_at": None}
_CACHE_MIN = 30


def _download_series(ticker: str, period: str = "6mo") -> pd.Series | None:
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
    Retorna el régimen de mercado actual con multiplicadores separados
    para posiciones LONG y SHORT.

    Devuelve:
        regime:         "bull" | "neutral" | "bear"
        min_score_mult: multiplicador LONG (compatibilidad hacia atrás)
        long_mult:      multiplicador para abrir LONG
        short_mult:     multiplicador para abrir SHORT (< 1.0 en BEAR = más fácil cortar)
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

    if spy is None or len(spy) < 50:
        result = {
            "regime":         "neutral",
            "min_score_mult": 1.10,
            "long_mult":      1.10,
            "short_mult":     1.00,
            "detail":         "Sin datos SPY — modo conservador",
            "spy_vs_sma50":   0.0,
            "spy_vs_sma200":  0.0,
            "vix":            20.0,
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

    if spy_last < sma200 or vix_last > 30:
        regime = "bear"
        # LONG: umbral sube 20% (más difícil comprar contra la tendencia)
        # SHORT: umbral baja 35% (umbral agresivo — crash = dirección clara)
        long_mult  = 1.20
        short_mult = 0.65
        if spy_last < sma200 and vix_last > 30:
            detail = f"BEAR: SPY bajo SMA200 ({spy_vs_200:+.1f}%) y VIX={vix_last:.0f}"
        elif spy_last < sma200:
            detail = f"BEAR: SPY bajo SMA200 ({spy_vs_200:+.1f}%)"
        else:
            detail = f"BEAR: VIX={vix_last:.0f} (pánico extremo)"

    elif vix_last > 20 or spy_last < sma50:
        regime = "neutral"
        long_mult  = 1.10
        short_mult = 0.85
        if vix_last > 20:
            detail = f"NEUTRAL: VIX={vix_last:.0f} (incertidumbre), SPY {spy_vs_200:+.1f}% vs SMA200"
        else:
            detail = f"NEUTRAL: SPY bajo SMA50 ({spy_vs_50:+.1f}%) pero sobre SMA200"

    else:
        regime = "bull"
        long_mult  = 1.00
        short_mult = 1.25  # más difícil cortar en mercado alcista
        detail = (
            f"BULL: SPY {spy_vs_50:+.1f}% vs SMA50, "
            f"{spy_vs_200:+.1f}% vs SMA200, VIX={vix_last:.0f}"
        )

    result = {
        "regime":         regime,
        "min_score_mult": long_mult,   # compatibilidad hacia atrás
        "long_mult":      long_mult,
        "short_mult":     short_mult,
        "detail":         detail,
        "spy_vs_sma50":   round(spy_vs_50, 2),
        "spy_vs_sma200":  round(spy_vs_200, 2),
        "vix":            round(vix_last, 1),
    }

    _cache["regime"] = result
    _cache["updated_at"] = now

    logger.info(f"Régimen mercado: {detail} | long_mult={long_mult} short_mult={short_mult}")
    return result
