import os
from dotenv import load_dotenv

load_dotenv()

# ── Capital y modo ──────────────────────────────────────────────
INITIAL_CAPITAL       = float(os.getenv("INITIAL_CAPITAL", 10000))
TRADING_MODE          = os.getenv("TRADING_MODE", "paper")
NEWS_API_KEY          = os.getenv("NEWS_API_KEY", "")
FINNHUB_API_KEY       = os.getenv("FINNHUB_API_KEY", "")
ALPHA_VANTAGE_KEY     = os.getenv("ALPHA_VANTAGE_KEY", "")
REDDIT_CLIENT_ID      = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET  = os.getenv("REDDIT_CLIENT_SECRET", "")

# ── FRED API (Federal Reserve Economic Data) ────────────────────
# Clave gratuita en: https://fred.stlouisfed.org/docs/api/api_key.html
# Usa: curva de tipos (T10Y2Y), VIX (VIXCLS) para señales macro.
FRED_API_KEY          = os.getenv("FRED_API_KEY", "")

# ── Kalshi API (mercado de predicción regulado CFTC) ────────────
# Clave opcional para datos avanzados: https://kalshi.com/api-docs
# Sin clave: acceso a datos públicos de mercado (solo lectura).
KALSHI_API_KEY        = os.getenv("KALSHI_API_KEY", "")

# ── Telegram (alertas en tiempo real) ──────────────────────────
# Setup: @BotFather → /newbot → copia TOKEN
#        api.telegram.org/bot<TOKEN>/getUpdates → copia chat_id
TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Opciones (flujo inusual) ────────────────────────────────────
OPTIONS_FLOW_ENABLED  = os.getenv("OPTIONS_FLOW_ENABLED", "true").lower() == "true"
OPTIONS_FLOW_MIN_PREMIUM = 50_000   # valor mínimo de la operación (USD) para considerarlo inusual

# ── Moneda de visualización ─────────────────────────────────────
DISPLAY_CURRENCY = os.getenv("DISPLAY_CURRENCY", "EUR")

# ════════════════════════════════════════════════════════════════
# UNIVERSO DE ACTIVOS — organizado por clase
# Un trader real diversifica en activos NO correlacionados:
#   • US Large Cap: alta liquidez, datos perfectos, horas NYSE
#   • US Sector ETFs: exposición sectorial sin riesgo empresa
#   • Crypto: 24/7, alta volatilidad = más oportunidades
#   • Commodities: cobertura contra inflación/dólar débil
#   • Internacional: descorrelación geográfica
# ════════════════════════════════════════════════════════════════

# ── US Large Cap — las más líquidas del mundo ───────────────────
US_TECH = ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA", "AMD", "NFLX", "ORCL"]
US_FINANCIALS = ["JPM", "BAC", "GS", "BRK-B"]
US_ENERGY = ["XOM", "CVX"]
US_HEALTH = ["JNJ", "UNH"]
US_CONSUMER = ["WMT", "HD"]

# ── US ETFs — diversificación sectorial + índices ───────────────
US_ETFS = [
    "SPY",   # S&P 500 — el índice más seguido del mundo
    "QQQ",   # Nasdaq 100 — tech pura
    "IWM",   # Russell 2000 — small caps (más beta)
    "XLK",   # Tech sector ETF
    "XLF",   # Financial sector ETF
    "XLE",   # Energy sector ETF
    "XLV",   # Health sector ETF
    "XLI",   # Industrial sector ETF
    "XLU",   # Utilities — defensivo en bear market
    "XLP",   # Consumer Staples — defensivo en bear market
    "GLD",   # Oro físico (ETF) — refugio en crisis
    "SLV",   # Plata (ETF)
    "USO",   # Petróleo WTI (ETF)
    "TLT",   # Bonos largo plazo — sube cuando hay huida a calidad
    # ETFs inversos — para operar el lado corto del mercado
    "SH",    # 1x inverso SPY — sube cuando el S&P 500 baja
    "PSQ",   # 1x inverso QQQ — sube cuando el Nasdaq baja
    "SDS",   # 2x inverso SPY — amplifica caídas del S&P 500
    "SQQQ",  # 3x inverso QQQ — máxima palanca bajista Nasdaq
]

