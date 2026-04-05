"""
Detector de horario de mercado NYSE.
Usa pytz para manejar correctamente el horario ET (EST/EDT según la época).
No requiere librerías externas de festivos — lista los días festivos de NYSE manualmente.
"""
from datetime import datetime, date, time
import logging

logger = logging.getLogger(__name__)

# Festivos NYSE 2025-2026 (fechas en que el mercado está cerrado)
NYSE_HOLIDAYS = {
    # 2025
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # MLK Day
    date(2025, 2, 17),  # Presidents Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
    # 2026
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}

# NYSE horario ET: 9:30 - 16:00
# En UTC: 14:30-21:00 (invierno, EST = UTC-5) / 13:30-20:00 (verano, EDT = UTC-4)
OPEN_ET  = time(9, 30)
CLOSE_ET = time(16, 0)


def _is_dst(dt: datetime) -> bool:
    """Determina si Nueva York está en horario de verano (EDT, UTC-4)."""
    # DST en EE.UU.: segundo domingo de marzo → primer domingo de noviembre
    year = dt.year
    # Segundo domingo de marzo
    march = date(year, 3, 1)
    dst_start = march.replace(day=8 + (6 - march.weekday()) % 7)
    # Primer domingo de noviembre
    nov = date(year, 11, 1)
    dst_end = nov.replace(day=(6 - nov.weekday()) % 7 + 1)
    d = dt.date()
    return dst_start <= d < dst_end


def utc_to_et(utc_dt: datetime) -> datetime:
    from datetime import timedelta
    offset = -4 if _is_dst(utc_dt) else -5
    return utc_dt + timedelta(hours=offset)


def is_market_open(utc_dt: datetime = None) -> bool:
    """True si el mercado NYSE está abierto en este momento."""
    if utc_dt is None:
        utc_dt = datetime.utcnow()

    et = utc_to_et(utc_dt)

    # Fin de semana
    if et.weekday() >= 5:
        return False

    # Festivo
    if et.date() in NYSE_HOLIDAYS:
        return False

    # Horario de apertura
    current_time = et.time()
    return OPEN_ET <= current_time < CLOSE_ET


def next_market_open_utc() -> datetime:
    """Retorna el UTC datetime de la próxima apertura NYSE."""
    from datetime import timedelta
    now_utc = datetime.utcnow()
    et = utc_to_et(now_utc)

    # Candidato: apertura de hoy a las 9:30
    candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)

    # Si ya pasó (o mercado está abierto), empezar desde mañana
    if et >= candidate:
        candidate += timedelta(days=1)

    # Saltar fines de semana y festivos
    for _ in range(10):
        if candidate.weekday() < 5 and candidate.date() not in NYSE_HOLIDAYS:
            break
        candidate += timedelta(days=1)

    # ET → UTC (revertir el offset que aplicó utc_to_et)
    offset = -4 if _is_dst(candidate) else -5
    return candidate + timedelta(hours=-offset)  # ET + |offset| = UTC


def market_status(utc_dt: datetime = None) -> dict:
    """Retorna estado detallado del mercado."""
    if utc_dt is None:
        utc_dt = datetime.utcnow()

    et = utc_to_et(utc_dt)
    open_now = is_market_open(utc_dt)

    if open_now:
        status = "ABIERTO"
        # Tiempo hasta cierre
        close_dt = et.replace(hour=16, minute=0, second=0, microsecond=0)
        mins_left = int((close_dt - et).total_seconds() / 60)
        detail = f"Cierra en {mins_left // 60}h {mins_left % 60}min (ET)"
    elif et.weekday() >= 5:
        status = "CERRADO"
        detail = "Fin de semana"
    elif et.date() in NYSE_HOLIDAYS:
        status = "CERRADO"
        detail = "Festivo NYSE"
    elif et.time() < OPEN_ET:
        status = "PRE-MARKET"
        open_dt = et.replace(hour=9, minute=30, second=0, microsecond=0)
        mins_left = int((open_dt - et).total_seconds() / 60)
        detail = f"Abre en {mins_left // 60}h {mins_left % 60}min"
    else:
        status = "AFTER-HOURS"
        detail = "Mercado cerrado hasta manana 9:30 ET"

    return {
        "open": open_now,
        "status": status,
        "detail": detail,
        "et_time": et.strftime("%H:%M ET"),
        "utc_time": utc_dt.strftime("%H:%M UTC"),
    }
