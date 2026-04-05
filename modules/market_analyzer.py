"""
Descarga datos OHLCV y calcula indicadores técnicos.
"""
import logging
import pandas as pd
import numpy as np
import yfinance as yf
import ta
from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, SMA_SHORT, SMA_LONG
)

logger = logging.getLogger(__name__)


def fetch_ohlcv(ticker: str, period: str = "3mo", interval: str = "1h") -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        # yfinance >= 0.2.x puede devolver MultiIndex (field, ticker) — aplanar
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.dropna(inplace=True)
        return df
    except Exception as e:
        logger.warning(f"[{ticker}] fetch error: {e}")
        return None


def get_current_price(ticker: str) -> float | None:
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        return float(info.last_price)
    except Exception:
        try:
            df = fetch_ohlcv(ticker, period="1d", interval="1m")
            if df is not None and not df.empty:
                return float(df["Close"].iloc[-1])
        except Exception:
            pass
    return None


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    prices = {}
    for t in tickers:
        p = get_current_price(t)
        if p:
            prices[t] = p
    return prices


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(close, window=RSI_PERIOD).rsi()

    # MACD
    macd_obj = ta.trend.MACD(close, window_slow=MACD_SLOW, window_fast=MACD_FAST, window_sign=MACD_SIGNAL)
    df["macd"] = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_hist"] = macd_obj.macd_diff()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close, window=BB_PERIOD, window_dev=BB_STD)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"] = bb.bollinger_mavg()
    df["bb_pct"] = bb.bollinger_pband()

    # SMAs
    df["sma_short"] = ta.trend.SMAIndicator(close, window=SMA_SHORT).sma_indicator()
    df["sma_long"] = ta.trend.SMAIndicator(close, window=SMA_LONG).sma_indicator()

    # ATR (volatilidad)
    df["atr"] = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()

    # Volume SMA
    df["vol_sma"] = volume.rolling(20).mean()

    return df.dropna()


def analyze_ticker(ticker: str) -> dict | None:
    """
    Retorna un dict con señales técnicas y score de compra/venta.
    score > 0: señal alcista | score < 0: señal bajista
    """
    df = fetch_ohlcv(ticker)
    if df is None:
        return None

    df = compute_indicators(df)
    if df.empty:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    signals = []
    weights = []

    # ── RSI ──────────────────────────────────────────────────────
    rsi = float(last["rsi"])
    if rsi < RSI_OVERSOLD:
        signals.append(("RSI oversold", 1.0))
    elif rsi > RSI_OVERBOUGHT:
        signals.append(("RSI overbought", -1.0))
    else:
        signals.append(("RSI neutral", 0.0))

    # ── MACD crossover ───────────────────────────────────────────
    pm, ps = float(prev["macd"]), float(prev["macd_signal"])
    lm, ls = float(last["macd"]), float(last["macd_signal"])
    if pm < ps and lm > ls:
        signals.append(("MACD bullish cross", 1.0))
    elif pm > ps and lm < ls:
        signals.append(("MACD bearish cross", -1.0))
    elif lm > ls:
        signals.append(("MACD above signal", 0.5))
    else:
        signals.append(("MACD below signal", -0.5))

    # ── Bollinger ─────────────────────────────────────────────────
    close = float(last["Close"])
    if close <= float(last["bb_lower"]):
        signals.append(("Price at BB lower", 1.0))
    elif close >= float(last["bb_upper"]):
        signals.append(("Price at BB upper", -1.0))
    else:
        signals.append(("Price inside BB", 0.0))

    # ── SMA trend ────────────────────────────────────────────────
    if float(last["sma_short"]) > float(last["sma_long"]):
        signals.append(("SMA uptrend", 0.7))
    else:
        signals.append(("SMA downtrend", -0.7))

    # ── Volume confirmation ───────────────────────────────────────
    vol_sma = float(last["vol_sma"])
    vol_ratio = float(last["Volume"]) / vol_sma if vol_sma > 0 else 1.0
    vol_boost = min(vol_ratio, 2.0) / 2.0  # normalizado 0-1

    # Score compuesto normalizado a [-1, 1]
    raw_score = sum(s[1] for s in signals) / len(signals)
    # Ajuste por volumen: amplifica señales con volumen alto
    score = raw_score * (0.7 + 0.3 * vol_boost)

    return {
        "ticker": ticker,
        "price": close,
        "rsi": round(float(rsi), 2),
        "macd": round(float(last["macd"]), 4),
        "macd_signal": round(float(last["macd_signal"]), 4),
        "bb_pct": round(float(last["bb_pct"]), 3),
        "sma_short": round(float(last["sma_short"]), 2),
        "sma_long": round(float(last["sma_long"]), 2),
        "atr": round(float(last["atr"]), 4),
        "vol_ratio": round(vol_ratio, 2),
        "signals": signals,
        "score": round(score, 4),   # -1 (muy bajista) a +1 (muy alcista)
    }
