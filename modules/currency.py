"""
Conversión USD ↔ EUR en tiempo real usando yfinance (gratis, sin API key).
"""
import time
import logging
import yfinance as yf
from config import DISPLAY_CURRENCY

logger = logging.getLogger(__name__)

_cache = {"rate": None, "ts": 0}
_CACHE_TTL = 300  # segundos


def get_usd_eur_rate() -> float:
    """Retorna cuántos EUR vale 1 USD. Cache de 5 min."""
    if DISPLAY_CURRENCY == "USD":
        return 1.0
    now = time.time()
    if _cache["rate"] and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["rate"]
    try:
        ticker = yf.Ticker("EURUSD=X")
        rate_eur_per_usd = float(ticker.fast_info.last_price)  # EUR por 1 USD
        _cache["rate"] = rate_eur_per_usd
        _cache["ts"] = now
        logger.debug(f"Tipo de cambio EUR/USD actualizado: {rate_eur_per_usd:.4f}")
        return rate_eur_per_usd
    except Exception as e:
        logger.warning(f"No se pudo obtener tipo de cambio: {e}")
        return _cache["rate"] or 0.92  # fallback aproximado


def to_display(usd_amount: float) -> float:
    """Convierte USD al importe en la moneda configurada."""
    if DISPLAY_CURRENCY == "USD":
        return usd_amount
    return usd_amount * get_usd_eur_rate()


def currency_symbol() -> str:
    return "€" if DISPLAY_CURRENCY == "EUR" else "$"


def format_currency(usd_amount: float, decimals: int = 2) -> str:
    sym = currency_symbol()
    val = to_display(usd_amount)
    return f"{sym}{val:,.{decimals}f}"
