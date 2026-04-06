"""
Screener dinámico — descubre candidatos en S&P 500 + S&P 400 MidCap.

Lógica:
  1. Descarga la lista de tickers de Wikipedia (gratis, sin API key)
  2. Batch download de OHLCV diario del último mes para todo el universo
  3. Filtros básicos: precio > $5, volumen medio > 150k/día
  4. Scoring por ticker:
       Volumen anómalo   40%  — ratio vol_hoy / vol_media_20d (dinero institucional)
       Momentum precio   30%  — % cambio 1d / 5d / 20d ponderado
       Técnico           30%  — precio > SMA20 + RSI no sobrecomprado
  5. Retorna top N candidatos (por defecto 15), cacheados 30 minutos

Cómo trabajan los traders:
  - No operan toda la bolsa — definen un universo de 500-3000 acciones y filtran
    cada día/hora las que muestran actividad anómala (volumen, breakout, noticias)
  - El screener emula ese proceso: no importa si la empresa es conocida o no,
    si el volumen es 3x su media, algo está pasando
"""
import logging
import threading
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from config import (
    SCREENER_ENABLED, SCREENER_TOP_N, SCREENER_MIN_PRICE,
    SCREENER_AVG_VOLUME_MIN, SCREENER_CACHE_MINUTES,
    SCREENER_INCLUDE_MIDCAP, WATCHLIST,
)

logger = logging.getLogger(__name__)

# ── Cachés ───────────────────────────────────────────────────────────────────
_universe_cache: dict = {"tickers": [], "fetched_at": None}
_screener_cache: dict = {"candidates": [], "updated_at": None}
_lock = threading.Lock()

# Tamaño de lote para yfinance batch download
_CHUNK_SIZE = 150


# ── Obtener universo ─────────────────────────────────────────────────────────

_WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _wiki_tables(url: str) -> list[pd.DataFrame]:
    """Descarga tablas de Wikipedia usando requests (evita 403)."""
    import requests
    from io import StringIO
    resp = requests.get(url, headers=_WIKI_HEADERS, timeout=15)
    resp.raise_for_status()
    return pd.read_html(StringIO(resp.text))


def _fetch_sp500() -> list[str]:
    """S&P 500 desde Wikipedia. Cacheado 12 horas."""
    try:
        tables = _wiki_tables(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        )
        tickers = tables[0]["Symbol"].astype(str).tolist()
        tickers = [t.replace(".", "-") for t in tickers]
        logger.info(f"S&P 500 cargado: {len(tickers)} tickers")
        return tickers
    except Exception as e:
        logger.warning(f"No se pudo obtener S&P 500 de Wikipedia: {e}")
        return []


def _fetch_sp400() -> list[str]:
    """S&P 400 MidCap desde Wikipedia."""
    try:
        tables = _wiki_tables(
            "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
        )
        df = tables[0]
        col = next(
            (c for c in df.columns if "ticker" in c.lower() or "symbol" in c.lower()),
            df.columns[0]
        )
        tickers = df[col].astype(str).tolist()
        tickers = [t.replace(".", "-") for t in tickers]
        logger.info(f"S&P 400 MidCap cargado: {len(tickers)} tickers")
        return tickers
    except Exception as e:
        logger.warning(f"No se pudo obtener S&P 400: {e}")
        return []


def _get_universe() -> list[str]:
    """
    Retorna el universo completo de tickers (S&P 500 + 400).
    Cacheado 12 horas. Excluye tickers ya en el WATCHLIST estático.
    """
    with _lock:
        now = datetime.utcnow()
        if (
            _universe_cache["fetched_at"]
            and (now - _universe_cache["fetched_at"]) < timedelta(hours=12)
            and _universe_cache["tickers"]
        ):
            return _universe_cache["tickers"]

        sp500 = _fetch_sp500()
        midcap = _fetch_sp400() if SCREENER_INCLUDE_MIDCAP else []

        # Unión, eliminar duplicados y tickers ya en watchlist estático
        static = set(WATCHLIST)
        all_tickers = list(dict.fromkeys(sp500 + midcap))  # preserva orden, elimina dupes
        all_tickers = [t for t in all_tickers if t not in static]

        _universe_cache["tickers"] = all_tickers
        _universe_cache["fetched_at"] = now
        logger.info(
            f"Universo screener: {len(all_tickers)} tickers "
            f"(S&P500={len(sp500)} midcap={len(midcap)} estático={len(static)})"
        )
        return all_tickers


# ── Scoring ──────────────────────────────────────────────────────────────────

def _compute_rsi(prices: pd.Series, period: int = 14) -> float:
    """RSI simplificado sobre una Series de precios."""
    if len(prices) < period + 1:
        return 50.0
    deltas = prices.diff().iloc[-(period + 1):]
    gains  = deltas.clip(lower=0).mean()
    losses = (-deltas.clip(upper=0)).mean()
    if losses == 0:
        return 100.0
    rs = gains / losses
    return float(100 - (100 / (1 + rs)))


