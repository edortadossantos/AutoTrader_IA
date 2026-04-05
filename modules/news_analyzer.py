"""
Obtiene noticias financieras (RSS + NewsAPI opcional) y calcula sentimiento.
"""
import logging
import requests
import feedparser
from datetime import datetime, timedelta
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config import NEWS_RSS_FEEDS, NEWS_API_KEY, WATCHLIST

logger = logging.getLogger(__name__)
_analyzer = SentimentIntensityAnalyzer()

# Mapeo ticker → palabras clave de búsqueda
TICKER_KEYWORDS = {
    "AAPL": ["Apple", "AAPL", "iPhone", "Tim Cook"],
    "MSFT": ["Microsoft", "MSFT", "Azure", "Satya Nadella"],
    "GOOGL": ["Google", "Alphabet", "GOOGL", "YouTube"],
    "NVDA": ["Nvidia", "NVDA", "GPU", "Jensen Huang"],
    "META": ["Meta", "Facebook", "Instagram", "Zuckerberg"],
    "AMZN": ["Amazon", "AMZN", "AWS", "Jeff Bezos"],
    "TSLA": ["Tesla", "TSLA", "Elon Musk", "EV"],
    "SPY": ["S&P 500", "SPY", "stock market", "market rally"],
    "QQQ": ["Nasdaq", "QQQ", "tech stocks"],
    "IWM": ["Russell 2000", "IWM", "small cap"],
    "JPM": ["JPMorgan", "JPM", "Jamie Dimon"],
    "BAC": ["Bank of America", "BAC"],
}


def fetch_rss_articles() -> list[dict]:
    articles = []
    for url in NEWS_RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "published": entry.get("published", ""),
                    "source": feed.feed.get("title", url),
                })
        except Exception as e:
            logger.debug(f"RSS error {url}: {e}")
    return articles


def fetch_newsapi_articles(query: str) -> list[dict]:
    if not NEWS_API_KEY:
        return []
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "from": (datetime.utcnow() - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S"),
            "apiKey": NEWS_API_KEY,
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        articles = []
        for a in data.get("articles", []):
            articles.append({
                "title": a.get("title", ""),
                "summary": a.get("description", ""),
                "published": a.get("publishedAt", ""),
                "source": a.get("source", {}).get("name", ""),
            })
        return articles
    except Exception as e:
        logger.debug(f"NewsAPI error: {e}")
        return []


def score_sentiment(text: str) -> float:
    """Retorna score VADER compound: -1 (muy negativo) a +1 (muy positivo)"""
    if not text:
        return 0.0
    return _analyzer.polarity_scores(text)["compound"]


def analyze_news_for_ticker(ticker: str, articles: list[dict]) -> dict:
    keywords = TICKER_KEYWORDS.get(ticker, [ticker])
    relevant = []
    for art in articles:
        text = f"{art['title']} {art['summary']}".lower()
        if any(kw.lower() in text for kw in keywords):
            sentiment = score_sentiment(f"{art['title']} {art['summary']}")
            relevant.append({**art, "sentiment": sentiment})

    if not relevant:
        return {"ticker": ticker, "news_score": 0.0, "articles_found": 0, "headlines": []}

    avg_sentiment = sum(a["sentiment"] for a in relevant) / len(relevant)
    headlines = [{"title": a["title"], "sentiment": round(a["sentiment"], 3)} for a in relevant[:5]]

    return {
        "ticker": ticker,
        "news_score": round(avg_sentiment, 4),
        "articles_found": len(relevant),
        "headlines": headlines,
    }


def get_market_sentiment(articles: list[dict]) -> float:
    """Sentimiento general del mercado basado en palabras macro."""
    macro_keywords = ["stock market", "S&P", "Nasdaq", "Fed", "interest rate",
                      "inflation", "recession", "bull", "bear", "rally", "selloff"]
    relevant = [a for a in articles
                if any(kw.lower() in f"{a['title']} {a['summary']}".lower() for kw in macro_keywords)]
    if not relevant:
        return 0.0
    return sum(score_sentiment(f"{a['title']} {a['summary']}") for a in relevant) / len(relevant)


def run_news_analysis() -> dict:
    """Ejecuta análisis completo de noticias para todos los tickers."""
    logger.info("Actualizando análisis de noticias...")
    articles = fetch_rss_articles()

    results = {}
    for ticker in WATCHLIST:
        # Complementar con NewsAPI si está disponible
        extra = fetch_newsapi_articles(ticker)
        all_articles = articles + extra
        results[ticker] = analyze_news_for_ticker(ticker, all_articles)

    market_sentiment = get_market_sentiment(articles)

    return {
        "ticker_news": results,
        "market_sentiment": round(market_sentiment, 4),
        "total_articles": len(articles),
        "updated_at": datetime.utcnow().isoformat(),
    }