# ── Crypto — operan 24/7, máxima volatilidad ────────────────────
# BTC/ETH lideran el mercado; SOL/AVAX/LINK tienen más momentum
# XRP y BNB: alta liquidez y ecosistemas propios
CRYPTO = [
    "BTC-USD",   # Bitcoin — líder de mercado, referencia macro
    "ETH-USD",   # Ethereum — DeFi + smart contracts
    "SOL-USD",   # Solana — alta velocidad, momentum fuerte
    "BNB-USD",   # Binance Coin — ecosistema BSC, muy líquido
    "XRP-USD",   # XRP — pagos internacionales, alta liquidez
    "AVAX-USD",  # Avalanche — DeFi alternativo, alta volatilidad
    "LINK-USD",  # Chainlink — oráculos, beta alto con crypto total
]

# ── Commodities futuros — cobertura macro ───────────────────────
COMMODITIES = [
    "GC=F",   # Oro futuros — sube cuando el dólar cae o hay miedo
    "CL=F",   # Petróleo WTI — correlaciona con inflación y geopolítica
    "SI=F",   # Plata futuros
]

# ── ETFs internacionales — descorrelación geográfica ────────────
INTERNATIONAL = [
    "EFA",   # Mercados desarrollados (Europa, Japón, Australia)
    "EEM",   # Mercados emergentes (China, India, Brasil)
]

# ── Watchlist unificada (lo que escanea el bot) ─────────────────
WATCHLIST = US_TECH + US_FINANCIALS + US_ENERGY + US_HEALTH + US_CONSUMER + US_ETFS + CRYPTO + COMMODITIES + INTERNATIONAL

# ── PARÁMETROS DE RIESGO POR CLASE DE ACTIVO ────────────────────
# Cada clase tiene volatilidad distinta → stops y sizing distintos
# ── Operar en corto habilitado ───────────────────────────────────
SHORT_ENABLED = True   # Permite abrir posiciones SHORT en stocks/ETFs

# ── ETFs inversos (se tratan como LONG pero correlacionan inversamente) ───────
INVERSE_ETFS = {"SH", "PSQ", "SDS", "SQQQ"}

ASSET_CLASS_PARAMS = {
    # clase       max_pos  stop   tp    min_score
    # Umbrales reducidos para trading activo (day/swing trading):
    #   - Stock: 0.55→0.42 | ETF: 0.50→0.38 | más operaciones de calidad
    #   - Crypto mantiene 0.22 (muy volátil, oportunidades frecuentes)
    #   - Commodity 0.30 (oro/petróleo con noticias macro = catalizadores claros)
    "crypto":     dict(max_pos=0.05, stop=0.08, tp=0.20, min_score=0.22),
    "commodity":  dict(max_pos=0.07, stop=0.04, tp=0.10, min_score=0.30),
    "etf":        dict(max_pos=0.12, stop=0.04, tp=0.10, min_score=0.38),
    "stock":      dict(max_pos=0.10, stop=0.05, tp=0.12, min_score=0.42),
    "intl":       dict(max_pos=0.08, stop=0.05, tp=0.12, min_score=0.40),
}

def get_asset_class(ticker: str) -> str:
    if ticker in CRYPTO:
        return "crypto"
    if ticker in COMMODITIES:
        return "commodity"
    if ticker in US_ETFS or ticker in INTERNATIONAL:
        return "etf"
    return "stock"

def get_asset_params(ticker: str) -> dict:
    return ASSET_CLASS_PARAMS[get_asset_class(ticker)]

# ── Gestión de riesgo global ────────────────────────────────────
MAX_POSITION_PCT     = 0.10   # default — sobrescrito por asset class
STOP_LOSS_PCT        = 0.05
TAKE_PROFIT_PCT      = 0.12
MAX_OPEN_POSITIONS   = 10     # más activos = más posiciones simultáneas (ampliado por más crypto)
MIN_SIGNAL_SCORE     = 0.42

# Límite de exposición por clase (% del capital total)
MAX_EXPOSURE_CRYPTO     = 0.25   # máx 25% en crypto (ampliado — más pares disponibles)
MAX_EXPOSURE_COMMODITY  = 0.15   # máx 15% en commodities
MAX_EXPOSURE_INTL       = 0.15   # máx 15% en internacional
MAX_EXPOSURE_SINGLE_SECTOR = 0.30  # máx 30% en cualquier sector US

# ── Trailing Stop-Loss ───────────────────────────────────────────
# Activa cuando el beneficio supera TRAILING_STOP_ACTIVATION,
# luego sigue el precio hacia arriba parándose X% bajo el máximo.
TRAILING_STOP_ACTIVATION = 0.03   # activar tras +3% de beneficio
TRAILING_STOP_PCT = {
    "crypto":    0.10,  # amplio: absorbe volatilidad cripto
    "commodity": 0.05,
    "etf":       0.05,
    "stock":     0.07,
    "intl":      0.06,
}