def _score_ticker(
    ticker: str,
    close: pd.Series,
    volume: pd.Series,
) -> dict | None:
    """
    Puntúa un ticker de 0 a 1.
    Retorna None si no cumple filtros mínimos.
    """
    close  = close.dropna()
    volume = volume.dropna()

    if len(close) < 10 or len(volume) < 5:
        return None

    last_price = float(close.iloc[-1])
    if last_price < SCREENER_MIN_PRICE:
        return None

    # ── Volumen ──────────────────────────────────────────────────
    last_vol = float(volume.iloc[-1])
    avg_vol  = float(volume.iloc[:-1].mean()) if len(volume) > 1 else last_vol
    if avg_vol < SCREENER_AVG_VOLUME_MIN:
        return None

    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0

    # Normalizado: 1x = 0.33, 2x = 0.67, 3x = 1.0
    # SCREENER_VOL_SPIKE_MIN no es filtro duro — es referencia de normalización
    vol_score = min(vol_ratio / 3.0, 1.0)

    # ── Momentum precio ──────────────────────────────────────────
    pct_1d  = float(close.iloc[-1] / close.iloc[-2]  - 1) if len(close) >= 2  else 0.0
    pct_5d  = float(close.iloc[-1] / close.iloc[-6]  - 1) if len(close) >= 6  else pct_1d
    pct_20d = float(close.iloc[-1] / close.iloc[-21] - 1) if len(close) >= 21 else pct_5d

    # Ponderado: más peso al corto plazo
    avg_mom = pct_1d * 0.40 + pct_5d * 0.35 + pct_20d * 0.25
    # Normalizado: +5% promedio = score 0.5, +10% = 1.0, negativo = 0
    mom_score = max(0.0, min(avg_mom / 0.10, 1.0))

    # ── Técnico: SMA20 + RSI ─────────────────────────────────────
    sma20 = float(close.iloc[-20:].mean()) if len(close) >= 20 else float(close.mean())
    above_sma = 1.0 if last_price > sma20 else 0.2

    rsi = _compute_rsi(close)
    if rsi > 80:
        rsi_score = 0.1   # muy sobrecomprado — evitar
    elif rsi > 70:
        rsi_score = 0.5
    elif rsi < 30:
        rsi_score = 0.9   # oversold — rebote potencial
    else:
        rsi_score = 1.0   # zona neutra-alcista

    tech_score = above_sma * 0.50 + rsi_score * 0.50

    # ── Score final ──────────────────────────────────────────────
    total = vol_score * 0.40 + mom_score * 0.30 + tech_score * 0.30

    return {
        "ticker":    ticker,
        "score":     round(total, 4),
        "vol_ratio": round(vol_ratio, 2),
        "pct_1d":    round(pct_1d * 100, 2),
        "pct_5d":    round(pct_5d * 100, 2),
        "price":     round(last_price, 2),
        "rsi":       round(rsi, 1),
        "above_sma": above_sma == 1.0,
    }


# ── Batch download ───────────────────────────────────────────────────────────

def _batch_download(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Descarga OHLCV de 1 mes para todos los tickers en lotes.
    Retorna (close_df, volume_df) con columnas = tickers.
    """
    close_frames  = []
    volume_frames = []

    for i in range(0, len(tickers), _CHUNK_SIZE):
        chunk = tickers[i : i + _CHUNK_SIZE]
        if not chunk:
            continue
        try:
            df = yf.download(
                chunk,
                period="1mo",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
            if df.empty:
                continue

            # yfinance devuelve MultiIndex (field, ticker) para múltiples tickers
            if isinstance(df.columns, pd.MultiIndex):
                c = df["Close"]
                v = df["Volume"]
            else:
                # Un solo ticker en el chunk
                c = df[["Close"]].rename(columns={"Close": chunk[0]})
                v = df[["Volume"]].rename(columns={"Volume": chunk[0]})

            close_frames.append(c)
            volume_frames.append(v)

        except Exception as e:
            logger.debug(f"Chunk {i//_CHUNK_SIZE} error: {e}")

    if not close_frames:
        return pd.DataFrame(), pd.DataFrame()

    close_all  = pd.concat(close_frames,  axis=1)
    volume_all = pd.concat(volume_frames, axis=1)
    return close_all, volume_all


# ── Punto de entrada público ─────────────────────────────────────────────────

def run_screener() -> list[dict]:
    """
    Ejecuta el screener y retorna los mejores candidatos.
    Resultado cacheado SCREENER_CACHE_MINUTES minutos.

    Cada candidato es un dict con: ticker, score, vol_ratio, pct_1d, pct_5d, price, rsi
    """
    if not SCREENER_ENABLED:
        return []

    with _lock:
        now = datetime.utcnow()
        if (
            _screener_cache["updated_at"]
            and (now - _screener_cache["updated_at"]) < timedelta(minutes=SCREENER_CACHE_MINUTES)
        ):
            return _screener_cache["candidates"]

    universe = _get_universe()
    if not universe:
        logger.warning("Universo vacío — screener desactivado este ciclo")
        return []

    logger.info(f"Screener: analizando {len(universe)} tickers...")
    t0 = datetime.utcnow()

    close_df, volume_df = _batch_download(universe)
    if close_df.empty:
        logger.warning("Screener: no se pudieron descargar datos")
        return []

    candidates = []
    for ticker in close_df.columns:
        try:
            c = close_df[ticker]
            v = volume_df[ticker] if ticker in volume_df.columns else pd.Series(dtype=float)
            result = _score_ticker(ticker, c, v)
            if result:
                candidates.append(result)
        except Exception:
            continue

    # Ordenar por score descendente, tomar top N
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:SCREENER_TOP_N]

    elapsed = (datetime.utcnow() - t0).total_seconds()
    logger.info(
        f"Screener completado en {elapsed:.1f}s | "
        f"candidatos con spike: {len(candidates)} | "
        f"top {len(top)}: {[c['ticker'] for c in top]}"
    )

    with _lock:
        _screener_cache["candidates"]  = top
        _screener_cache["updated_at"]  = datetime.utcnow()

    return top


def get_screener_tickers() -> list[str]:
    """Retorna solo los tickers (para integrarlo fácilmente en el ciclo de trading)."""
    return [c["ticker"] for c in run_screener()]
