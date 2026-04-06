"""
Detector de flujo inusual de opciones.

Fuentes (todas gratuitas/scraping):
  1. Barchart Unusual Options Activity  — scraping HTML
  2. Finviz Options Scanner              — scraping HTML

Cómo funciona:
  • Descarga la lista de opciones con volumen muy superior al open interest
  • Identifica si el flujo es alcista (calls) o bajista (puts)
  • Genera una señal por ticker que se usa en combined_strategy.py

Caché: 15 minutos (no sobrecargar las fuentes).
El score de opciones va del -1 (muy bajista) al +1 (muy alcista).
"""
import logging
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_cache: dict = {"data": {}, "updated_at": None}
_CACHE_MIN = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _fetch_barchart_unusual() -> list[dict]:
    """
    Scraping de Barchart unusual options activity.
    Retorna lista de {ticker, type, score} donde type='call'/'put'.
    """
    try:
        # Barchart ofrece un endpoint JSON en su sitio
        url = "https://www.barchart.com/options/unusual-activity/stocks"
        # Primero obtenemos la cookie de sesión
        session = requests.Session()
        session.get("https://www.barchart.com", headers=HEADERS, timeout=10)

        # Luego el endpoint de datos (CSV descargable con autenticación de cookie)
        api_url = "https://www.barchart.com/proxies/core-api/v1/options/unusual-activity"
        params = {
            "fields": "symbol,optionType,volume,openInterest,volumeOpenInterestRatio,tradeTime,strikePrice,expirationDate,lastPrice,baseLastPrice",
            "orderBy": "volumeOpenInterestRatio",
            "orderDir": "desc",
            "meta": "field.shortName,field.type,field.description",
            "hasOptions": "true",
            "page": 1,
            "limit": 100,
        }
        r = session.get(api_url, params=params, headers={
            **HEADERS,
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        }, timeout=12)

        if r.status_code != 200:
            return _fetch_barchart_html(session)

        data = r.json().get("data", [])
        results = []
        for item in data:
            row = item.get("raw", item)
            ticker = row.get("symbol", "")
            opt_type = row.get("optionType", "").lower()
            vol = row.get("volume", 0) or 0
            oi = row.get("openInterest", 1) or 1
            ratio = vol / oi if oi > 0 else 0

            if not ticker or ratio < 2:
                continue

            # Score: calls → positivo, puts → negativo, ponderado por ratio
            score = min(1.0, ratio / 20.0)
            if opt_type == "put":
                score = -score

            results.append({"ticker": ticker, "type": opt_type, "score": score, "ratio": ratio})

        return results

    except Exception as e:
        logger.debug(f"Barchart API unusual: {e}")
        return []


def _fetch_barchart_html(session: requests.Session | None = None) -> list[dict]:
    """Fallback: scraping HTML de Barchart si el JSON falla."""
    try:
        from bs4 import BeautifulSoup
        s = session or requests.Session()
        url = "https://www.barchart.com/options/unusual-activity/stocks"
        r = s.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")

        results = []
        table = soup.find("table")
        if not table:
            return []

        for row in table.find_all("tr")[1:51]:  # primeras 50 filas
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) < 6:
                continue
            ticker = cols[0].split()[0].upper()
            opt_type = "call" if "call" in cols[2].lower() else "put"
            try:
                ratio = float(cols[5].replace("x", "").replace(",", "")) if cols[5] else 0
            except ValueError:
                ratio = 0

            score = min(1.0, ratio / 20.0)
            if opt_type == "put":
                score = -score

            results.append({"ticker": ticker, "type": opt_type, "score": score, "ratio": ratio})

        return results

    except Exception as e:
        logger.debug(f"Barchart HTML fallback: {e}")
        return []


def _fetch_finviz_options() -> list[dict]:
    """
    Finviz options scanner — identifica acciones con alto volumen de opciones.
    Complementa a Barchart con señales de dirección menos precisas.
    """
    try:
        from bs4 import BeautifulSoup
        url = "https://finviz.com/screener.ashx?v=111&s=ta_unusualvolume&f=optionable_yes&o=-volume"
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")

        results = []
        # Finviz tabla de screener
        table = soup.find("table", {"id": "screener-views-table"})
        if not table:
            # Intentar selector alternativo
            table = soup.find("table", class_="screener_table")
        if not table:
            return []

        for row in table.find_all("tr")[1:31]:
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) < 2:
                continue
            ticker = cols[0].strip().upper()
            if not ticker or len(ticker) > 5:
                continue
            # Sin dirección clara → score neutro-positivo (volumen alto = interés)
            results.append({"ticker": ticker, "type": "unknown", "score": 0.25, "ratio": 0})

        return results

    except Exception as e:
        logger.debug(f"Finviz options: {e}")
        return []


def get_options_flow() -> dict[str, float]:
    """
    Retorna dict {ticker: score} donde score ∈ [-1, +1].
      +1 = flujo de calls muy alcista (alguien sabe algo positivo)
      -1 = flujo de puts muy bajista
       0 = sin señal

    Resultados cacheados 15 minutos.
    """
    now = datetime.utcnow()
    if (
        _cache["updated_at"]
        and (now - _cache["updated_at"]) < timedelta(minutes=_CACHE_MIN)
        and _cache["data"]
    ):
        return _cache["data"]

    # Obtener de ambas fuentes
    barchart = _fetch_barchart_unusual()
    finviz   = _fetch_finviz_options()

    # Combinar: Barchart tiene prioridad (más preciso)
    combined: dict[str, float] = {}
    for item in finviz:
        t = item["ticker"]
        combined[t] = item["score"]  # base de finviz (baja confianza)
    for item in barchart:
        t = item["ticker"]
        # Si Barchart confirma la dirección → score más fuerte
        if t in combined and combined[t] * item["score"] > 0:
            combined[t] = max(abs(combined[t]), abs(item["score"])) * (1 if item["score"] > 0 else -1)
        else:
            combined[t] = item["score"]  # Barchart gana

    if combined:
        logger.info(
            f"Options flow: {len(combined)} tickers detectados. "
            f"Alcistas: {sum(1 for v in combined.values() if v > 0.3)} | "
            f"Bajistas: {sum(1 for v in combined.values() if v < -0.3)}"
        )
        # Alertas para los más extremos
        try:
            from modules import telegram_notifier as tg
            from config import WATCHLIST
            for ticker, score in combined.items():
                if ticker in WATCHLIST and abs(score) >= 0.5:
                    flow_type = "bullish" if score > 0 else "bearish"
                    tg.notify_options_alert(ticker, flow_type, abs(score))
        except Exception:
            pass
    else:
        logger.debug("Options flow: sin datos (fuentes no accesibles)")

    _cache["data"] = combined
    _cache["updated_at"] = now
    return combined


def get_ticker_options_score(ticker: str) -> float:
    """Score de opciones para un ticker específico. 0.0 si no hay datos."""
    return get_options_flow().get(ticker, 0.0)
