"""
Motor principal de trading: orquesta análisis → señal → orden.
Respeta horario NYSE y circuit breakers.
"""
import logging
from datetime import datetime

from config import WATCHLIST
from modules.market_analyzer import analyze_ticker, get_current_prices
from modules.news_analyzer import run_news_analysis
from modules.risk_manager import (
    can_open_position, calc_position_size, calc_stops, check_exits, risk_check_portfolio
)
from modules.portfolio import (
    open_position, close_position, get_position, get_positions,
    save_daily_snapshot, get_equity
)
from modules.market_hours import is_market_open, market_status
from modules import circuit_breaker
from strategies.combined_strategy import CombinedStrategy

logger = logging.getLogger(__name__)
strategy = CombinedStrategy()

_news_cache = {"data": None, "updated_at": None}


def get_news_cache() -> dict:
    return _news_cache["data"] or {"ticker_news": {}, "market_sentiment": 0.0}


def update_news_cache():
    global _news_cache
    result = run_news_analysis()
    _news_cache["data"] = result
    _news_cache["updated_at"] = datetime.utcnow()
    logger.info(
        f"Noticias actualizadas: {result['total_articles']} articulos | "
        f"sentimiento mercado: {result['market_sentiment']}"
    )
    return result


def scan_and_trade() -> list[dict]:
    """
    Ciclo principal de trading.
    Retorna lista de acciones tomadas.
    """
    actions = []

    # ── 0. Verificar horario de mercado ─────────────────────────
    mkt = market_status()
    if not mkt["open"]:
        logger.info(f"Mercado {mkt['status']} — {mkt['detail']}. Ciclo omitido.")
        return [{"type": "INFO", "msg": f"Mercado {mkt['status']}: {mkt['detail']}"}]

    logger.info(f"Mercado ABIERTO ({mkt['et_time']}) — iniciando escaneo")

    # ── 1. Obtener precios ───────────────────────────────────────
    current_prices = get_current_prices(WATCHLIST)
    if not current_prices:
        logger.warning("No se pudieron obtener precios.")
        return actions

    equity = get_equity(current_prices)

    # ── 2. Circuit breaker ───────────────────────────────────────
    cb = circuit_breaker.check(equity)

    if cb["halted"]:
        logger.critical(f"[HALT] {cb['reason']} — cerrando todas las posiciones.")
        # Cerrar todo
        for pos in get_positions():
            price = current_prices.get(pos["ticker"], pos["avg_price"])
            pnl = close_position(pos["ticker"], price, "circuit_breaker_halt")
            actions.append({"type": "SELL", "ticker": pos["ticker"],
                            "price": price, "pnl": pnl, "reason": "HALT"})
        actions.append({"type": "HALT", "msg": cb["reason"]})
        return actions

    if cb["level"] == 2:
        logger.error(f"[REDUCCION] {cb['reason']} — cerrando posiciones, sin nuevas entradas.")
        for pos in get_positions():
            price = current_prices.get(pos["ticker"], pos["avg_price"])
            pnl = close_position(pos["ticker"], price, "circuit_breaker_reduce")
            actions.append({"type": "SELL", "ticker": pos["ticker"],
                            "price": price, "pnl": pnl, "reason": "REDUCE"})

    # ── 3. Chequear stop-loss / take-profit ──────────────────────
    from modules.risk_manager import check_exits
    exits = check_exits(current_prices)
    for exit_order in exits:
        pnl = close_position(exit_order["ticker"], exit_order["price"], exit_order["reason"])
        logger.info(
            f"CERRADA {exit_order['ticker']} @ ${exit_order['price']:.2f} "
            f"[{exit_order['reason']}] PnL=${pnl:+.2f}"
        )
        actions.append({"type": "SELL", "ticker": exit_order["ticker"],
                        "price": exit_order["price"], "pnl": pnl,
                        "reason": exit_order["reason"]})

    # ── 4. Escanear entradas (solo si CB permite) ─────────────────
    if cb["can_open"]:
        news_data = get_news_cache()
        market_sentiment = news_data.get("market_sentiment", 0.0)

        for ticker in WATCHLIST:
            try:
                tech = analyze_ticker(ticker)
                if tech is None:
                    continue

                ticker_news = news_data.get("ticker_news", {}).get(ticker, {"news_score": 0.0})
                signal = strategy.generate_signal(tech, ticker_news, market_sentiment)
                price = current_prices.get(ticker, tech["price"])

                if signal["action"] == "BUY":
                    ok, reason = can_open_position(ticker)
                    if not ok:
                        logger.debug(f"[{ticker}] BUY bloqueado: {reason}")
                        continue

                    qty = calc_position_size(price, current_prices)
                    if qty <= 0:
                        continue

                    stop, tp = calc_stops(price, tech["atr"])
                    open_position(ticker, qty, price, stop, tp)
                    logger.info(
                        f"ABIERTA {ticker} {qty:.4f}x @ ${price:.2f} "
                        f"[SL=${stop:.2f} TP=${tp:.2f}] conf={signal['confidence']:.2f}"
                    )
                    actions.append({
                        "type": "BUY", "ticker": ticker, "qty": qty,
                        "price": price, "confidence": signal["confidence"],
                        "reason": signal["reason"]
                    })

                elif signal["action"] == "SELL":
                    pos = get_position(ticker)
                    if pos:
                        pnl = close_position(ticker, price, "signal_sell")
                        logger.info(f"VENDIDA {ticker} @ ${price:.2f} PnL=${pnl:+.2f}")
                        actions.append({"type": "SELL", "ticker": ticker,
                                        "price": price, "pnl": pnl, "reason": "signal_sell"})

            except Exception as e:
                logger.error(f"[{ticker}] error: {e}", exc_info=True)
    else:
        logger.warning(f"[CB nivel {cb['level']}] No se abren nuevas posiciones.")

    # ── 5. Resumen del ciclo ─────────────────────────────────────
    risk = risk_check_portfolio(current_prices)
    logger.info(
        f"Equity=${equity:.2f} | Cash=${risk['cash']:.2f} | "
        f"Posiciones={risk['open_positions']} | CB={cb['label']}"
    )

    return actions
