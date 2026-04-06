"""
Detector de horario de mercado multi-activo.

  • Crypto (BTC-USD, ETH-USD, SOL-USD):  abierto 24/7/365
  • Commodities futuros (GC=F, CL=F…):   CME 23h/día, cierra 1h (17:00-18:00 ET)
  • US Stocks / ETFs:                     NYSE/Nasdaq 9:30-16:00 ET, L-V
  • ETFs internacionales (EFA, EEM…):     siguen horario NYSE
"""
from datetime import datetime, date, time, timedelta
import logging

logger = logging.getLogger(__name__)

# ── Festivos NYSE 2025-2026 ──────────────────────────────────────
NYSE_HOLIDAYS = {
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
}

OPEN_ET  = time(9, 30)
CLOSE_ET = time(16, 0)

# ── Horario CME (futuros) en ET: 18:00 domingo – 17:00 viernes, pausa 17:00-18:00 ──
CME_PAUSE_START = time(17, 0)
CME_PAUSE_END   = time(18, 0)


def _is_dst(dt: datetime) -> bool:
    year = dt.year
    march = date(year, 3, 1)
    dst_start = march.replace(day=8 + (6 - march.weekday()) % 7)
    nov = date(year, 11, 1)
    dst_end = nov.replace(day=(6 - nov.weekday()) % 7 + 1)
    return dst_start <= dt.date() < dst_end


def utc_to_et(utc_dt: datetime) -> datetime:
    offset = -4 if _is_dst(utc_dt) else -5
    return utc_dt + timedelta(hours=offset)


# ────────────────────────────────────────────────────────────────

def is_crypto(ticker: str) -> bool:
    return ticker.endswith("-USD") or ticker.endswith("-USDT")


def is_futures(ticker: str) -> bool:
    return ticker.endswith("=F")


def is_market_open(utc_dt: datetime = None, ticker: str = "") -> bool:
    """
    True si el mercado del activo está abierto ahora.
    Sin ticker → evalúa NYSE por defecto.
    """
    if utc_dt is None:
        utc_dt = datetime.utcnow()

    # Crypto: siempre abierto
    if is_crypto(ticker):
        return True

    et = utc_to_et(utc_dt)

    # Futuros CME: abierto L-V 18:00-17:00 ET (con pausa 1h)
    if is_futures(ticker):
        # Cerrado sábado después de 17:00 ET y domingo antes de 18:00 ET
        weekday = et.weekday()  # 0=lun, 5=sab, 6=dom
        t = et.time()
        if weekday == 5:  # sábado: CME cierra a las 17:00
            return t < CME_PAUSE_START
        if weekday == 6:  # domingo: CME abre a las 18:00
            return t >= CME_PAUSE_END
        # L-V: cierra 1h entre 17:00 y 18:00
        return not (CME_PAUSE_START <= t < CME_PAUSE_END)

    # NYSE/Nasdaq
    if et.weekday() >= 5:
        return False
    if et.date() in NYSE_HOLIDAYS:
        return False
    return OPEN_ET <= et.time() < CLOSE_ET


def should_scan_now(tickers: list[str], utc_dt: datetime = None) -> dict[str, bool]:
    """Retorna qué tickers están en horario de mercado ahora."""
    if utc_dt is None:
        utc_dt = datetime.utcnow()
    return {t: is_market_open(utc_dt, t) for t in tickers}


def next_market_open_utc() -> datetime:
    """Próxima apertura NYSE en UTC (para el sleep nocturno)."""
    now_utc = datetime.utcnow()
    et = utc_to_et(now_utc)
    candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)
    if et >= candidate:
        candidate += timedelta(days=1)
    for _ in range(10):
        if candidate.weekday() < 5 and candidate.date() not in NYSE_HOLIDAYS:
            break
        candidate += timedelta(days=1)
    offset = -4 if _is_dst(candidate) else -5
    return candidate + timedelta(hours=-offset)


def market_status(utc_dt: datetime = None) -> dict:
    """Estado detallado del mercado NYSE (para el dashboard)."""
    if utc_dt is None:
        utc_dt = datetime.utcnow()
    et = utc_to_et(utc_dt)
    open_now = is_market_open(utc_dt)

    if open_now:
        status = "ABIERTO"
        close_dt = et.replace(hour=16, minute=0, second=0, microsecond=0)
        mins_left = int((close_dt - et).total_seconds() / 60)
        detail = f"Cierra en {mins_left // 60}h {mins_left % 60}min (ET)"
    elif et.weekday() >= 5:
        status = "CERRADO"
        detail = "Fin de semana (crypto activo 24/7)"
    elif et.date() in NYSE_HOLIDAYS:
        status = "CERRADO"
        detail = "Festivo NYSE (crypto activo 24/7)"
    elif et.time() < OPEN_ET:
        status = "PRE-MARKET"
        open_dt = et.replace(hour=9, minute=30, second=0, microsecond=0)
        mins_left = int((open_dt - et).total_seconds() / 60)
        detail = f"Abre en {mins_left // 60}h {mins_left % 60}min"
    else:
        status = "AFTER-HOURS"
        detail = "Mercado cerrado hasta mañana 9:30 ET"

    return {
        "open":     open_now,
        "status":   status,
        "detail":   detail,
        "et_time":  et.strftime("%H:%M ET"),
        "utc_time": utc_dt.strftime("%H:%M UTC"),
        "crypto_active": True,  # siempre
    }
