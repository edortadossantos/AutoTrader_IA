"""
Obtiene noticias financieras de múltiples fuentes y calcula sentimiento ponderado.

Fuentes integradas (todas gratuitas):
  - ~30 feeds RSS (Reuters, CNBC, MarketWatch, Benzinga, Barron's, SEC EDGAR, etc.)
  - Finnhub API  (noticias de mercado + por empresa, 60 req/min gratis)
  - Alpha Vantage NEWS_SENTIMENT (sentimiento por ticker, 25 req/día gratis)
  - Reddit PRAW  (r/wallstreetbets, r/investing, r/stocks — opcional)
  - NewsAPI      (opcional, ya existente)
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config import (
    NEWS_RSS_FEEDS, NEWS_API_KEY,
    FINNHUB_API_KEY, ALPHA_VANTAGE_KEY,
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
    WATCHLIST, CRYPTO, COMMODITIES,
)

logger = logging.getLogger(__name__)
_analyzer = SentimentIntensityAnalyzer()

# ── Credibilidad por fuente (multiplicador sobre el score VADER) ─────────────
SOURCE_WEIGHTS: dict[str, float] = {
    "Reuters":         1.5,
    "Bloomberg":       1.5,
    "The Wall Street Journal": 1.4,
    "WSJ":             1.4,
    "Barron's":        1.4,
    "Financial Times": 1.4,
    "CNBC":            1.3,
    "MarketWatch":     1.3,
    "Benzinga":        1.3,
    "Seeking Alpha":   1.2,
    "Finnhub":         1.2,
    "AP":              1.2,
    "Business Wire":   1.1,
    "PR Newswire":     1.1,
    "SEC EDGAR":       1.3,
    "Nasdaq":          1.2,
    "Forbes":          1.1,
    "Zero Hedge":      0.9,  # sensacionalista pero muy leído
    "Reddit":          0.8,  # útil para detectar retail momentum
}

# ── Palabras clave que indican noticias de alta urgencia (boost x1.4) ────────
BREAKING_KEYWORDS = [
    "breaking", "urgent", "halt", "halted", "suspended", "SEC investigation",
    "beats expectations", "misses expectations", "earnings beat", "earnings miss",
    "upgrade", "downgrade", "outperform", "underperform", "buy rating", "sell rating",
    "merger", "acquisition", "buyout", "takeover", "bankruptcy", "default",
    "FDA approval", "FDA rejection", "layoffs", "CEO resigns", "CEO fired",
    "stock split", "dividend cut", "dividend increase", "share buyback",
    "guidance raised", "guidance lowered", "revenue warning", "profit warning",
]

# ── Tickers → palabras clave para filtrado ───────────────────────────────────
TICKER_KEYWORDS: dict[str, list[str]] = {
    # ── US Tech ─────────────────────────────────────────────────
    "AAPL":  ["Apple", "AAPL", "iPhone", "iPad", "Mac", "Tim Cook", "App Store", "Vision Pro"],
    "MSFT":  ["Microsoft", "MSFT", "Azure", "Windows", "Office", "Satya Nadella", "Copilot", "GitHub"],
    "GOOGL": ["Google", "Alphabet", "GOOGL", "YouTube", "Search", "DeepMind", "Sundar Pichai", "Gemini"],
    "NVDA":  ["Nvidia", "NVDA", "GPU", "CUDA", "H100", "Jensen Huang", "AI chip", "Blackwell", "GeForce"],
    "META":  ["Meta", "Facebook", "Instagram", "WhatsApp", "Zuckerberg", "Threads", "Quest", "Llama"],
    "AMZN":  ["Amazon", "AMZN", "AWS", "Prime", "Bezos", "Jassy", "Alexa", "Kindle"],
    "TSLA":  ["Tesla", "TSLA", "Elon Musk", "EV", "electric vehicle", "Cybertruck", "Powerwall", "Autopilot"],
    "AMD":   ["AMD", "Advanced Micro Devices", "Ryzen", "EPYC", "Lisa Su", "Radeon"],
    "NFLX":  ["Netflix", "NFLX", "streaming", "Reed Hastings"],
    "ORCL":  ["Oracle", "ORCL", "Larry Ellison", "cloud database"],
    # ── US Financials ────────────────────────────────────────────
    "JPM":   ["JPMorgan", "JPM", "Jamie Dimon", "Chase"],
    "BAC":   ["Bank of America", "BAC", "BofA"],
    "GS":    ["Goldman Sachs", "GS", "David Solomon"],
    "BRK-B": ["Berkshire Hathaway", "Buffett", "Warren Buffett", "BRK"],
    # ── US Energy ────────────────────────────────────────────────
    "XOM":   ["ExxonMobil", "XOM", "Exxon", "oil major"],
    "CVX":   ["Chevron", "CVX", "oil company"],
    # ── US Health ────────────────────────────────────────────────
    "JNJ":   ["Johnson Johnson", "JNJ", "pharma", "medical device"],
    "UNH":   ["UnitedHealth", "UNH", "health insurance", "Optum"],
    # ── US Consumer ──────────────────────────────────────────────
    "WMT":   ["Walmart", "WMT", "retail", "Doug McMillon"],
    "HD":    ["Home Depot", "HD", "home improvement", "housing"],
    # ── ETFs US ──────────────────────────────────────────────────
    "SPY":   ["S&P 500", "SPY", "stock market", "market rally", "broad market", "equities"],
    "QQQ":   ["Nasdaq", "QQQ", "tech stocks", "Nasdaq 100"],
    "IWM":   ["Russell 2000", "IWM", "small cap"],
    "XLK":   ["tech sector", "XLK", "technology ETF"],
    "XLF":   ["financial sector", "XLF", "bank stocks", "financials ETF"],
    "XLE":   ["energy sector", "XLE", "oil stocks", "energy ETF"],
    "XLV":   ["health sector", "XLV", "healthcare ETF", "pharma stocks"],
    "XLI":   ["industrial sector", "XLI", "industrials ETF"],
    "GLD":   ["gold ETF", "GLD", "gold price", "gold rally"],
    "SLV":   ["silver ETF", "SLV", "silver price"],
    "USO":   ["oil ETF", "USO", "crude oil", "WTI"],
    # ── Crypto ───────────────────────────────────────────────────
    "BTC-USD": ["Bitcoin", "BTC", "crypto", "cryptocurrency", "digital currency",
                "Satoshi", "blockchain", "halving", "ETF Bitcoin", "spot Bitcoin ETF"],
    "ETH-USD": ["Ethereum", "ETH", "Ether", "DeFi", "smart contract", "staking",
                "Layer 2", "EIP", "Vitalik Buterin"],
    "SOL-USD": ["Solana", "SOL", "Solana blockchain", "SOL price", "Anatoly Yakovenko"],
    # ── Commodities ──────────────────────────────────────────────
    "GC=F":  ["gold", "gold price", "gold futures", "safe haven", "XAU", "precious metals",
              "Fed rate", "dollar weakness", "inflation hedge"],
    "CL=F":  ["crude oil", "WTI", "oil price", "OPEC", "petroleum", "barrel",
              "energy prices", "Saudi Arabia", "Russia oil"],
    "SI=F":  ["silver", "silver price", "silver futures", "XAG", "precious metals"],
    # ── Internacional ────────────────────────────────────────────
    "EFA":   ["international stocks", "EFA", "Europe stocks", "Japan stocks",
              "developed markets", "MSCI EAFE", "ECB", "European Central Bank"],
    "EEM":   ["emerging markets", "EEM", "China stocks", "India stocks",
              "Brazil stocks", "MSCI emerging", "EM rally"],
    # ── Macro / mercado general ──────────────────────────────────
    "_MACRO": [
        "Federal Reserve", "Fed", "FOMC", "interest rate", "inflation", "CPI", "PPI",
        "unemployment", "jobs report", "GDP", "recession", "bull market", "bear market",
        "stock market", "Wall Street", "S&P", "Nasdaq", "Dow Jones", "earnings season",
        "Treasury", "yield curve", "10-year", "rate hike", "rate cut", "quantitative",
        "dollar", "DXY", "tariff", "trade war", "geopolitical", "sanctions",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────

def _freshness_multiplier(published_str: str) -> float:
    """Noticias recientes pesan más. Retorna multiplicador 0.5–1.5."""
    try:
        from email.utils import parsedate_to_datetime
        try:
            pub = parsedate_to_datetime(published_str)
        except Exception:
            pub = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        if age_h < 1:
            return 1.5
        if age_h < 3:
            return 1.3
        if age_h < 6:
            return 1.1
        if age_h < 24:
            return 1.0
        return 0.7
    except Exception:
        return 1.0


def _breaking_boost(text: str) -> float:
    """1.4 si contiene keyword de alta urgencia, sino 1.0."""
    tl = text.lower()
    return 1.4 if any(kw.lower() in tl for kw in BREAKING_KEYWORDS) else 1.0


def _source_weight(source: str) -> float:
    for key, w in SOURCE_WEIGHTS.items():
        if key.lower() in source.lower():
            return w
    return 1.0


def score_sentiment(text: str, source: str = "", published: str = "") -> float:
    """Score VADER ponderado por credibilidad de fuente, frescura y urgencia."""
    if not text:
        return 0.0
    raw = _analyzer.polarity_scores(text)["compound"]
    weight = _source_weight(source) * _freshness_multiplier(published) * _breaking_boost(text)
    return max(-1.0, min(1.0, raw * weight))


def _deduplicate(articles: list[dict]) -> list[dict]:
    """Elimina artículos con títulos muy similares (primeros 60 chars)."""
    seen: set[str] = set()
    out = []
    for a in articles:
        key = a.get("title", "")[:60].lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(a)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Fuentes de datos
# ─────────────────────────────────────────────────────────────────────────────

def fetch_rss_articles() -> list[dict]:
    articles = []
    for url in NEWS_RSS_FEEDS:
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "AutoTrader/1.0"})
            for entry in feed.entries[:20]:
                articles.append({
                    "title":     entry.get("title", ""),
                    "summary":   entry.get("summary", entry.get("description", "")),
                    "published": entry.get("published", entry.get("updated", "")),
                    "source":    feed.feed.get("title", url.split("/")[2]),
                    "url":       entry.get("link", ""),
                })
        except Exception as e:
            logger.debug(f"RSS error {url}: {e}")
    return articles


def fetch_finnhub_market_news() -> list[dict]:
    """Noticias generales de mercado vía Finnhub (gratis, 60 req/min)."""
    if not FINNHUB_API_KEY:
        return []
    try:
        url = "https://finnhub.io/api/v1/news"
        r = requests.get(url, params={"category": "general", "token": FINNHUB_API_KEY}, timeout=8)
        articles = []
        for item in r.json()[:40]:
            articles.append({
                "title":     item.get("headline", ""),
                "summary":   item.get("summary", ""),
                "published": datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc).isoformat(),
                "source":    item.get("source", "Finnhub"),
                "url":       item.get("url", ""),
            })
        return articles
    except Exception as e:
        logger.debug(f"Finnhub market news error: {e}")
        return []


def fetch_finnhub_company_news(ticker: str) -> list[dict]:
    """Noticias específicas de una empresa vía Finnhub. Solo para stocks (no crypto/futuros)."""
    if not FINNHUB_API_KEY:
        return []
    # Finnhub no tiene company news para crypto ni futuros
    if ticker in CRYPTO or ticker in COMMODITIES:
        return []
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        url = "https://finnhub.io/api/v1/company-news"
        r = requests.get(url, params={
            "symbol": ticker, "from": week_ago, "to": today, "token": FINNHUB_API_KEY
        }, timeout=8)
        articles = []
        for item in r.json()[:15]:
            articles.append({
                "title":     item.get("headline", ""),
                "summary":   item.get("summary", ""),
                "published": datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc).isoformat(),
                "source":    item.get("source", "Finnhub"),
                "url":       item.get("url", ""),
                "_ticker":   ticker,
            })
        return articles
    except Exception as e:
        logger.debug(f"Finnhub company news {ticker}: {e}")
        return []


def fetch_finnhub_sentiment(ticker: str) -> dict:
    """Solo disponible para stocks US (no crypto ni futuros)."""
    if ticker in CRYPTO or ticker in COMMODITIES:
        return {}

    """
    Retorna buzz score y sentimiento de Finnhub para un ticker.
    Retorna dict con keys: buzz, sentiment, articles_in_week, score
    """
    if not FINNHUB_API_KEY:
        return {}
    try:
        url = "https://finnhub.io/api/v1/news-sentiment"
        r = requests.get(url, params={"symbol": ticker, "token": FINNHUB_API_KEY}, timeout=8)
        data = r.json()
        sentiment_data = data.get("sentiment", {})
        buzz_data = data.get("buzz", {})
        # Finnhub: bearishPercent/bullishPercent → convertir a -1..+1
        bull = sentiment_data.get("bullishPercent", 0.5)
        bear = sentiment_data.get("bearishPercent", 0.5)
        score = bull - bear  # rango -1 a +1
        return {
            "score":            round(score, 4),
            "bullish_pct":      round(bull, 3),
            "bearish_pct":      round(bear, 3),
            "buzz":             buzz_data.get("buzz", 0),
            "articles_in_week": buzz_data.get("articlesInLastWeek", 0),
        }
    except Exception as e:
        logger.debug(f"Finnhub sentiment {ticker}: {e}")
        return {}


# Cache simple para Alpha Vantage (máx 25 req/día → rotar tickers)
_av_cache: dict[str, tuple[float, float]] = {}   # ticker → (score, timestamp)

def fetch_alpha_vantage_sentiment(tickers: list[str]) -> dict[str, float]:
    """
    Sentimiento de noticias por ticker vía Alpha Vantage.
    Agrupa hasta 5 tickers por llamada. Cachea 4 horas (límite diario).
    """
    if not ALPHA_VANTAGE_KEY:
        return {}
    now = time.time()
    # Filtrar los que no estén en caché o hayan expirado (4h)
    to_fetch = [t for t in tickers if t not in _av_cache or now - _av_cache[t][1] > 14400]
    if not to_fetch:
        return {t: _av_cache[t][0] for t in tickers if t in _av_cache}

    results: dict[str, float] = {t: _av_cache[t][0] for t in tickers if t in _av_cache}
    # Alpha Vantage acepta hasta ~5 tickers por llamada
    chunk = to_fetch[:5]
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers":  ",".join(chunk),
            "sort":     "LATEST",
            "limit":    50,
            "apikey":   ALPHA_VANTAGE_KEY,
        }
        r = requests.get(url, params=params, timeout=12)
        data = r.json()
        # Acumular scores por ticker desde feed
        scores: dict[str, list[float]] = {t: [] for t in chunk}
        for article in data.get("feed", []):
            for ts in article.get("ticker_sentiment", []):
                t = ts.get("ticker", "")
                if t in scores:
                    try:
                        scores[t].append(float(ts.get("ticker_sentiment_score", 0)))
                    except ValueError:
                        pass
        for t in chunk:
            if scores[t]:
                s = sum(scores[t]) / len(scores[t])
                _av_cache[t] = (round(s, 4), now)
                results[t] = round(s, 4)
    except Exception as e:
        logger.debug(f"Alpha Vantage sentiment: {e}")
    return results


def fetch_reddit_sentiment(subreddits: str = "wallstreetbets+investing+stocks+options") -> list[dict]:
    """
    Sentimiento retail vía PRAW. Requiere REDDIT_CLIENT_ID y REDDIT_CLIENT_SECRET.
    Registra una app gratuita en https://www.reddit.com/prefs/apps (tipo: script).
    """
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        return []
    try:
        import praw  # noqa: import-outside-toplevel
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent="AutoTrader_IA/1.0",
        )
        articles = []
        sub = reddit.subreddit(subreddits)
        for post in sub.hot(limit=60):
            if post.score < 10:  # ignorar posts de muy bajo engagement
                continue
            articles.append({
                "title":     post.title,
                "summary":   post.selftext[:300] if post.selftext else "",
                "published": datetime.fromtimestamp(post.created_utc, tz=timezone.utc).isoformat(),
                "source":    f"Reddit/r/{post.subreddit.display_name}",
                "url":       f"https://reddit.com{post.permalink}",
                "_upvotes":  post.score,
            })
        return articles
    except ImportError:
        logger.debug("praw no instalado. Instala con: pip install praw")
        return []
    except Exception as e:
        logger.debug(f"Reddit error: {e}")
        return []


def fetch_finviz_news(ticker: str) -> list[dict]:
    """
    Scraping de noticias de Finviz para un ticker específico.
    Finviz agrega titulares de múltiples fuentes con latencia de segundos.
    """
    try:
        from bs4 import BeautifulSoup
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }, timeout=8)
        soup = BeautifulSoup(r.text, "lxml")

        news_table = soup.find(id="news-table")
        if not news_table:
            return []

        articles = []
        current_date = ""
        for row in news_table.find_all("tr")[:20]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            date_cell = cells[0].get_text(strip=True)
            title_cell = cells[1]

            # Finviz: si la celda tiene fecha y hora, o solo hora
            if len(date_cell) > 8:
                current_date = date_cell[:9].strip()
            time_str = date_cell[-7:].strip() if len(date_cell) >= 7 else date_cell

            a_tag = title_cell.find("a")
            if not a_tag:
                continue

            title = a_tag.get_text(strip=True)
            link = a_tag.get("href", "")
            source_tag = title_cell.find("span")
            source = source_tag.get_text(strip=True) if source_tag else "Finviz"

            articles.append({
                "title":     title,
                "summary":   "",
                "published": f"{current_date} {time_str}",
                "source":    source,
                "url":       link,
                "_ticker":   ticker,
            })

        return articles

    except Exception as e:
        logger.debug(f"Finviz news {ticker}: {e}")
        return []


def fetch_sec_edgar_filings() -> list[dict]:
    """
    Últimos filings 8-K y 10-Q del SEC EDGAR en tiempo real.
    Los 8-K son eventos corporativos (resultados, fusiones, cambios de directivos).
    """
    articles = []
    urls = [
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=20&output=atom",
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-Q&dateb=&owner=include&count=10&output=atom",
    ]
    for url in urls:
        try:
            import feedparser
            feed = feedparser.parse(url, request_headers={"User-Agent": "AutoTrader/1.0 edorta@email.com"})
            for entry in feed.entries[:15]:
                articles.append({
                    "title":     entry.get("title", ""),
                    "summary":   entry.get("summary", ""),
                    "published": entry.get("published", ""),
                    "source":    "SEC EDGAR",
                    "url":       entry.get("link", ""),
                })
        except Exception as e:
            logger.debug(f"SEC EDGAR {url}: {e}")
    return articles


def fetch_newsapi_articles(query: str) -> list[dict]:
    if not NEWS_API_KEY:
        return []
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q":        query,
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": 15,
            "from":     (datetime.utcnow() - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S"),
            "apiKey":   NEWS_API_KEY,
        }
        r = requests.get(url, params=params, timeout=10)
        articles = []
        for a in r.json().get("articles", []):
            articles.append({
                "title":     a.get("title", ""),
                "summary":   a.get("description", ""),
                "published": a.get("publishedAt", ""),
                "source":    a.get("source", {}).get("name", "NewsAPI"),
                "url":       a.get("url", ""),
            })
        return articles
    except Exception as e:
        logger.debug(f"NewsAPI error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Análisis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_news_for_ticker(
    ticker: str,
    articles: list[dict],
    finnhub_sentiment: dict | None = None,
    av_score: float | None = None,
) -> dict:
    keywords = TICKER_KEYWORDS.get(ticker, [ticker])
    relevant = []
    for art in articles:
        text = f"{art['title']} {art['summary']}".lower()
        if any(kw.lower() in text for kw in keywords):
            s = score_sentiment(
                f"{art['title']} {art['summary']}",
                source=art.get("source", ""),
                published=art.get("published", ""),
            )
            relevant.append({**art, "sentiment": s})

    text_score = 0.0
    if relevant:
        text_score = sum(a["sentiment"] for a in relevant) / len(relevant)

    headlines = [
        {"title": a["title"], "sentiment": round(a["sentiment"], 3), "source": a.get("source", "")}
        for a in sorted(relevant, key=lambda x: abs(x["sentiment"]), reverse=True)[:6]
    ]

    # Combinar fuentes: 50% texto RSS, 30% Finnhub, 20% Alpha Vantage
    fh_score = finnhub_sentiment.get("score", 0.0) if finnhub_sentiment else 0.0
    av = av_score or 0.0

    if finnhub_sentiment and av_score is not None:
        combined = text_score * 0.50 + fh_score * 0.30 + av * 0.20
    elif finnhub_sentiment:
        combined = text_score * 0.60 + fh_score * 0.40
    elif av_score is not None:
        combined = text_score * 0.70 + av * 0.30
    else:
        combined = text_score

    return {
        "ticker":           ticker,
        "news_score":       round(combined, 4),
        "text_score":       round(text_score, 4),
        "finnhub_score":    round(fh_score, 4) if finnhub_sentiment else None,
        "av_score":         round(av, 4) if av_score is not None else None,
        "finnhub_buzz":     finnhub_sentiment.get("buzz") if finnhub_sentiment else None,
        "articles_found":   len(relevant),
        "headlines":        headlines,
    }


def get_market_sentiment(articles: list[dict]) -> float:
    macro_keywords = TICKER_KEYWORDS["_MACRO"]
    relevant = [
        a for a in articles
        if any(kw.lower() in f"{a['title']} {a['summary']}".lower() for kw in macro_keywords)
    ]
    if not relevant:
        return 0.0
    scores = [
        score_sentiment(
            f"{a['title']} {a['summary']}",
            source=a.get("source", ""),
            published=a.get("published", ""),
        )
        for a in relevant
    ]
    return round(sum(scores) / len(scores), 4)


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador principal
# ─────────────────────────────────────────────────────────────────────────────

def run_news_analysis() -> dict:
    logger.info("Actualizando análisis de noticias (RSS + Finnhub + AV + Reddit + Finviz + SEC)...")

    # 1. Fuentes globales en paralelo
    from concurrent.futures import ThreadPoolExecutor, as_completed
    global_fetchers = {
        "rss":    fetch_rss_articles,
        "fh_mkt": fetch_finnhub_market_news,
        "reddit": fetch_reddit_sentiment,
        "sec":    fetch_sec_edgar_filings,
    }
    global_results: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fn): name for name, fn in global_fetchers.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                global_results[name] = fut.result()
            except Exception as e:
                logger.debug(f"Global fetch {name}: {e}")
                global_results[name] = []

    all_articles = _deduplicate(
        global_results.get("rss", [])
        + global_results.get("fh_mkt", [])
        + global_results.get("reddit", [])
        + global_results.get("sec", [])
    )
    logger.info(f"  Artículos globales (deduplicados): {len(all_articles)}")

    # 2. Alpha Vantage batch para todos los tickers relevantes (excluyendo ETFs genéricos)
    av_tickers = [t for t in WATCHLIST if t not in ("SPY", "QQQ", "IWM")]
    av_scores  = fetch_alpha_vantage_sentiment(av_tickers)

    # 3. Por ticker: Finnhub + Finviz + NewsAPI en paralelo
    results: dict[str, dict] = {}

    def _analyze_ticker(ticker: str) -> tuple[str, dict]:
        fh_sent      = fetch_finnhub_sentiment(ticker)
        company_news = fetch_finnhub_company_news(ticker)
        finviz_news  = fetch_finviz_news(ticker)
        extra_newsapi = fetch_newsapi_articles(ticker)
        ticker_articles = _deduplicate(all_articles + company_news + finviz_news + extra_newsapi)
        result = analyze_news_for_ticker(
            ticker,
            ticker_articles,
            finnhub_sentiment=fh_sent if fh_sent else None,
            av_score=av_scores.get(ticker),
        )
        return ticker, result

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures_t = {ex.submit(_analyze_ticker, t): t for t in WATCHLIST}
        for fut in as_completed(futures_t):
            try:
                ticker, result = fut.result()
                results[ticker] = result
            except Exception as e:
                ticker = futures_t[fut]
                logger.debug(f"Analyze ticker {ticker}: {e}")

    market_sentiment = get_market_sentiment(all_articles)

    return {
        "ticker_news":     results,
        "market_sentiment": market_sentiment,
        "total_articles":  len(all_articles),
        "sources_active":  _active_sources(all_articles),
        "updated_at":      datetime.utcnow().isoformat(),
    }


def _active_sources(articles: list[dict]) -> list[str]:
    return sorted({a.get("source", "").split("/")[0] for a in articles if a.get("source")})
