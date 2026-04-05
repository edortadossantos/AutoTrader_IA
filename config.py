import os
from dotenv import load_dotenv

load_dotenv()

# ── Capital y modo ──────────────────────────────────────────────
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", 10000))
TRADING_MODE = os.getenv("TRADING_MODE", "paper")  # solo "paper" por ahora
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── Moneda de visualización ─────────────────────────────────────
# "USD" = dólares nativos | "EUR" = convierte usando tipo de cambio en tiempo real
DISPLAY_CURRENCY = os.getenv("DISPLAY_CURRENCY", "EUR")

# ── Universo de activos a monitorear ────────────────────────────
WATCHLIST = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA",
    # ETFs
    "SPY", "QQQ", "IWM",
    # Financials
    "JPM", "BAC",
]

# ── Gestión de riesgo básica ────────────────────────────────────
MAX_POSITION_PCT = 0.10       # máx 10% del capital por posición
STOP_LOSS_PCT = 0.05          # stop loss 5%
TAKE_PROFIT_PCT = 0.12        # take profit 12%
MAX_OPEN_POSITIONS = 5        # máx posiciones abiertas simultáneas
MIN_SIGNAL_SCORE = 0.60       # score mínimo para operar (0-1)

# ── Circuit breakers (protección del capital) ───────────────────
# Nivel 1 — AVISO: alerta en dashboard y log, pero sigue operando
DRAWDOWN_WARN_PCT    = 0.10   # aviso si el capital cae un 10%

# Nivel 2 — REDUCCION: cierra posiciones abiertas, no abre nuevas
DRAWDOWN_REDUCE_PCT  = 0.20   # reduce exposición si cae un 20%

# Nivel 3 — HALT TOTAL: para TODO el trading automáticamente
DRAWDOWN_HALT_PCT    = 0.50   # bloqueo total si el capital cae un 50%

# Pérdida máxima en un solo día (% sobre equity de apertura del día)
DAILY_LOSS_LIMIT_PCT = 0.05   # para el bot si pierde más del 5% en un día

# Máximo de operaciones perdedoras consecutivas antes de pausar
MAX_CONSECUTIVE_LOSSES = 4

# ── Parámetros técnicos ─────────────────────────────────────────
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_STD = 2
SMA_SHORT = 20
SMA_LONG = 50

# ── Scheduler ──────────────────────────────────────────────────
# NYSE: abre 9:30 ET = 13:30 UTC (verano) / 14:30 UTC (invierno)
# Usamos UTC; el bot detecta horario real con holidays incluidos
SCAN_INTERVAL_MINUTES = 15   # cada cuántos minutos escanea el mercado
NEWS_INTERVAL_MINUTES = 30   # cada cuántos minutos actualiza noticias

# ── Rutas ──────────────────────────────────────────────────────
DB_PATH = "data/portfolio.db"
LOG_PATH = "logs/autotrader.log"

# ── Fuentes RSS de noticias financieras (gratuitas) ─────────────
NEWS_RSS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.investing.com/rss/news_25.rss",
    "https://finance.yahoo.com/rss/topstories",
]
