"""
Descarga datos OHLCV y calcula indicadores técnicos.

v2 — Multi-timeframe + señales mejoradas:
  - Contexto daily (SMA50/200 + ADX) como filtro principal de tendencia
  - MACD solo en crossover real (elimina el ruido continuo)
  - Volumen como señal direccional (no solo boost)
  - ADX multiplier: descuenta señales en mercados sin tendencia
  - Cache 30 min para datos daily (no sobrecargar yfinance)
"""
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf
import ta
from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, SMA_SHORT, SMA_LONG,
    INVERSE_ETFS,
)

logger = logging.getLogger(__name__)

# Cache para datos daily (clave: ticker, valor: {data, updated_at})
_daily_cache: dict[str, dict] = {}
_DAILY_CACHE_MIN = 30


# ────────────────────────────────────────────────────────────────────
# Contribuciones fijas de cada señal al score compuesto.
# Rango total: [-1.05, +1.05] — comparable con el sistema anterior.
# ────────────────────────────────────────────────────────────────────
_SIGNAL_CONTRIB = {
    # RSI
    "RSI oversold":        +0.25,
    "RSI overbought":      -0.25,
    "RSI neutral":          0.00,
    # MACD (solo crossover, sin ruido continuo)
    "MACD bullish cross":  +0.20,
    "MACD bearish cross":  -0.20,
    "MACD no cross":        0.00,
    # Bollinger Bands
    "Price at BB lower":   +0.15,
    "Price at BB upper":   -0.15,
    "Price inside BB":      0.00,
    # SMA horaria (tendencia de corto plazo — peso bajo)
    "SMA uptrend":         +0.10,
    "SMA downtrend":       -0.10,
    # Tendencia DAILY (filtro macro — peso alto)
    "Daily uptrend":       +0.25,
    "Daily downtrend":     -0.25,
    "Daily mixed":          0.00,
    # Señal de sobrevendido extremo: RSI < 30 + precio en BB inferior = rebote probable
    # Compensa parcialmente el Daily downtrend en crashes para no perder el rebote.
    "Extreme oversold":    +0.20,
    # Señal de sobrecompra extrema: RSI > 70 + precio en BB superior = caída probable
    "Extreme overbought":  -0.20,
    # Volumen (confirmación direccional)
    "Volume spike":        +0.10,   # vol > 1.5× media — señal confirmada
    "Volume above avg":    +0.05,   # vol > 1.1× media — leve confirmación
    "Volume dry":          -0.10,   # vol < 0.7× media — señal dudosa
    "Volume normal":        0.00,
    # Momentum direccional (ADX fuerte + tendencia + MACD confirmado)
    # NO se cancela con RSI/BB: representa tendencia pura sin ruido.
    # Clave para detectar crashes sostenidos aunque el RSI esté sobrevendido.
    "Momentum bull":       +0.25,   # ADX>25 + daily up + MACD hist>0
    "Momentum bear":       -0.25,   # ADX>25 + daily down + MACD hist<0
    # ROC — momentum de precio puro (Rate of Change)
    # Independiente de RSI/BB: no se cancela con señales de reversión.
    "ROC up":              +0.15,   # ROC5 > 0.8% y ROC20 > 1.5%
    "ROC down":            -0.15,   # ROC5 < -0.8% y ROC20 < -1.5%
    "ROC flat":             0.00,
}

# Señales que se invierten para ETFs inversos (SH, PSQ, SDS, SQQQ).
# Cuando el mercado cae, el ETF sube → RSI overbought = señal alcista, no bajista.
_INVERSE_INVERT = {
    "RSI oversold", "RSI overbought",
    "Price at BB lower", "Price at BB upper",
    "Extreme oversold", "Extreme overbought",
}


def fetch_ohlcv(ticker: str, period: str = "3mo", interval: str = "1h") -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.dropna(inplace=True)
        return df
    except Exception as e:
        logger.warning(f"[{ticker}] fetch error: {e}")
        return None


def fetch_daily_context(ticker: str) -> dict:
    """
    Descarga datos diarios (6 meses) y calcula:
      - Tendencia: 'up' | 'down' | 'mixed'
      - ADX (fuerza de tendencia, 0-100)
      - % precio vs SMA50 y SMA200

    Cacheado 30 min para no sobrecargar yfinance en cada ciclo.
    """
    now = datetime.utcnow()
    cached = _daily_cache.get(ticker)
    if cached and (now - cached["updated_at"]) < timedelta(minutes=_DAILY_CACHE_MIN):
        return cached["data"]

    _default = {"trend": "mixed", "sma50_pct": 0.0, "sma200_pct": 0.0, "adx": 20.0}
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 30:
            _daily_cache[ticker] = {"data": _default, "updated_at": now}
            return _default
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.dropna(inplace=True)

        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()

        last   = float(close.iloc[-1])
        sma50  = float(close.iloc[-min(50, len(close)):].mean())
        sma200 = float(close.iloc[-min(200, len(close)):].mean())

        adx_val = 20.0
        try:
            adx_ind = ta.trend.ADXIndicator(high, low, close, window=14)
            adx_val = float(adx_ind.adx().iloc[-1])
            if np.isnan(adx_val):
                adx_val = 20.0
        except Exception:
            pass

        vs_sma50  = (last / sma50  - 1) * 100
        vs_sma200 = (last / sma200 - 1) * 100

        if last > sma50 and last > sma200:
            trend = "up"
        elif last < sma200:
            trend = "down"
        else:
            trend = "mixed"

        result = {
            "trend":     trend,
            "sma50_pct":  round(vs_sma50,  2),
            "sma200_pct": round(vs_sma200, 2),
            "adx":        round(adx_val, 1),
        }
        _daily_cache[ticker] = {"data": result, "updated_at": now}
        return result

    except Exception as e:
        logger.warning(f"[{ticker}] daily context error: {e}")
        _daily_cache[ticker] = {"data": _default, "updated_at": now}
        return _default


def get_current_price(ticker: str) -> float | None:
    """Alpaca IEX → yfinance fallback. Caché 30 s."""
    try:
        from modules.data_layer import get_price
        return get_price(ticker)
    except Exception:
        try:
            return float(yf.Ticker(ticker).fast_info.last_price)
        except Exception:
            pass
    return None


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """Batch Alpaca (1-2 llamadas) → yfinance fallback por ticker."""
    try:
        from modules.data_layer import get_prices_batch
        return get_prices_batch(tickers)
    except Exception:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        prices: dict[str, float] = {}
        with ThreadPoolExecutor(max_workers=min(12, len(tickers) or 1)) as ex:
            futures = {ex.submit(get_current_price, t): t for t in tickers}
            for fut in as_completed(futures):
                ticker = futures[fut]
                try:
                    p = fut.result()
                    if p:
                        prices[ticker] = p
                except Exception:
                    pass
        return prices


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close  = df["Close"].squeeze()
    high   = df["High"].squeeze()
    low    = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    df["rsi"]        = ta.momentum.RSIIndicator(close, window=RSI_PERIOD).rsi()
    macd_obj         = ta.trend.MACD(close, window_slow=MACD_SLOW, window_fast=MACD_FAST, window_sign=MACD_SIGNAL)
    df["macd"]       = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_hist"]  = macd_obj.macd_diff()
    bb               = ta.volatility.BollingerBands(close, window=BB_PERIOD, window_dev=BB_STD)
    df["bb_upper"]   = bb.bollinger_hband()
    df["bb_lower"]   = bb.bollinger_lband()
    df["bb_mid"]     = bb.bollinger_mavg()
    df["bb_pct"]     = bb.bollinger_pband()
    df["sma_short"]  = ta.trend.SMAIndicator(close, window=SMA_SHORT).sma_indicator()
    df["sma_long"]   = ta.trend.SMAIndicator(close, window=SMA_LONG).sma_indicator()
    df["atr"]        = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    df["vol_sma"]    = volume.rolling(20).mean()

    return df.dropna()


