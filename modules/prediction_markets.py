"""
Mercados de predicción — señales basadas en probabilidades de eventos macro.

Fuentes:
  - Polymarket (polymarket.com) — mayor mercado de predicción del mundo.
    API Gamma pública sin autenticación: https://gamma-api.polymarket.com
    Liquidez >$500M, miles de participantes con capital real.

  - Kalshi (kalshi.com) — único exchange de predicción regulado por CFTC en EEUU.
    API pública para datos de mercado: https://trading-api.kalshi.com
    Regulación federal garantiza integridad y liquidez institucional.

Por qué importan:
  - Agregación de expectativas de miles de traders con dinero real en juego
  - Probabilidades de: bajada tipos Fed, recesión, rendimiento S&P, resultados
    electorales, aprobaciones regulatorias, sanciones, etc.
  - Más eficientes que encuestas porque los participantes arriesgan capital real
  - Históricamente lideran los movimientos de mercado (información forward-looking)

Señal generada:
  +1.0 → mercados predicen entorno muy favorable (bajadas tipos, no recesión)
  -1.0 → mercados predicen entorno adverso (subida tipos, recesión inminente)
"""
import base64
import logging
import math
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 12
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# ── Palabras clave para clasificar mercados en Polymarket/Kalshi ─────────────
# Formato: (keyword, is_bullish)
# is_bullish=True  → YES de este mercado = bueno para mercados financieros
# is_bullish=False → YES de este mercado = malo para mercados financieros
_MARKET_KEYWORDS: list[tuple[str, bool]] = [
    # Fed — bajada de tipos = bullish para acciones y crypto
    ("fed decrease interest rates", True),
    ("fed cut", True),
    ("rate cut", True),
    ("cuts rates", True),
    ("rate reduction", True),
    ("lower rates", True),
    ("fed pivot", True),
    ("no change in fed interest rates", None),  # neutral (mantener = ni bullish ni bearish)
    ("rate hike", False),
    ("fed increase interest rates", False),
    ("hikes rates", False),
    ("rate increase", False),
    ("higher rates", False),
    # Bitcoin/Crypto — precio más alto = bullish
    ("price of bitcoin be above", True),    # "above X" → YES prob alta = bullish
    ("bitcoin reach", True),
    ("bitcoin above", True),
    ("bitcoin below", False),
    ("crypto etf approved", True),
    ("crypto ban", False),
    ("bitcoin etf", True),
    # Recesión
    ("recession", False),
    ("gdp contraction", False),
    ("no recession", True),
    ("soft landing", True),
    # Mercado de acciones
    ("bull market", True),
    ("market rally", True),
    ("market crash", False),
    ("bear market", False),
    ("s&p 500 above", True),
    ("s&p 500 below", False),
    ("nasdaq above", True),
    ("nasdaq below", False),
    # Inflación/macro
    ("inflation below", True),
    ("inflation above", False),
    ("cpi below", True),
    ("cpi above", False),
    ("stagflation", False),
    # Macro global
    ("gdp growth", True),
    ("strong jobs", True),
    ("debt ceiling", False),
    ("default", False),
    ("bank failure", False),
    ("tariff", False),
    ("trade war", False),
    # Volatilidad/crisis — resoluciones primero (más específicas que "iran"/"war")
    ("ceasefire", True),          # paz acordada = bullish (más específico que "iran")
    ("conflict ends", True),      # conflicto resuelto = bullish
    ("iran strike", False),       # ataque irani = bearish
    ("invade iran", False),       # EEUU invade Iran = escalada = bearish
    ("military action against iran", False),
    ("us declare war", False),
    ("iran", False),              # mención general Iran = incertidumbre = bearish
    ("war", False),               # guerra genérica = bearish
]


def _score_question(question: str, yes_prob: float) -> float | None:
    """
    Convierte una pregunta de predicción + probabilidad YES en un score bullish/bearish.
    Retorna None si la pregunta no es relevante para trading.
    None como is_bullish → mercado neutral (retorna 0.0 en lugar de ignorar).
    """
    q = question.lower()
    for keyword, is_bullish in _MARKET_KEYWORDS:
        if keyword in q:
            if is_bullish is None:
                return 0.0   # mercado relevante pero neutral (ej: "no change in Fed")
            # Normaliza 0-1 a -1..+1 centrado en 0.5
            raw = (yes_prob - 0.5) * 2
            return raw if is_bullish else -raw
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. POLYMARKET
# ─────────────────────────────────────────────────────────────────────────────

def get_polymarket_signal() -> dict:
    """
    Señal de Polymarket — mayor mercado de predicción descentralizado.

    Filtra mercados activos con >$50k volumen relacionados con Fed, recesión,
    y condiciones macro. Pondera por log(volumen) para dar más peso a los
    mercados con mayor liquidez.
    """
    try:
        r = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit":  200,
                "order":  "volume24hr",
                "ascending": "false",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        markets = r.json()
        if not isinstance(markets, list):
            return {"signal": 0.0, "summary": "no_data", "markets_used": 0}

        scores = []
        relevant = []

        for m in markets:
            question       = m.get("question", "")
            outcomes_prices = m.get("outcomePrices", [])
            volume         = float(m.get("volumeNum", 0) or 0)

            if volume < 50_000:
                continue

            try:
                # outcomePrices puede ser lista o string JSON '["0.73","0.27"]'
                if isinstance(outcomes_prices, str):
                    import json as _json
                    outcomes_prices = _json.loads(outcomes_prices)
                if isinstance(outcomes_prices, list) and len(outcomes_prices) >= 1:
                    yes_prob = float(outcomes_prices[0])
                else:
                    continue
            except (ValueError, TypeError):
                continue

            score = _score_question(question, yes_prob)
            if score is None:
                continue

            weight = math.log10(max(volume, 1))
            scores.append((score, weight))
            relevant.append({
                "question": question,
                "yes_prob": round(yes_prob, 3),
                "volume_usd": round(volume, 0),
                "signal": round(score, 3),
            })

        if not scores:
            return {"signal": 0.0, "summary": "no_relevant_markets", "markets_used": 0}

        total_weight   = sum(w for _, w in scores)
        weighted_score = sum(s * w for s, w in scores) / total_weight
        weighted_score = round(max(-1.0, min(1.0, weighted_score)), 4)
        summary = "bullish" if weighted_score > 0.15 else ("bearish" if weighted_score < -0.15 else "neutral")

        return {
            "signal":       weighted_score,
            "summary":      summary,
            "markets_used": len(relevant),
            "top_markets":  sorted(relevant, key=lambda x: abs(x["signal"]), reverse=True)[:5],
            "source":       "Polymarket",
        }

    except Exception as e:
        logger.debug(f"Polymarket signal error: {e}")
        return {"signal": 0.0, "summary": "error", "markets_used": 0}


# ─────────────────────────────────────────────────────────────────────────────
# 2. KALSHI
# ─────────────────────────────────────────────────────────────────────────────

