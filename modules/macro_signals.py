"""
Señales macro de alta calidad — fuentes usadas por traders profesionales.

Fuentes integradas (todas gratuitas o con clave gratuita):

  1. CNN Fear & Greed Index
     Compuesto de 7 indicadores: momentum precio, amplitud de mercado,
     put/call ratio, VIX, junk bond demand, safe haven demand, momentum S&P.
     Indicador contrario: miedo extremo → comprar; codicia extrema → vender.

  2. Crypto Fear & Greed (Alternative.me)
     Equivalente para cripto: volatilidad BTC, momentum, redes sociales,
     dominancia BTC, tendencias Google, volumen relativo.

  3. FRED API (Federal Reserve Economic Data)
     - T10Y2Y: spread 10Y-2Y. Negativo = curva invertida = alerta recesión.
     - VIXCLS: VIX. >30 = miedo; <15 = complacencia extrema.
     Datos más actualizados y fiables de macro disponibles gratuitamente.

  4. CFTC COT Report (Commitment of Traders)
     Posicionamiento semanal de fondos no-comerciales (hedge funds, CTA).
     Es el dato más honesto: los fondos no pueden mentir al regulador.
     Net LONG fondos → bullish; Net SHORT fondos → bearish.

  5. Put/Call Ratio (CBOE)
     Indicador contrario de corto plazo.
     Ratio >1.2 = pesimismo extremo → suele preceder rebotes.
     Ratio <0.7 = complacencia extrema → suele preceder correcciones.

  6. AAII Sentiment Survey
     Encuesta semanal inversores minoristas — indicador contrario clásico.
     Bears extremos >50% históricamente preceden rebotes.

Señal combinada:
  +1.0 → entorno macro muy favorable para comprar
  -1.0 → entorno macro muy adverso, reducir exposición
"""
import io
import logging
import time
from datetime import datetime, timezone

import requests

from config import FRED_API_KEY

logger     = logging.getLogger(__name__)
_TIMEOUT   = 12
_HEADERS   = {"User-Agent": "AutoTrader-IA/1.0 (research)"}


# ─────────────────────────────────────────────────────────────────────────────
# 1. CNN FEAR & GREED INDEX
# ─────────────────────────────────────────────────────────────────────────────

_FNG_CACHE: dict = {}
_FNG_TTL = 3600  # 1 hora