# ── Correlación sectorial ────────────────────────────────────────
# Máximo de posiciones abiertas simultáneamente en el mismo sector.
# Evita concentración: no tener AAPL + MSFT + NVDA + AMD al mismo tiempo.
MAX_POSITIONS_PER_SECTOR = 2

SECTOR_MAP = {
    # US Tech
    "AAPL": "us_tech",  "MSFT": "us_tech",  "GOOGL": "us_tech", "NVDA": "us_tech",
    "META": "us_tech",  "AMZN": "us_tech",  "TSLA": "us_tech",  "AMD":  "us_tech",
    "NFLX": "us_tech",  "ORCL": "us_tech",
    # US Financials
    "JPM": "us_fin",  "BAC": "us_fin",  "GS": "us_fin",  "BRK-B": "us_fin",
    # US Energy
    "XOM": "us_energy",  "CVX": "us_energy",
    # US Health
    "JNJ": "us_health",  "UNH": "us_health",
    # US Consumer
    "WMT": "us_consumer",  "HD": "us_consumer",
    # ETFs — agrupados para no duplicar exposición sectorial
    "SPY":  "etf_broad",  "QQQ": "etf_tech",   "IWM": "etf_small",
    "XLK":  "etf_tech",   "XLF": "etf_fin",    "XLE": "etf_energy",
    "XLV":  "etf_health", "XLI": "etf_ind",    "XLU": "etf_util",
    "XLP":  "etf_staples","GLD": "etf_gold",   "SLV": "etf_silver",
    "USO":  "etf_oil",    "TLT": "etf_bonds",
    # ETFs inversos — sector propio para no bloquear otros ETFs
    "SH":   "etf_inv_broad", "PSQ":  "etf_inv_tech",
    "SDS":  "etf_inv_broad", "SQQQ": "etf_inv_tech",
    # Crypto (máx 2 simultáneamente por sector)
    "BTC-USD":  "crypto_btc",   # BTC en su propio sector (referencia)
    "ETH-USD":  "crypto_eth",   # ETH en su propio sector
    "SOL-USD":  "crypto_alt",
    "BNB-USD":  "crypto_alt",
    "XRP-USD":  "crypto_alt",
    "AVAX-USD": "crypto_alt",
    "LINK-USD": "crypto_alt",
    # Futuros
    "GC=F": "fut_gold",  "CL=F": "fut_oil",  "SI=F": "fut_silver",
    # Internacional
    "EFA": "intl_dev",  "EEM": "intl_em",
}

# ── Cooldown tras stop-loss ──────────────────────────────────────
# Horas que un ticker queda bloqueado para re-entrar tras ser parado.
# Evita volver a entrar en un activo que acaba de caer.
COOLDOWN_HOURS = {
    "crypto":    2,
    "commodity": 3,
    "etf":       4,
    "stock":     6,
    "intl":      4,
}

# ── Circuit breakers ────────────────────────────────────────────
DRAWDOWN_WARN_PCT        = 0.10
DRAWDOWN_REDUCE_PCT      = 0.20
DRAWDOWN_HALT_PCT        = 0.50
DAILY_LOSS_LIMIT_PCT     = 0.05
MAX_CONSECUTIVE_LOSSES   = 4

# ── Parámetros técnicos ─────────────────────────────────────────
RSI_OVERSOLD   = 38   # más sensible para detectar antes las oportunidades
RSI_OVERBOUGHT = 62   # simétrico — detecta sobrecompra antes para cortos
RSI_PERIOD     = 14
MACD_FAST      = 12
MACD_SLOW      = 26
MACD_SIGNAL    = 9
BB_PERIOD      = 20
BB_STD         = 2
SMA_SHORT      = 20
SMA_LONG       = 50

# ── Scheduler ──────────────────────────────────────────────────
SCAN_INTERVAL_MINUTES      = 12   # escaneo general (era 15)
CRYPTO_SCAN_INTERVAL_MIN   = 8    # crypto más frecuente 24/7 (era 10)
NEWS_INTERVAL_MINUTES      = 4    # noticias más frecuentes (era 5)
PRO_SIGNALS_INTERVAL_MIN   = 30   # señales pro (límite API)

# ── Screener dinámico (S&P 500 + S&P 400 MidCap) ───────────────────────────
SCREENER_ENABLED        = True
SCREENER_TOP_N          = 15      # candidatos máximos por ciclo
SCREENER_MIN_PRICE      = 5.0     # evitar penny stocks
SCREENER_AVG_VOLUME_MIN = 150_000 # volumen medio mínimo (últimos 20 días)
SCREENER_VOL_SPIKE_MIN  = 1.5     # ratio vol_hoy/vol_media mínimo para ser candidato
SCREENER_CACHE_MINUTES  = 30      # caché: no re-escanear antes de este tiempo
SCREENER_INCLUDE_MIDCAP = True    # incluir S&P 400 MidCap además del S&P 500