def _kalshi_auth_headers(api_key_id: str, method: str, path: str) -> dict:
    """
    Genera headers de autenticación RSA para Kalshi API v2.
    Requiere kalshi_private.pem en el directorio raíz del proyecto.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

        pem_path = os.path.join(os.path.dirname(__file__), "..", "kalshi_private.pem")
        pem_path = os.path.abspath(pem_path)

        with open(pem_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)

        ts_ms = str(int(time.time() * 1000))
        msg   = (ts_ms + method.upper() + path).encode("utf-8")
        sig   = private_key.sign(
            msg,
            asym_padding.PSS(
                mgf=asym_padding.MGF1(hashes.SHA256()),
                salt_length=asym_padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        sig64 = base64.b64encode(sig).decode("utf-8")

        return {
            **_HEADERS,
            "KALSHI-ACCESS-KEY":       api_key_id,
            "KALSHI-ACCESS-SIGNATURE": sig64,
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        }
    except Exception as e:
        logger.debug(f"Kalshi RSA auth error: {e}")
        return _HEADERS


def _kalshi_fetch_series(api_key: str, series_ticker: str) -> list[dict]:
    """Descarga mercados de una serie Kalshi específica."""
    path = "/trade-api/v2/markets"
    base = "https://api.elections.kalshi.com"
    headers = _kalshi_auth_headers(api_key, "GET", path) if api_key else _HEADERS
    r = requests.get(
        base + path,
        params={"status": "open", "limit": 200, "series_ticker": series_ticker},
        headers=headers,
        timeout=_TIMEOUT,
    )
    return r.json().get("markets", [])


def _score_kalshi_range_markets(markets: list[dict], asset_name: str) -> tuple[float, float] | None:
    """
    Puntúa mercados de rango de precio (KXBTC, KXETH, KXWTI).

    Kalshi ofrece mercados binarios del tipo "¿estará BTC por encima de $X en fecha Y?".
    Hay múltiples strikes para el mismo subyacente. El strike con probabilidad ~50%
    es el precio implícito del mercado. Si el precio implícito > strike mediano → bullish.

    Retorna (score, weight) o None si no hay datos suficientes.
    """
    # Recoger (strike, yes_prob, volume) de cada mercado
    points = []
    for m in markets:
        subtitle = m.get("subtitle", "") or m.get("yes_sub_title", "") or ""
        strike   = m.get("floor_strike")
        if strike is None:
            continue
        strike = float(strike)

        bid_raw = m.get("yes_bid_dollars") or m.get("yes_bid") or 0
        ask_raw = m.get("yes_ask_dollars") or m.get("yes_ask") or 0
        try:
            bid = float(bid_raw)
            ask = float(ask_raw)
        except (TypeError, ValueError):
            continue

        # Kalshi dollars: 0.0 – 1.0 (probability). 0-100 scale requires /100 extra.
        # Check which scale: if bid > 1.1 assume it's cents scale
        if bid > 1.1 or ask > 1.1:
            bid /= 100.0
            ask /= 100.0

        yes_prob = (bid + ask) / 2.0
        if yes_prob <= 0 or yes_prob >= 1:
            yes_prob = bid if bid > 0 else ask
        if yes_prob <= 0:
            continue

        vol = float(m.get("volume_fp") or m.get("volume") or 0)
        points.append((strike, yes_prob, vol))

    if len(points) < 3:
        return None

    # El precio implícito = strike donde yes_prob cruza 0.5
    # Ordenar por strike ascendente
    points.sort(key=lambda x: x[0])
    strikes  = [p[0] for p in points]
    probs    = [p[1] for p in points]
    volumes  = [p[2] for p in points]

    # Probabilidad más cercana a 0.5 → implied price = strike correspondiente
    closest_idx = min(range(len(probs)), key=lambda i: abs(probs[i] - 0.5))
    implied_price = strikes[closest_idx]
    prob_at_50 = probs[closest_idx]

    # Si prob > 0.5 en el strike mediano → mercado espera precio ENCIMA del strike → bullish
    # Normalizar: score basado en cuánto se desvía la prob del 50%
    median_strike = strikes[len(strikes) // 2]
    score = (prob_at_50 - 0.5) * 2  # -1..+1
    total_vol = sum(volumes)
    weight = math.log10(max(total_vol, 1)) if total_vol > 0 else 1.0

    return (score, weight)


def get_kalshi_signal() -> dict:
    """
    Señal de Kalshi — único exchange de predicción regulado por CFTC en EEUU.

    Con KALSHI_API_KEY + kalshi_private.pem usa autenticación RSA.
    Cubre: mercados de rango BTC/ETH/WTI/Gold + mercados binarios macro si existen.
    """
    from config import KALSHI_API_KEY

    BASE = "https://api.elections.kalshi.com"
    PATH = "/trade-api/v2/markets"

    try:
        headers = _kalshi_auth_headers(KALSHI_API_KEY, "GET", PATH) if KALSHI_API_KEY else _HEADERS

        # ── Mercados generales (macro/elecciones/eventos) ──────────────────
        r = requests.get(
            BASE + PATH,
            params={"status": "open", "limit": 200},
            headers=headers,
            timeout=_TIMEOUT,
        )
        all_markets = r.json().get("markets", [])

        scores   = []
        relevant = []

        # ── 1. Keyword matching en mercados generales ──────────────────────
        for m in all_markets:
            title  = m.get("title", "") or m.get("subtitle", "") or ""
            bid_r  = m.get("yes_bid_dollars") or m.get("yes_bid") or 0
            ask_r  = m.get("yes_ask_dollars") or m.get("yes_ask") or 0
            vol    = float(m.get("volume_fp") or m.get("volume") or 0)

            if vol < 500:
                continue

            try:
                bid = float(bid_r)
                ask = float(ask_r)
            except (TypeError, ValueError):
                continue

            if bid > 1.1 or ask > 1.1:  # escala 0-100
                bid /= 100.0
                ask /= 100.0

            yes_prob = (bid + ask) / 2.0

            score = _score_question(title, yes_prob)
            if score is None:
                continue

            weight = math.log10(max(vol, 1))
            scores.append((score, weight))
            relevant.append({
                "title":    title,
                "yes_prob": round(yes_prob, 3),
                "volume":   round(vol, 0),
                "signal":   round(score, 3),
            })

        # ── 2. Mercados de rango financiero (KXBTC, KXETH, KXWTI) ──────────
        if KALSHI_API_KEY:
            for series, asset_name, is_bullish_asset in [
                ("KXBTC", "bitcoin", True),
                ("KXETH", "ethereum", True),
                ("KXWTI", "oil", None),  # petróleo: neutral para señal macro general
            ]:
                try:
                    series_markets = _kalshi_fetch_series(KALSHI_API_KEY, series)
                    result = _score_kalshi_range_markets(series_markets, asset_name)
                    if result is not None:
                        raw_score, weight = result
                        # BTC/ETH bullish = señal macro bullish; petróleo = neutral
                        if is_bullish_asset is True:
                            scores.append((raw_score, weight))
                            relevant.append({
                                "title":    f"{asset_name} range markets ({series})",
                                "yes_prob": round(0.5 + raw_score / 2, 3),
                                "volume":   "series",
                                "signal":   round(raw_score, 3),
                            })
                except Exception as e:
                    logger.debug(f"Kalshi series {series} error: {e}")

        if not scores:
            note = "" if KALSHI_API_KEY else " — añade KALSHI_API_KEY para mercados financieros"
            return {
                "signal": 0.0, "summary": f"no_relevant_markets{note}",
                "markets_used": 0, "source": "Kalshi",
            }

        total_weight   = sum(w for _, w in scores)
        weighted_score = sum(s * w for s, w in scores) / total_weight
        weighted_score = round(max(-1.0, min(1.0, weighted_score)), 4)
        summary = "bullish" if weighted_score > 0.15 else ("bearish" if weighted_score < -0.15 else "neutral")

        return {
            "signal":       weighted_score,
            "summary":      summary,
            "markets_used": len(relevant),
            "top_markets":  sorted(relevant, key=lambda x: abs(x["signal"]), reverse=True)[:5],
            "source":       "Kalshi",
        }

    except Exception as e:
        logger.debug(f"Kalshi signal error: {e}")
        return {"signal": 0.0, "summary": "error", "markets_used": 0, "source": "Kalshi"}


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador
# ─────────────────────────────────────────────────────────────────────────────

def run_prediction_markets() -> dict:
    """
    Agrega Polymarket + Kalshi en una señal de mercados de predicción unificada.
    Llamar cada 30-60 min (datos actualizan en tiempo real pero cambios lentos).
    """
    logger.info("Actualizando señales de mercados de predicción...")

    poly   = get_polymarket_signal()
    kalshi = get_kalshi_signal()

    poly_sig   = poly.get("signal", 0.0)
    kalshi_sig = kalshi.get("signal", 0.0)
    poly_ok    = poly.get("markets_used", 0) > 0
    kalshi_ok  = kalshi.get("markets_used", 0) > 0

    # Polymarket = mayor volumen; Kalshi = regulado (más institucional)
    if poly_ok and kalshi_ok:
        combined = poly_sig * 0.60 + kalshi_sig * 0.40
    elif poly_ok:
        combined = poly_sig
    elif kalshi_ok:
        combined = kalshi_sig
    else:
        combined = 0.0

    combined = round(max(-1.0, min(1.0, combined)), 4)
    summary  = "bullish" if combined > 0.15 else ("bearish" if combined < -0.15 else "neutral")

    logger.info(
        f"  Prediction markets OK — "
        f"Polymarket: {poly_sig:+.3f} ({poly.get('markets_used',0)} mkt) | "
        f"Kalshi: {kalshi_sig:+.3f} ({kalshi.get('markets_used',0)} mkt) | "
        f"Combined: {combined:+.3f}"
    )

    return {
        "signal":     combined,
        "summary":    summary,
        "polymarket": poly,
        "kalshi":     kalshi,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