def get_cnn_fear_greed() -> dict:
    """
    Fear & Greed Index de CNN — compuesto de 7 indicadores de mercado.

    Señal contraria normalizada:
      0-25  Miedo extremo  → +1.0 (oportunidad de compra histórica)
      25-45 Miedo          → +0.3 a +0.5
      45-55 Neutral        → ~0
      55-75 Codicia        → -0.3 a -0.5
      75-100 Codicia extrema → -1.0 (precede correcciones)
    """
    now = time.time()
    if _FNG_CACHE.get("ts", 0) + _FNG_TTL > now:
        return _FNG_CACHE.get("data", {"signal": 0.0, "source": "CNN_FNG_cache"})

    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        fg_data = r.json().get("fear_and_greed", {})
        score   = float(fg_data.get("score", 50))
        rating  = fg_data.get("rating", "Neutral")

        # Indicador contrario: 50→0, 0→+1 (pánico=comprar), 100→-1 (codicia=vender)
        normalized = (50.0 - score) / 50.0
        normalized = round(max(-1.0, min(1.0, normalized)), 4)

        result = {
            "signal":    normalized,
            "raw_score": round(score, 1),
            "rating":    rating,
            "source":    "CNN Fear & Greed",
        }
        _FNG_CACHE["ts"]   = now
        _FNG_CACHE["data"] = result
        return result

    except Exception as e:
        logger.debug(f"CNN Fear&Greed error: {e}")
        return {"signal": 0.0, "raw_score": 50, "rating": "Unknown", "source": "CNN_FNG_error"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. CRYPTO FEAR & GREED (Alternative.me)
# ─────────────────────────────────────────────────────────────────────────────

_CRYPTO_FNG_CACHE: dict = {}
_CRYPTO_FNG_TTL = 3600


def get_crypto_fear_greed() -> dict:
    """
    Crypto Fear & Greed de Alternative.me — gratuito, actualización diaria.
    Incluye: volatilidad BTC, momentum/volumen, redes sociales,
    dominancia BTC, tendencias Google.
    """
    now = time.time()
    if _CRYPTO_FNG_CACHE.get("ts", 0) + _CRYPTO_FNG_TTL > now:
        return _CRYPTO_FNG_CACHE.get("data", {"signal": 0.0})

    try:
        r     = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        entry  = r.json().get("data", [{}])[0]
        score  = int(entry.get("value", 50))
        rating = entry.get("value_classification", "Neutral")

        normalized = round((50.0 - score) / 50.0, 4)
        normalized = max(-1.0, min(1.0, normalized))

        result = {
            "signal":    normalized,
            "raw_score": score,
            "rating":    rating,
            "source":    "Crypto F&G (Alternative.me)",
        }
        _CRYPTO_FNG_CACHE["ts"]   = now
        _CRYPTO_FNG_CACHE["data"] = result
        return result

    except Exception as e:
        logger.debug(f"Crypto F&G error: {e}")
        return {"signal": 0.0, "raw_score": 50, "rating": "Unknown", "source": "CryptoFNG_error"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. FRED API — Curva de tipos + VIX (Federal Reserve Economic Data)
# ─────────────────────────────────────────────────────────────────────────────

_FRED_CACHE: dict = {}
_FRED_TTL = 14_400  # 4 horas (FRED actualiza 1-2x/día)


def _fred_latest(series_id: str) -> float | None:
    """Obtiene el último valor no-nulo de una serie FRED."""
    if not FRED_API_KEY:
        return None
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id":  series_id,
                "api_key":    FRED_API_KEY,
                "file_type":  "json",
                "limit":      5,
                "sort_order": "desc",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        for ob in r.json().get("observations", []):
            val = ob.get("value", ".")
            if val != ".":
                return float(val)
    except Exception as e:
        logger.debug(f"FRED {series_id}: {e}")
    return None


def get_fred_macro_signal() -> dict:
    """
    Señal macro FRED usando curva de tipos 10Y-2Y y VIX.

    Curva de tipos (T10Y2Y):
      > +0.5  → normal/expansión       → +0.5
       0-0.5  → ligeramente positiva   → +0.2
      -0.5-0  → inversión leve          → -0.3
      -1.0-0.5→ inversión moderada      → -0.6  (alerta seria)
      < -1.0  → inversión severa        → -1.0  (señal recesión)

    VIX (VIXCLS) — contrario:
      > 40  → pánico extremo  → +0.8 (oportunidad contraria)
      30-40 → miedo           → +0.4
      20-30 → neutral         → 0.0
      15-20 → baja vol        → -0.2
      < 15  → complacencia    → -0.5
    """
    now = time.time()
    if _FRED_CACHE.get("ts", 0) + _FRED_TTL > now:
        return _FRED_CACHE.get("data", {"signal": 0.0, "source": "FRED_cache"})

    if not FRED_API_KEY:
        return {"signal": 0.0, "source": "FRED_no_key", "yield_curve": None, "vix": None}

    yield_spread = _fred_latest("T10Y2Y")
    time.sleep(0.3)
    vix = _fred_latest("VIXCLS")

    # Curva de tipos
    curve_score = 0.0
    if yield_spread is not None:
        if yield_spread > 0.5:
            curve_score = 0.5
        elif yield_spread > 0.0:
            curve_score = 0.2
        elif yield_spread > -0.5:
            curve_score = -0.3
        elif yield_spread > -1.0:
            curve_score = -0.6
        else:
            curve_score = -1.0

    # VIX (contrario)
    vix_score = 0.0
    if vix is not None:
        if vix > 40:
            vix_score = 0.8
        elif vix > 30:
            vix_score = 0.4
        elif vix > 20:
            vix_score = 0.0
        elif vix > 15:
            vix_score = -0.2
        else:
            vix_score = -0.5

    # Curva de tipos es más predictiva a largo plazo
    if yield_spread is not None and vix is not None:
        combined = curve_score * 0.60 + vix_score * 0.40
    elif yield_spread is not None:
        combined = curve_score
    elif vix is not None:
        combined = vix_score
    else:
        combined = 0.0

    combined = round(max(-1.0, min(1.0, combined)), 4)

    result = {
        "signal":      combined,
        "yield_curve": round(yield_spread, 4) if yield_spread is not None else None,
        "vix":         round(vix, 2) if vix is not None else None,
        "curve_score": round(curve_score, 4),
        "vix_score":   round(vix_score, 4),
        "summary":     "bullish" if combined > 0.2 else ("bearish" if combined < -0.2 else "neutral"),
        "source":      "FRED (Federal Reserve)",
    }
    _FRED_CACHE["ts"]   = now
    _FRED_CACHE["data"] = result
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4. CFTC COT REPORT — Posicionamiento institucional en futuros
# ─────────────────────────────────────────────────────────────────────────────

_COT_CACHE: dict = {}
_COT_TTL = 86_400  # 24 horas (informe semanal, publicado viernes)

# Contratos a rastrear: etiqueta → fragmento del nombre en el CSV del CFTC
_COT_MARKETS = {
    "S&P 500":   "E-MINI S&P 500",
    "NASDAQ":    "NASDAQ-100",
    "GOLD":      "GOLD - COMMODITY EXCHANGE",
    "CRUDE OIL": "CRUDE OIL, LIGHT SWEET",
    "10Y TBOND": "10-YEAR U.S. TREASURY",
    "BITCOIN":   "BITCOIN",
}

# Pesos por relevancia para la señal global
_COT_WEIGHTS = {
    "S&P 500":   0.35,
    "NASDAQ":    0.25,
    "10Y TBOND": 0.20,
    "GOLD":      0.10,
    "CRUDE OIL": 0.05,
    "BITCOIN":   0.05,
}


def get_cot_signal() -> dict:
    """
    CFTC Commitment of Traders — posicionamiento neto de fondos no-comerciales.

    Fondos no-comerciales (hedge funds, CTA): los mejores predictores del
    mercado porque arriesgan capital real y no pueden mentirle al regulador.

    Net LONG fondos → bullish esperado.
    Net SHORT fondos → bearish esperado.

    Nota: bonos largos (10Y) se invierten — huida a calidad = bearish acciones.
    Datos semanales (viernes). CSV descargable gratis del CFTC.
    """
    now = time.time()
    if _COT_CACHE.get("ts", 0) + _COT_TTL > now:
        return _COT_CACHE.get("data", {"signal": 0.0, "source": "COT_cache"})

    try:
        import csv
        import zipfile

        year = datetime.now().year
        for yr in [year, year - 1]:
            url = f"https://www.cftc.gov/files/dea/history/fut_fin_xls_{yr}.zip"
            r   = requests.get(url, headers=_HEADERS, timeout=30)
            if r.status_code == 200:
                break
        else:
            return {"signal": 0.0, "summary": "cot_fetch_failed", "source": "CFTC_COT"}

        zf       = zipfile.ZipFile(io.BytesIO(r.content))
        csv_name = next(n for n in zf.namelist() if n.lower().endswith((".txt", ".csv")))
        content  = zf.read(csv_name).decode("latin-1")
        reader   = csv.DictReader(io.StringIO(content))

        latest_by_market: dict[str, dict] = {}
        for row in reader:
            mkt      = row.get("Market_and_Exchange_Names", "")
            date_str = row.get("Report_Date_as_YYYY-MM-DD", "")
            for label, keyword in _COT_MARKETS.items():
                if keyword.lower() in mkt.lower():
                    existing = latest_by_market.get(label)
                    if not existing or date_str > existing.get("date", ""):
                        latest_by_market[label] = {
                            "market":         mkt,
                            "date":           date_str,
                            "noncomm_long":   int(row.get("NonComm_Positions_Long_All",  0) or 0),
                            "noncomm_short":  int(row.get("NonComm_Positions_Short_All", 0) or 0),
                        }

        if not latest_by_market:
            return {"signal": 0.0, "summary": "no_cot_data", "source": "CFTC_COT"}

        market_signals: dict[str, dict] = {}
        scores: list[tuple[float, float]] = []

        for label, data in latest_by_market.items():
            longs  = data["noncomm_long"]
            shorts = data["noncomm_short"]
            total  = longs + shorts
            if total == 0:
                continue

            net_ratio = (longs - shorts) / total  # -1 a +1

            # Bonos: net long en bonos = huida a calidad = bearish para acciones
            if label == "10Y TBOND":
                net_ratio = -net_ratio

            weight = _COT_WEIGHTS.get(label, 0.05)
            scores.append((net_ratio, weight))
            market_signals[label] = {
                "net_ratio": round(net_ratio, 4),
                "longs":     longs,
                "shorts":    shorts,
                "date":      data["date"],
            }

        if not scores:
            return {"signal": 0.0, "summary": "no_cot_scores", "source": "CFTC_COT"}

        total_w  = sum(w for _, w in scores)
        combined = sum(s * w for s, w in scores) / total_w if total_w > 0 else 0.0
        combined = round(max(-1.0, min(1.0, combined)), 4)

        summary = (
            "bullish_institutional" if combined > 0.15
            else ("bearish_institutional" if combined < -0.15 else "neutral_institutional")
        )

        result = {
            "signal":         combined,
            "summary":        summary,
            "market_signals": market_signals,
            "source":         "CFTC COT Report",
        }
        _COT_CACHE["ts"]   = now
        _COT_CACHE["data"] = result
        return result

    except Exception as e:
        logger.debug(f"COT signal error: {e}")
        return {"signal": 0.0, "summary": "cot_error", "source": "CFTC_COT"}


# ─────────────────────────────────────────────────────────────────────────────
# 5. PUT/CALL RATIO (CBOE)
# ─────────────────────────────────────────────────────────────────────────────

_PCR_CACHE: dict = {}
_PCR_TTL = 3600


def get_put_call_ratio() -> dict:
    """
    Put/Call Ratio del CBOE — indicador contrario de sentimiento de corto plazo.

    Ratio > 1.2 → pesimismo extremo → precede rebotes (BULLISH contrario)
    Ratio ~ 0.9 → equilibrio neutral
    Ratio < 0.7 → complacencia extrema → precede correcciones (BEARISH contrario)

    CBOE publica datos diarios gratuitos en CSV.
    """
    now = time.time()
    if _PCR_CACHE.get("ts", 0) + _PCR_TTL > now:
        return _PCR_CACHE.get("data", {"signal": 0.0})

    try:
        r = requests.get(
            "https://www.cboe.com/publish/scheduledtask/mktdata/datahouse/equitypc.csv",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        lines = r.text.strip().split("\n")

        last_ratio: float | None = None
        for line in reversed(lines):
            parts = line.strip().split(",")
            if len(parts) >= 3:
                try:
                    put_vol  = float(parts[1])
                    call_vol = float(parts[2])
                    if call_vol > 0:
                        last_ratio = put_vol / call_vol
                        break
                except (ValueError, IndexError):
                    continue

        if last_ratio is None:
            return {"signal": 0.0, "raw_ratio": None, "source": "CBOE_PCR_error"}

        if last_ratio > 1.5:
            signal = 0.9
        elif last_ratio > 1.2:
            signal = 0.5
        elif last_ratio > 1.0:
            signal = 0.2
        elif last_ratio > 0.8:
            signal = 0.0
        elif last_ratio > 0.7:
            signal = -0.2
        else:
            signal = -0.6

        result = {
            "signal":    round(signal, 4),
            "raw_ratio": round(last_ratio, 4),
            "summary":   "fear" if last_ratio > 1.2 else ("greed" if last_ratio < 0.7 else "neutral"),
            "source":    "CBOE Put/Call Ratio",
        }
        _PCR_CACHE["ts"]   = now
        _PCR_CACHE["data"] = result
        return result

    except Exception as e:
        logger.debug(f"Put/Call ratio error: {e}")
        return {"signal": 0.0, "raw_ratio": None, "source": "CBOE_PCR_error"}


# ─────────────────────────────────────────────────────────────────────────────
# 6. AAII SENTIMENT SURVEY — Encuesta inversores minoristas
# ─────────────────────────────────────────────────────────────────────────────

_AAII_CACHE: dict = {}
_AAII_TTL = 86_400  # 24 horas (encuesta semanal)


def get_aaii_sentiment() -> dict:
    """
    AAII Sentiment Survey — encuesta semanal de inversores minoristas.
    Indicador contrario clásico en Wall Street desde 1987.

    Bears extremos > 50% históricamente preceden rebotes de +15-20% en 6 meses.
    Bulls extremos > 55% históricamente preceden correcciones de -10-15%.

    Score contrario:
      bearish% - bullish% positivo → más bears → señal contraria BULLISH
      bearish% - bullish% negativo → más bulls → señal contraria BEARISH
    """
    now = time.time()
    if _AAII_CACHE.get("ts", 0) + _AAII_TTL > now:
        return _AAII_CACHE.get("data", {"signal": 0.0})

    try:
        r = requests.get(
            "https://www.aaii.com/files/surveys/sentiment.xls",
            headers={**_HEADERS, "Referer": "https://www.aaii.com/"},
            timeout=_TIMEOUT,
        )
        if r.status_code == 200 and len(r.content) > 1000:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
                ws = wb.active
                last_row = None
                for row in ws.iter_rows(min_row=5, values_only=True):
                    if row[0] and row[1] and isinstance(row[1], (int, float)):
                        last_row = row
                if last_row:
                    bullish = float(last_row[1]) if last_row[1] else 0.33
                    bearish = float(last_row[3]) if last_row[3] else 0.33
                    # Indicador contrario: más bears = señal bullish
                    spread = bearish - bullish
                    signal = round(max(-1.0, min(1.0, spread * 2.5)), 4)
                    result = {
                        "signal":   signal,
                        "bullish":  round(bullish, 4),
                        "bearish":  round(bearish, 4),
                        "spread":   round(spread, 4),
                        "summary":  (
                            "contrarian_bullish" if spread > 0.10
                            else ("contrarian_bearish" if spread < -0.10 else "neutral")
                        ),
                        "source":   "AAII Sentiment Survey",
                    }
                    _AAII_CACHE["ts"]   = now
                    _AAII_CACHE["data"] = result
                    return result
            except ImportError:
                logger.debug("openpyxl no instalado — AAII no disponible. Instala: pip install openpyxl")

        return {"signal": 0.0, "source": "AAII_unavailable"}

    except Exception as e:
        logger.debug(f"AAII sentiment error: {e}")
        return {"signal": 0.0, "source": "AAII_error"}


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador: señal macro combinada
# ─────────────────────────────────────────────────────────────────────────────

def run_macro_signals() -> dict:
    """
    Agrega todas las señales macro en una señal unificada.
    Llamar cada 30-60 min. COT solo cambia semanalmente (caché 24h).
    """
    logger.info("Actualizando señales macro...")

    fng        = get_cnn_fear_greed()
    crypto_fng = get_crypto_fear_greed()
    fred       = get_fred_macro_signal()
    pcr        = get_put_call_ratio()
    aaii       = get_aaii_sentiment()
    cot        = get_cot_signal()

    # Pesos por fiabilidad y relevancia para señal de trading
    components: list[tuple[float, float, str]] = [
        (fred.get("signal", 0.0),  0.30, "FRED"),        # macro estructural, más predictivo
        (cot.get("signal",  0.0),  0.25, "COT"),         # posicionamiento institucional real
        (fng.get("signal",  0.0),  0.20, "CNN F&G"),     # sentimiento de mercado compuesto
        (pcr.get("signal",  0.0),  0.15, "Put/Call"),    # opciones short-term contrario
        (aaii.get("signal", 0.0),  0.10, "AAII"),        # retail contrario (semanal)
    ]

    combined = sum(sig * w for sig, w, _ in components)
    combined = round(max(-1.0, min(1.0, combined)), 4)
    summary  = "bullish" if combined > 0.15 else ("bearish" if combined < -0.15 else "neutral")

    detail = " | ".join(f"{name}:{sig:+.3f}" for sig, _, name in components)
    logger.info(f"  Macro signals OK — {detail} → Combined: {combined:+.3f}")

    return {
        "signal":         combined,
        "summary":        summary,
        "cnn_fear_greed": fng,
        "crypto_fng":     crypto_fng,
        "fred":           fred,
        "put_call_ratio": pcr,
        "aaii":           aaii,
        "cot":            cot,
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }
