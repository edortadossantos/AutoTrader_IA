"""
Capa unificada de datos de mercado.

Prioridad de precios:
  1. Alpaca IEX  (acciones US / ETFs)   — tiempo real, gratis
  2. Alpaca Crypto (BTC/ETH/etc.)       — tiempo real, gratis
  3. yfinance                           — fallback universal (15 min delay en US stocks)

Commodities (GC=F, CL=F, SI=F) → siempre yfinance (Alpaca no soporta futuros).

Funciones públicas:
  get_price(symbol)          → float | None
  get_prices_batch(symbols)  → dict[str, float]
  get_volume(symbol)         → dict {current, avg_20, ratio}
  get_sentiment()            → float [-1, +1]   (Polymarket + Kalshi, macro)
  get_event_data()           → dict              (Finnhub economic calendar)
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────
from config import ALPACA_API_KEY, ALPACA_API_SECRET

_STOCK_BASE  = "https://data.alpaca.markets/v2"
_CRYPTO_BASE = "https://data.alpaca.markets/v1beta3/crypto/us"
_TIMEOUT     = 7

# Tickers que solo yfinance puede manejar (futuros, índices Yahoo-específicos)
_YFINANCE_ONLY = {"GC=F", "CL=F", "SI=F", "HG=F", "NG=F", "ZC=F", "ZS=F"}

# Mapeo yfinance → símbolo Alpaca crypto
_CRYPTO_MAP: dict[str, str] = {
    "BTC-USD":  "BTC/USD",
    "ETH-USD":  "ETH/USD",
    "SOL-USD":  "SOL/USD",
    "BNB-USD":  "BNB/USD",
    "XRP-USD":  "XRP/USD",
    "AVAX-USD": "AVAX/USD",
    "LINK-USD": "LINK/USD",
    "DOGE-USD": "DOGE/USD",
    "ADA-USD":  "ADA/USD",
    "DOT-USD":  "DOT/USD",
}

# ── Cache en memoria ─────────────────────────────────────────────────────
_price_cache:  dict[str, dict] = {}
_volume_cache: dict[str, dict] = {}
_PRICE_TTL  = 30   # segundos — precio fresco por 30s
_VOLUME_TTL = 60   # segundos — volumen fresco por 60s


def _is_fresh(entry: dict, ttl: int) -> bool:
    return (datetime.utcnow() - entry["ts"]).total_seconds() < ttl


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
    }


def _retry(fn, retries: int = 2, delay: float = 0.4):
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == retries:
                raise
            logger.debug(f"Retry {attempt + 1}/{retries}: {e}")
            time.sleep(delay)


# ── Precio individual ─────────────────────────────────────────────────────

def _alpaca_stock_price(symbol: str) -> Optional[float]:
    r = requests.get(
        f"{_STOCK_BASE}/stocks/{symbol}/trades/latest",
        headers=_headers(),
        params={"feed": "iex"},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return float(r.json()["trade"]["p"])


def _alpaca_crypto_price(alpaca_sym: str) -> Optional[float]:
    r = requests.get(
        f"{_CRYPTO_BASE}/latest/trades",
        headers=_headers(),
        params={"symbols": alpaca_sym},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    trades = r.json().get("trades", {})
    return float(trades[alpaca_sym]["p"]) if alpaca_sym in trades else None


def _yfinance_price(symbol: str) -> Optional[float]:
    try:
        return float(yf.Ticker(symbol).fast_info.last_price)
    except Exception:
        return None


def get_price(symbol: str) -> Optional[float]:
    """Precio con caché 30 s. Alpaca → yfinance fallback."""
    cached = _price_cache.get(symbol)
    if cached and _is_fresh(cached, _PRICE_TTL):
        return cached["price"]

    price: Optional[float] = None

    if not ALPACA_API_KEY or symbol in _YFINANCE_ONLY:
        price = _yfinance_price(symbol)

    elif symbol in _CRYPTO_MAP:
        try:
            price = _retry(lambda: _alpaca_crypto_price(_CRYPTO_MAP[symbol]))
        except Exception as e:
            logger.warning(f"[{symbol}] Alpaca crypto error: {e} — yfinance fallback")
            price = _yfinance_price(symbol)

    else:
        try:
            price = _retry(lambda: _alpaca_stock_price(symbol))
        except Exception as e:
            logger.warning(f"[{symbol}] Alpaca stock error: {e} — yfinance fallback")
            price = _yfinance_price(symbol)

    if price and price > 0:
        _price_cache[symbol] = {"price": price, "ts": datetime.utcnow()}
    return price


# ── Precios en batch (1-2 llamadas para todos los símbolos) ──────────────

def get_prices_batch(symbols: list[str]) -> dict[str, float]:
    """
    Separa por tipo, hace llamadas batch mínimas.
    Stocks/ETFs → 1 llamada Alpaca.
    Crypto      → 1 llamada Alpaca crypto.
    Commodities → yfinance thread pool.
    Cualquier fallo → yfinance individual.
    """
    if not symbols:
        return {}

    result: dict[str, float] = {}

    stock_syms  = [s for s in symbols if s not in _CRYPTO_MAP and s not in _YFINANCE_ONLY]
    crypto_syms = [s for s in symbols if s in _CRYPTO_MAP]
    yf_syms     = list({s for s in symbols if s in _YFINANCE_ONLY})

    # ── Stocks/ETFs batch ───────────────────────────────────────────────
    if ALPACA_API_KEY and stock_syms:
        try:
            r = requests.get(
                f"{_STOCK_BASE}/stocks/snapshots",
                headers=_headers(),
                params={"symbols": ",".join(stock_syms), "feed": "iex"},
                timeout=12,
            )
            r.raise_for_status()
            for sym, snap in r.json().items():
                try:
                    p = float(snap["latestTrade"]["p"])
                    result[sym] = p
                    _price_cache[sym] = {"price": p, "ts": datetime.utcnow()}
                except (KeyError, TypeError, ValueError):
                    pass
        except Exception as e:
            logger.warning(f"Batch stocks Alpaca error: {e} — yfinance fallback")

        # Los que no llegaron en la respuesta Alpaca → yfinance
        yf_syms += [s for s in stock_syms if s not in result]

    elif stock_syms:
        yf_syms += stock_syms

    # ── Crypto batch ─────────────────────────────────────────────────────
    if ALPACA_API_KEY and crypto_syms:
        alpaca_syms = [_CRYPTO_MAP[s] for s in crypto_syms]
        try:
            r = requests.get(
                f"{_CRYPTO_BASE}/snapshots",
                headers=_headers(),
                params={"symbols": ",".join(alpaca_syms)},
                timeout=12,
            )
            r.raise_for_status()
            snap_data = r.json().get("snapshots", {})
            for orig, alpaca in zip(crypto_syms, alpaca_syms):
                try:
                    p = float(snap_data[alpaca]["latestTrade"]["p"])
                    result[orig] = p
                    _price_cache[orig] = {"price": p, "ts": datetime.utcnow()}
                except (KeyError, TypeError, ValueError):
                    pass
        except Exception as e:
            logger.warning(f"Batch crypto Alpaca error: {e} — yfinance fallback")

        yf_syms += [s for s in crypto_syms if s not in result]

    elif crypto_syms:
        yf_syms += crypto_syms

    # ── yfinance fallback (commodities + cualquier fallo) ─────────────────
    yf_syms = list(set(yf_syms))
    if yf_syms:
        with ThreadPoolExecutor(max_workers=min(8, len(yf_syms))) as ex:
            futures = {ex.submit(_yfinance_price, s): s for s in yf_syms}
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    p = fut.result()
                    if p and p > 0:
                        result[sym] = p
                        _price_cache[sym] = {"price": p, "ts": datetime.utcnow()}
                except Exception:
                    pass

    return result


# ── Volumen ───────────────────────────────────────────────────────────────

def _alpaca_volume_stock(symbol: str) -> Optional[dict]:
    r = requests.get(
        f"{_STOCK_BASE}/stocks/{symbol}/bars",
        headers=_headers(),
        params={"timeframe": "1Min", "limit": 21, "feed": "iex", "sort": "asc"},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    bars = r.json().get("bars", [])
    if len(bars) < 5:
        return None
    vols = [b["v"] for b in bars]
    cur  = vols[-1]
    avg  = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else cur
    return {"current": float(cur), "avg_20": float(avg), "ratio": cur / (avg + 1e-9)}


def get_volume(symbol: str) -> dict:
    """Devuelve {current, avg_20, ratio}. ratio > 1.5 = spike real."""
    cached = _volume_cache.get(symbol)
    if cached and _is_fresh(cached, _VOLUME_TTL):
        return cached["data"]

    data = {"current": 0.0, "avg_20": 0.0, "ratio": 1.0}

    if ALPACA_API_KEY and symbol not in _CRYPTO_MAP and symbol not in _YFINANCE_ONLY:
        try:
            res = _retry(lambda: _alpaca_volume_stock(symbol))
            if res:
                data = res
        except Exception as e:
            logger.debug(f"[{symbol}] volume Alpaca error: {e}")

    _volume_cache[symbol] = {"data": data, "ts": datetime.utcnow()}
    return data


# ── Sentimiento macro (Polymarket + Kalshi) ───────────────────────────────

_sentiment_cache: dict = {"score": 0.0, "ts": None}
_SENTIMENT_TTL = 900   # 15 minutos — macro no cambia más rápido


def get_sentiment() -> float:
    """Score macro combinado [-1.0, +1.0]. Solo como bias de sesión, no señal directa."""
    if (_sentiment_cache["ts"]
            and (datetime.utcnow() - _sentiment_cache["ts"]).total_seconds() < _SENTIMENT_TTL):
        return _sentiment_cache["score"]

    score = 0.0
    try:
        from modules.prediction_markets import run_prediction_markets
        data  = run_prediction_markets()
        score = float(data.get("combined_signal", 0.0))
    except Exception as e:
        logger.warning(f"Sentiment fetch error: {e}")

    _sentiment_cache["score"] = score
    _sentiment_cache["ts"]    = datetime.utcnow()
    return score


# ── Eventos macro (Finnhub economic calendar) ────────────────────────────

def get_event_data() -> dict:
    """Eventos de alto impacto del calendario económico (FOMC, CPI, NFP)."""
    try:
        from modules.pro_signals import fetch_economic_calendar, get_macro_risk
        events = fetch_economic_calendar(days_ahead=2)
        return get_macro_risk(events)
    except Exception as e:
        logger.warning(f"Event data error: {e}")
        return {"signal": 0.0, "events": [], "high_impact_soon": False}