# ── Rutas ──────────────────────────────────────────────────────
DB_PATH  = "data/portfolio.db"
LOG_PATH = "logs/autotrader.log"

# ── Fuentes RSS de noticias financieras ─────────────────────────
NEWS_RSS_FEEDS = [
    # ── Yahoo Finance ───────────────────────────────────────────
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^IXIC&region=US&lang=en-US",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=XLF&region=US&lang=en-US",
    "https://finance.yahoo.com/rss/topstories",
    # ── CNBC ────────────────────────────────────────────────────
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    # ── MarketWatch ─────────────────────────────────────────────
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://feeds.marketwatch.com/marketwatch/marketpulse/",
    # ── Reuters ─────────────────────────────────────────────────
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/technologyNews",
    # ── Investing.com ───────────────────────────────────────────
    "https://www.investing.com/rss/news_25.rss",
    "https://www.investing.com/rss/news_301.rss",
    "https://www.investing.com/rss/news_95.rss",
    # ── Benzinga ────────────────────────────────────────────────
    "https://www.benzinga.com/feed",
    # ── Seeking Alpha ───────────────────────────────────────────
    "https://seekingalpha.com/feed.xml",
    # ── AP ──────────────────────────────────────────────────────
    "https://feeds.apnews.com/apnews/business",
    # ── Barron's ────────────────────────────────────────────────
    "https://www.barrons.com/xml/rss/3_7510.xml",
    # ── Forbes ──────────────────────────────────────────────────
    "https://www.forbes.com/business/feed/",
    # ── The Motley Fool ─────────────────────────────────────────
    "https://www.fool.com/a/feeds/foolwatch.aspx",
    # ── Zero Hedge ──────────────────────────────────────────────
    "https://feeds.feedburner.com/zerohedge/feed",
    # ── Business Wire ───────────────────────────────────────────
    "https://feed.businesswire.com/rss/home/?rss=G22",
    # ── PR Newswire ─────────────────────────────────────────────
    "https://www.prnewswire.com/rss/news-releases-list.rss",
    # ── SEC EDGAR 8-K ────────────────────────────────────────────
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=20&output=atom",
    # ── FXStreet (macro, Fed, divisas) ───────────────────────────
    "https://www.fxstreet.com/rss",
    # ── Nasdaq News ─────────────────────────────────────────────
    "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
    # ── CoinDesk (crypto) ────────────────────────────────────────
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    # ── CoinTelegraph (crypto) ───────────────────────────────────
    "https://cointelegraph.com/rss",
    # ── OilPrice.com (energía y commodities) ─────────────────────
    "https://oilprice.com/rss/main",
    # ── Kitco News (oro, plata, metales) ─────────────────────────
    "https://www.kitco.com/rss/feed/rss_news.php",
    # ── The Block (crypto institucional) ─────────────────────────
    "https://www.theblock.co/rss.xml",
    # ── Decrypt (crypto) ─────────────────────────────────────────
    "https://decrypt.co/feed",
    # ── Unusual Whales (opciones + política) ─────────────────────
    "https://unusualwhales.com/rss",
    # ── Calculated Risk (macro/economía US) ──────────────────────
    "https://feeds.feedburner.com/CalculatedRisk",
    # ── Wolf Street (economía crítica) ───────────────────────────
    "https://wolfstreet.com/feed/",
    # ── ETF.com ──────────────────────────────────────────────────
    "https://www.etf.com/sections/features-and-news?rss",
    # ── Investors.com IBD ────────────────────────────────────────
    "https://www.investors.com/feed/",
    # ── Federal Reserve (comunicados oficiales) ───────────────────
    "https://www.federalreserve.gov/feeds/press_all.xml",
    # ── US Treasury (política arancelaria y fiscal) ───────────────
    "https://home.treasury.gov/system/files/276/treasury-press-releases.xml",
    # ── Politico Economy (tariffs, política comercial) ────────────
    "https://rss.politico.com/economy.xml",
    # ── The Hill (política US, decisiones regulatorias) ──────────
    "https://thehill.com/rss/syndicator/19109",
    # ── IMF News (macro global) ───────────────────────────────────
    "https://www.imf.org/en/News/rss?category=News&subcategory=Press+Release",
    # ── FRED Blog (Federal Reserve St. Louis — datos macro) ───────
    "https://fredblog.stlouisfed.com/feed/",
]