def analyze_ticker(ticker: str) -> dict | None:
    """
    Retorna señales técnicas y score de compra/venta para el ticker.

    Score en [-1, +1]:
      > 0  señal alcista
      < 0  señal bajista

    Mejoras v2:
      - Tendencia daily como filtro principal (peso 0.25)
      - MACD solo en crossover real (sin ruido continuo)
      - Volumen como señal direccional
      - ADX multiplier: descuenta señales en mercados choppy (ADX < 20)
    """
    df = fetch_ohlcv(ticker)
    if df is None:
        return None

    df = compute_indicators(df)
    if df.empty:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    signals: list[tuple[str, float]] = []

    # ── RSI ──────────────────────────────────────────────────────────
    rsi = float(last["rsi"])
    if rsi < RSI_OVERSOLD:
        signals.append(("RSI oversold", _SIGNAL_CONTRIB["RSI oversold"]))
    elif rsi > RSI_OVERBOUGHT:
        signals.append(("RSI overbought", _SIGNAL_CONTRIB["RSI overbought"]))
    else:
        signals.append(("RSI neutral", 0.0))

    # ── MACD — solo crossover real (sin ruido continuo) ──────────────
    pm, ps = float(prev["macd"]), float(prev["macd_signal"])
    lm, ls = float(last["macd"]), float(last["macd_signal"])
    if pm < ps and lm > ls:
        signals.append(("MACD bullish cross", _SIGNAL_CONTRIB["MACD bullish cross"]))
    elif pm > ps and lm < ls:
        signals.append(("MACD bearish cross", _SIGNAL_CONTRIB["MACD bearish cross"]))
    else:
        signals.append(("MACD no cross", 0.0))

    # ── Bollinger Bands ───────────────────────────────────────────────
    close = float(last["Close"])
    if close <= float(last["bb_lower"]):
        signals.append(("Price at BB lower", _SIGNAL_CONTRIB["Price at BB lower"]))
    elif close >= float(last["bb_upper"]):
        signals.append(("Price at BB upper", _SIGNAL_CONTRIB["Price at BB upper"]))
    else:
        signals.append(("Price inside BB", 0.0))

    # ── SMA corta vs larga (tendencia horaria — peso bajo) ────────────
    if float(last["sma_short"]) > float(last["sma_long"]):
        signals.append(("SMA uptrend", _SIGNAL_CONTRIB["SMA uptrend"]))
    else:
        signals.append(("SMA downtrend", _SIGNAL_CONTRIB["SMA downtrend"]))

    # ── Tendencia DAILY (filtro macro — peso alto) ────────────────────
    daily = fetch_daily_context(ticker)
    adx = daily["adx"]    # extraer aquí para usarlo también en Momentum signal
    if daily["trend"] == "up":
        signals.append(("Daily uptrend", _SIGNAL_CONTRIB["Daily uptrend"]))
    elif daily["trend"] == "down":
        signals.append(("Daily downtrend", _SIGNAL_CONTRIB["Daily downtrend"]))
    else:
        signals.append(("Daily mixed", 0.0))

    # ── Volumen (confirmación direccional) ───────────────────────────
    # La dirección importa: volumen alto en vela alcista confirma; en bajista, alerta.
    vol_sma    = float(last["vol_sma"])
    vol_ratio  = float(last["Volume"]) / vol_sma if vol_sma > 0 else 1.0
    candle_dir = 1 if float(last["Close"]) >= float(last["Open"]) else -1
    if vol_ratio >= 1.5:
        # Spike: +0.10 si vela alcista, -0.10 si vela bajista
        signals.append(("Volume spike", _SIGNAL_CONTRIB["Volume spike"] * candle_dir))
    elif vol_ratio >= 1.1:
        signals.append(("Volume above avg", _SIGNAL_CONTRIB["Volume above avg"] * candle_dir))
    elif vol_ratio < 0.7:
        signals.append(("Volume dry", _SIGNAL_CONTRIB["Volume dry"]))
    else:
        signals.append(("Volume normal", 0.0))

    # ── Sobrevendido extremo (rebote en crash) ───────────────────────
    # RSI < 30 + precio tocando/bajo BB inferior = confluencia de sobrevendido.
    # Esta señal actúa como contrapeso parcial del "Daily downtrend" en crashes.
    # Solo se emite si la señal ya tiene RSI oversold + BB lower (no se duplica).
    has_rsi_oversold  = rsi < RSI_OVERSOLD
    has_bb_lower      = close <= float(last["bb_lower"])
    has_rsi_overbought = rsi > RSI_OVERBOUGHT
    has_bb_upper      = close >= float(last["bb_upper"])

    if has_rsi_oversold and has_bb_lower and rsi < 30:
        signals.append(("Extreme oversold", _SIGNAL_CONTRIB["Extreme oversold"]))

    # ── Sobrecompra extrema (techo / catalizador SHORT) ──────────────
    # RSI > 70 + precio en/sobre BB superior = confluencia de sobrecompra.
    # Activa señal bajista para posiciones SHORT.
    if has_rsi_overbought and has_bb_upper and rsi > 70:
        signals.append(("Extreme overbought", _SIGNAL_CONTRIB["Extreme overbought"]))

    # ── Momentum direccional (triple confirmación — no lo cancela RSI/BB) ─────
    # ADX fuerte + tendencia daily + MACD histograma en la misma dirección.
    # Esta señal es la clave para detectar crashes sostenidos donde el RSI
    # "miente" al ponerse sobrevendido durante la caída continua.
    macd_hist = float(last["macd_hist"])
    if adx > 25 and daily["trend"] == "up" and macd_hist > 0:
        signals.append(("Momentum bull", _SIGNAL_CONTRIB["Momentum bull"]))
    elif adx > 25 and daily["trend"] == "down" and macd_hist < 0:
        signals.append(("Momentum bear", _SIGNAL_CONTRIB["Momentum bear"]))

    # ── ROC — Rate of Change puro (independiente de RSI/BB) ──────────────
    # ROC5 = rendimiento de los últimos 5 cierres
    # ROC20 = rendimiento de los últimos 20 cierres
    # Ambas en la misma dirección → confirmación de tendencia de corto plazo.
    if len(df) >= 21:
        roc5  = (float(last["Close"]) / float(df["Close"].iloc[-6])  - 1) * 100
        roc20 = (float(last["Close"]) / float(df["Close"].iloc[-21]) - 1) * 100
        if roc5 > 0.8 and roc20 > 1.5:
            signals.append(("ROC up", _SIGNAL_CONTRIB["ROC up"]))
        elif roc5 < -0.8 and roc20 < -1.5:
            signals.append(("ROC down", _SIGNAL_CONTRIB["ROC down"]))
        else:
            signals.append(("ROC flat", 0.0))
    else:
        roc5 = roc20 = 0.0
        signals.append(("ROC flat", 0.0))

    # ── Filtro de volatilidad (ATR% relativo) — sizing modifier ──────────
    # No afecta el score de señal, pero devuelve un multiplicador de tamaño.
    # ATR% < 0.3% → mercado muerto, no operar (size_mult = 0)
    # ATR% > 3.5% → volatilidad extrema, reducir tamaño (size_mult = 0.5)
    # Expanding vs histórico → entorno ideal de momentum (size_mult = 1.2)
    atr_val    = float(last["atr"])
    atr_pct    = (atr_val / close * 100) if close > 0 else 0.0
    atr_hist   = float(df["atr"].iloc[-20:].mean()) if len(df) >= 20 else atr_val
    atr_ratio  = atr_val / (atr_hist + 1e-9)

    if atr_pct < 0.30:
        vol_size_mult = 0.0   # mercado muerto
    elif atr_pct > 3.5:
        vol_size_mult = 0.5   # volatilidad extrema
    elif atr_ratio > 1.25:
        vol_size_mult = 1.2   # ATR expandiéndose — momentum óptimo
    else:
        vol_size_mult = 1.0

    # ── Ajuste para ETFs inversos (SH, PSQ, SDS, SQQQ) ───────────────
    # El RSI y BB se invierten: cuando el mercado cae, el ETF sube.
    # RSI overbought en SH durante crash = señal alcista (seguir comprando).
    # Las señales de tendencia/momentum/volumen quedan sin cambio.
    if ticker in INVERSE_ETFS:
        signals = [
            (name, -contrib) if name in _INVERSE_INVERT else (name, contrib)
            for name, contrib in signals
        ]

    # ── Score compuesto ───────────────────────────────────────────────
    raw_score = sum(contrib for _, contrib in signals)

    # ADX multiplier: señales en mercados sin tendencia valen menos
    # (adx ya extraído arriba junto con daily context)
    if adx < 15:
        adx_mult = 0.60   # muy choppy — señales técnicas poco fiables (era 0.50)
    elif adx < 20:
        adx_mult = 0.85   # moderadamente choppy (era 0.75, demasiado agresivo)
    elif adx > 35:
        adx_mult = 1.10   # tendencia fuerte — amplificar señal
    else:
        adx_mult = 1.00

    score = max(-1.0, min(1.0, raw_score * adx_mult))

    return {
        "ticker":         ticker,
        "price":          close,
        "rsi":            round(rsi, 2),
        "macd":           round(float(last["macd"]), 4),
        "macd_signal":    round(float(last["macd_signal"]), 4),
        "bb_pct":         round(float(last["bb_pct"]), 3),
        "sma_short":      round(float(last["sma_short"]), 2),
        "sma_long":       round(float(last["sma_long"]), 2),
        "atr":            round(float(last["atr"]), 4),
        "atr_pct":        round(atr_pct, 3),
        "vol_ratio":      round(vol_ratio, 2),
        "vol_size_mult":  round(vol_size_mult, 2),
        "roc5":           round(roc5, 3),
        "roc20":          round(roc20, 3),
        "daily_trend":    daily["trend"],
        "daily_sma50":    daily["sma50_pct"],
        "daily_sma200":   daily["sma200_pct"],
        "adx":            adx,
        "signals":        signals,
        "score":          round(score, 4),
    }
