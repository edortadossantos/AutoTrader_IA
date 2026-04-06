"""
Señales profesionales de mercado vía Finnhub API (gratis, 60 req/min).

Señales implementadas:
  1. Insider Transactions  — cuando directivos compran/venden sus propias acciones
  2. Analyst Consensus     — rating agregado + upgrades/downgrades recientes
  3. Earnings Surprise     — si la empresa supera/falla estimaciones consistentemente
  4. Earnings Calendar     — aviso si hay earnings próximos (gestión de riesgo)
  5. Economic Calendar     — eventos macro críticos (FOMC, CPI, NFP)

Por qué importan:
  - Insiders compran → señal bullish de primer nivel (los directivos saben más)
  - Analyst upgrade    → mueve precio 3-8% en sesión
  - Earnings beat 4Q   → momentum comprador fiable
  - Earnings en 2 días → riesgo elevado, reducir posición
  - CPI/FOMC mañana   → volatilidad extrema esperada
"""
import logging
from datetime import datetime, timedelta, timezone

import requests

from config import FINNHUB_API_KEY, WATCHLIST

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. INSIDER TRANSACTIONS (Form 4 — SEC)
# ─────────────────────────────────────────────────────────────────────────────

def get_insider_signal(ticker: str) -> dict:
    """
    Analiza compras/ventas de insiders en los últimos 90 días.
    Score: +1.0 si compras netas fuertes, -1.0 si ventas masivas.

    Los insiders venden por mil razones (impuestos, diversificación),
    pero COMPRAN por una sola: creen que el precio va a subir.
    """
    if not FINNHUB_API_KEY:
        return {"signal": 0.0, "summary": "no_api_key"}
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/stock/insider-transactions",
            params={"symbol": ticker, "token": FINNHUB_API_KEY},
            timeout=8,
        )
        data = r.json().get("data", [])
        if not data:
            return {"signal": 0.0, "summary": "no_data"}

        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        buys = sells = 0
        buy_value = sell_value = 0.0

        for tx in data:
            try:
                tx_date = datetime.fromisoformat(tx.get("transactionDate", "1970-01-01"))
                if tx_date.tzinfo is None:
                    tx_date = tx_date.replace(tzinfo=timezone.utc)
                if tx_date < cutoff:
                    continue
            except Exception:
                continue

            code = tx.get("transactionCode", "")
            change = tx.get("change", 0) or 0
            price = tx.get("transactionPrice", 0) or 0
            value = abs(change) * price

            if code == "P":  # Purchase
                buys += 1
                buy_value += value
            elif code == "S":  # Sale
                sells += 1
                sell_value += value

        net_value = buy_value - sell_value * 0.3  # ventas pesan menos (normales)
        total = buy_value + sell_value * 0.3

        if total == 0:
            score = 0.0
        else:
            score = max(-1.0, min(1.0, net_value / total))

        return {
            "signal":     round(score, 4),
            "buys_90d":   buys,
            "sells_90d":  sells,
            "buy_value":  round(buy_value, 0),
            "sell_value": round(sell_value, 0),
            "summary":    "bullish_insiders" if score > 0.3 else ("bearish_insiders" if score < -0.3 else "neutral"),
        }
    except Exception as e:
        logger.debug(f"Insider signal {ticker}: {e}")
        return {"signal": 0.0, "summary": "error"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. ANALYST CONSENSUS + UPGRADES/DOWNGRADES
# ─────────────────────────────────────────────────────────────────────────────

def get_analyst_signal(ticker: str) -> dict:
    """
    Combina:
      a) Consenso actual (strongBuy/buy vs sell/strongSell)
      b) Upgrades/downgrades recientes (últimos 30 días) — más relevantes

    Un upgrade reciente de Goldman/Morgan Stanley mueve el precio más que
    cualquier noticia de RSS.
    """
    if not FINNHUB_API_KEY:
        return {"signal": 0.0, "summary": "no_api_key"}
    try:
        # Consenso
        r = requests.get(
            "https://finnhub.io/api/v1/stock/recommendation",
            params={"symbol": ticker, "token": FINNHUB_API_KEY},
            timeout=8,
        )
        recs = r.json()
        consensus_score = 0.0
        if recs:
            latest = recs[0]
            strong_buy = latest.get("strongBuy", 0)
            buy        = latest.get("buy", 0)
            hold       = latest.get("hold", 0)
            sell       = latest.get("sell", 0)
            strong_sell = latest.get("strongSell", 0)
            total = strong_buy + buy + hold + sell + strong_sell
            if total > 0:
                # Ponderación: strongBuy=+2, buy=+1, hold=0, sell=-1, strongSell=-2
                weighted = (strong_buy * 2 + buy * 1 + sell * -1 + strong_sell * -2)
                consensus_score = max(-1.0, min(1.0, weighted / (total * 2)))

        # Upgrades/downgrades últimos 30 días
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        r2 = requests.get(
            "https://finnhub.io/api/v1/stock/upgrade-downgrade",
            params={"symbol": ticker, "from": since, "token": FINNHUB_API_KEY},
            timeout=8,
        )
        changes = r2.json() if isinstance(r2.json(), list) else []
        upgrade_boost = 0.0
        recent_changes = []
        for c in changes[:5]:
            to_grade   = (c.get("toGrade") or "").lower()
            from_grade = (c.get("fromGrade") or "").lower()
            firm       = c.get("company", "")
            action     = c.get("action", "").lower()

            boost = 0.0
            if action in ("upgrade", "reiterated") and any(g in to_grade for g in ["buy", "outperform", "overweight", "positive"]):
                boost = 0.3
            elif action == "downgrade" or any(g in to_grade for g in ["sell", "underperform", "underweight", "reduce"]):
                boost = -0.3
            upgrade_boost += boost
            if boost != 0:
                recent_changes.append({"firm": firm, "action": action, "to": to_grade})

        upgrade_boost = max(-1.0, min(1.0, upgrade_boost))
        # 40% consenso + 60% cambios recientes (más informativos)
        final = consensus_score * 0.40 + upgrade_boost * 0.60

        return {
            "signal":         round(final, 4),
            "consensus_score": round(consensus_score, 4),
            "upgrade_boost":  round(upgrade_boost, 4),
            "recent_changes": recent_changes,
            "summary":        "bullish_analysts" if final > 0.2 else ("bearish_analysts" if final < -0.2 else "neutral"),
        }
    except Exception as e:
        logger.debug(f"Analyst signal {ticker}: {e}")
        return {"signal": 0.0, "summary": "error"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. EARNINGS SURPRISE (momentum de estimaciones)
# ─────────────────────────────────────────────────────────────────────────────

def get_earnings_surprise_signal(ticker: str) -> dict:
    """
    Si una empresa bate estimaciones consistentemente, suele continuar haciéndolo.
    Score basado en los últimos 4 quarters de surprise%.

    Empresas que baten >3% cada quarter tienen momentum comprador sostenido.
    """
    if not FINNHUB_API_KEY:
        return {"signal": 0.0, "summary": "no_api_key"}
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/stock/earnings",
            params={"symbol": ticker, "limit": 4, "token": FINNHUB_API_KEY},
            timeout=8,
        )
        quarters = r.json()
        if not quarters:
            return {"signal": 0.0, "summary": "no_data"}

        surprises = []
        for q in quarters:
            sp = q.get("surprisePercent")
            if sp is not None:
                surprises.append(float(sp))

        if not surprises:
            return {"signal": 0.0, "summary": "no_surprise_data"}

        avg = sum(surprises) / len(surprises)
        # Normalizar: 10% surprise → score ~1.0
        score = max(-1.0, min(1.0, avg / 10.0))

        # Bonus si el último quarter es el mejor (aceleración)
        if len(surprises) >= 2 and surprises[0] > surprises[1]:
            score = min(1.0, score * 1.2)

        return {
            "signal":           round(score, 4),
            "avg_surprise_pct": round(avg, 2),
            "last_4_quarters":  [round(s, 2) for s in surprises],
            "summary":          "strong_beats" if score > 0.3 else ("misses" if score < -0.2 else "inline"),
        }
    except Exception as e:
        logger.debug(f"Earnings surprise {ticker}: {e}")
        return {"signal": 0.0, "summary": "error"}


# ─────────────────────────────────────────────────────────────────────────────
# 4. EARNINGS CALENDAR (gestión de riesgo)
# ─────────────────────────────────────────────────────────────────────────────

def get_earnings_risk(ticker: str, upcoming_earnings: list[dict]) -> dict:
    """
    Retorna nivel de riesgo si hay earnings próximos.
    - earnings en ≤2 días → riesgo ALTO (reducir posición)
    - earnings en ≤7 días → riesgo MEDIO (no abrir nuevas)
    - sin earnings próximos → riesgo BAJO
    """
    today = datetime.utcnow().date()
    for event in upcoming_earnings:
        if event.get("symbol") != ticker:
            continue
        try:
            ed = datetime.strptime(event["date"], "%Y-%m-%d").date()
            days_away = (ed - today).days
            if 0 <= days_away <= 2:
                return {"risk": "HIGH", "earnings_in_days": days_away, "date": event["date"]}
            if 0 <= days_away <= 7:
                return {"risk": "MEDIUM", "earnings_in_days": days_away, "date": event["date"]}
        except Exception:
            continue
    return {"risk": "LOW", "earnings_in_days": None, "date": None}


def fetch_upcoming_earnings(days_ahead: int = 14) -> list[dict]:
    """Earnings de los próximos N días para todos los tickers del watchlist."""
    if not FINNHUB_API_KEY:
        return []
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        until = (datetime.utcnow() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": today, "to": until, "token": FINNHUB_API_KEY},
            timeout=10,
        )
        return r.json().get("earningsCalendar", [])
    except Exception as e:
        logger.debug(f"Earnings calendar: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 5. ECONOMIC CALENDAR (eventos macro que mueven todo el mercado)
# ─────────────────────────────────────────────────────────────────────────────

# Eventos macro de alta importancia que distorsionan señales técnicas
HIGH_IMPACT_EVENTS = [
    "fed", "fomc", "federal reserve", "interest rate decision",
    "cpi", "consumer price index", "inflation",
    "nonfarm payroll", "nfp", "unemployment", "jobs",
    "gdp", "gross domestic product",
    "pce", "personal consumption",
    "retail sales",
    "ism manufacturing", "ism services",
    "earnings season",
]

def fetch_economic_calendar(days_ahead: int = 7) -> list[dict]:
    """Eventos macro próximos con impacto estimado."""
    if not FINNHUB_API_KEY:
        return []
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        until = (datetime.utcnow() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": today, "to": until, "token": FINNHUB_API_KEY},
            timeout=10,
        )
        events = r.json().get("economicCalendar", [])
        # Filtrar solo eventos de alto impacto
        high_impact = []
        for e in events:
            name = (e.get("event") or "").lower()
            if any(kw in name for kw in HIGH_IMPACT_EVENTS):
                high_impact.append({
                    "event":  e.get("event"),
                    "date":   e.get("time", "")[:10],
                    "time":   e.get("time", ""),
                    "impact": e.get("impact", ""),
                    "country": e.get("country", ""),
                })
        return high_impact
    except Exception as e:
        logger.debug(f"Economic calendar: {e}")
        return []


def get_macro_risk(economic_events: list[dict]) -> dict:
    """
    Evalúa si hay eventos macro inminentes que requieran reducir exposición.
    Retorna nivel de riesgo macro y lista de eventos.
    """
    today = datetime.utcnow().date()
    imminent = []   # ≤1 día
    upcoming = []   # 2-3 días

    for e in economic_events:
        try:
            ed = datetime.strptime(e["date"], "%Y-%m-%d").date()
            days_away = (ed - today).days
            if 0 <= days_away <= 1:
                imminent.append(e)
            elif days_away <= 3:
                upcoming.append(e)
        except Exception:
            continue

    if imminent:
        return {"risk": "HIGH", "reason": "macro_event_today_tomorrow", "events": imminent}
    if upcoming:
        return {"risk": "MEDIUM", "reason": "macro_event_this_week", "events": upcoming}
    return {"risk": "LOW", "reason": "clear", "events": []}


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador: señal pro combinada para un ticker
# ─────────────────────────────────────────────────────────────────────────────

def get_pro_signal(
    ticker: str,
    upcoming_earnings: list[dict] | None = None,
    economic_events: list[dict] | None = None,
) -> dict:
    """
    Señal profesional combinada para un ticker.
    Pesos: Analyst 40% + Earnings surprise 35% + Insider 25%

    Aparte, retorna flags de riesgo (earnings próximos, macro).
    """
    analyst   = get_analyst_signal(ticker)
    earnings  = get_earnings_surprise_signal(ticker)
    insider   = get_insider_signal(ticker)

    # Score compuesto
    score = (
        analyst["signal"]  * 0.40 +
        earnings["signal"] * 0.35 +
        insider["signal"]  * 0.25
    )

    earnings_risk = get_earnings_risk(ticker, upcoming_earnings or [])
    macro_risk    = get_macro_risk(economic_events or [])

    # Si hay riesgo alto (earnings o macro) → atenuar señal
    if earnings_risk["risk"] == "HIGH" or macro_risk["risk"] == "HIGH":
        score *= 0.3   # señal muy atenuada — mejor no operar
    elif earnings_risk["risk"] == "MEDIUM" or macro_risk["risk"] == "MEDIUM":
        score *= 0.7

    return {
        "ticker":          ticker,
        "pro_score":       round(score, 4),
        "analyst":         analyst,
        "earnings":        earnings,
        "insider":         insider,
        "earnings_risk":   earnings_risk,
        "macro_risk":      macro_risk,
    }


def run_pro_signals() -> dict:
    """
    Ejecuta todas las señales profesionales para el watchlist completo.
    Llamar cada 15-30 min (no más — límite 60 req/min en plan gratis).
    """
    logger.info("Actualizando señales profesionales (Finnhub)...")

    upcoming_earnings = fetch_upcoming_earnings(days_ahead=14)
    economic_events   = fetch_economic_calendar(days_ahead=7)

    results: dict[str, dict] = {}
    for ticker in WATCHLIST:
        results[ticker] = get_pro_signal(ticker, upcoming_earnings, economic_events)

    logger.info(f"  Pro signals OK — {len(results)} tickers, "
                f"{len(upcoming_earnings)} earnings próximos, "
                f"{len(economic_events)} eventos macro")

    return {
        "ticker_signals":   results,
        "upcoming_earnings": upcoming_earnings[:20],
        "economic_events":   economic_events,
        "updated_at":        datetime.utcnow().isoformat(),
    }
