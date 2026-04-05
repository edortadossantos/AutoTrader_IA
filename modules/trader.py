"""
Motor principal de trading: orquesta análisis → señal → orden.
"""
import logging
from datetime import datetime

from config import WATCHLIST
from modules.market_analyzer import analyze_ticker, get_current_prices
from modules.news_analyzer import run_news_analysis
from modules.risk_manager import (
    can_open_position, calc_position_size, calc_stops, check_exits, risk_check_portfolio
)
from modules.portfolio import open_position, close_position, get_position, save_daily_snapshot
from strategies.combined_strategy import CombinedStrategy

logger = logging.getLogger(__name__)
strategy = CombinedStrategy()

_news_cache = {"data": None, "updated_at": None}


def get_news_cache() -> dict:
    """Devuelve el último análisis de noticias (se actualiza externamente)."""
    return _news_cache["data"] or {"ticker_news": {}, "market_sentiment": 0.0}


def update_news_cache():
    global _news_cache
    result = run_news_analysis()
    _news_cache["data"] = result
    _news_cache["updated_at"] = datetime.utcnow()
    logger.info(f"Noticias actualizadas: {result['total_articles']} artículos | sentimiento mercado: {result['market_sentiment']}")
    return result


def scan_and_trade() -> list[dict]:
    """
    Ciclo principal:
    1. Obtener precios actuales
    2. Comprobar exits (stop/take-profit)
    3. Escanear señales de entrada
    4. Ejecutar órdenes paper
    Retorna lista de acciones tomadas.
    """
    actions = []
    current_prices = get_current_prices(WATCHLIST)
    if not current_prices:
        logger.warning("No se pudieron obtener precios. ¿Mercado cerrado?")
        return actions

    news_data = get_news_cache()
    market_sentiment = news_data.get("market_sentiment", 0.0)

    # ── 1. Chequear exits ───────────────────────────────────────
    exits = check_exits(current_prices)
    for exit_order in exits:
        pnl = close_position(exit_order["ticker"], exit_order["price"], exit_order["reason"])
        msg = f"CERRADA {exit_order['ticker']} @ ${exit_order['price']:.2f} [{exit_order['reason']}] PnL=${pnl:+.2f}"
        logger.info(msg)
        actions.append({"type": "SELL", "ticker": exit_order["ticker"],
                        "price": exit_order["price"], "pnl": pnl,
                        "reason": exit_order["reason"]})

    # ── 2. Escanear entradas ─────────────────────────────────────
    for ticker in WATCHLIST:
        try:
            # Análisis técnico
            tech = analyze_ticker(ticker)
            if tech is None:
                continue

            # Noticias
            ticker_news = news_data.get("ticker_news", {}).get(ticker, {"news_score": 0.0})

            # Generar señal
            signal = strategy.generate_signal(tech, ticker_news, market_sentiment)

            price = current_prices.get(ticker, tech["price"])

            if signal["action"] == "BUY":
                ok, reason = can_open_position(ticker)
                if not ok:
                    logger.debug(f"[{ticker}] BUY bloqueado: {reason}")
                    continue

                qty = calc_position_size(price, current_prices)
                if qty <= 0:
                    logger.debug(f"[{ticker}] qty=0, sin capital suficiente")
                    continue

                stop, tp = calc_stops(price, tech["atr"])
                open_position(ticker, qty, price, stop, tp)
                msg = (f"ABIERTA {ticker} {qty:.4f}x @ ${price:.2f} "
                       f"[SL=${stop:.2f} TP=${tp:.2f}] conf={signal['confidence']:.2f}")
                logger.info(msg)
                actions.append({"type": "BUY", "ticker": ticker, "qty": qty,
                                "price": price, "confidence": signal["confidence"],
                                "reason": signal["reason"]})

            elif signal["action"] == "SELL":
                pos = get_position(ticker)
                if pos:
                    pnl = close_position(ticker, price, "signal_sell")
                    msg = f"VENDIDA {ticker} @ ${price:.2f} PnL=${pnl:+.2f}"
                    logger.info(msg)
                    actions.append({"type": "SELL", "ticker": ticker, "price": price,
                                    "pnl": pnl, "reason": "signal_sell"})

        except Exception as e:
            logger.error(f"[{ticker}] error en ciclo de trading: {e}", exc_info=True)

    # ── 3. Snapshot diario ───────────────────────────────────────
    risk = risk_check_portfolio(current_prices)
    logger.info(
        f"Equity=${risk['equity']:.2f} | Cash=${risk['cash']:.2f} | "
        f"Posiciones={risk['open_positions']} | Exposición={risk['exposure_pct']:.1%}"
    )

    return actions
