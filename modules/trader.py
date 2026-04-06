"""
Motor principal de trading multi-mercado.

Mercados soportados:
  • US Stocks/ETFs  → solo en horario NYSE (9:30-16:00 ET, L-V)
  • Crypto          → 24/7 (BTC, ETH, SOL siempre activos)
  • Commodities     → casi 24h (futuros CME, pausa 1h/día)
  • ETFs intl       → siguen horario NYSE

El bot nunca duerme: cuando NYSE cierra sigue operando crypto y futuros.
"""
import logging
from datetime import datetime

from config import WATCHLIST, CRYPTO, COMMODITIES, SCREENER_ENABLED, get_asset_class, get_asset_params
from modules.market_analyzer import analyze_ticker, get_current_prices
from modules.news_analyzer import run_news_analysis
from modules.pro_signals import run_pro_signals
from modules.market_screener import get_screener_tickers
from modules.risk_manager import (
    can_open_position, calc_position_size, calc_stops,
    check_exits, risk_check_portfolio
)
from modules.portfolio import (
    open_position, close_position, get_position, get_positions,
    save_daily_snapshot, get_equity
)
from modules.market_hours import is_market_open, market_status
from modules.market_regime import get_market_regime
from modules import circuit_breaker
from modules import telegram_notifier as tg
from modules.options_flow import get_ticker_options_score
from strategies.combined_strategy import CombinedStrategy

logger = logging.getLogger(__name__)
strategy = CombinedStrategy()

_news_cache = {"data": None, "updated_at": None}
_pro_cache  = {"data": None, "updated_at": None}


def get_news_cache() -> dict:
    return _news_cache["data"] or {"ticker_news": {}, "market_sentiment": 0.0}


def get_pro_cache() -> dict:
    return _pro_cache["data"] or {"ticker_signals": {}}


def update_news_cache():
    global _news_cache
    result = run_news_analysis()
    _news_cache["data"] = result
    _news_cache["updated_at"] = datetime.utcnow()
    logger.info(
        f"Noticias actualizadas: {result['total_articles']} artículos | "
        f"sentimiento mercado: {result['market_sentiment']} | "
        f"fuentes: {len(result.get('sources_active', []))}"
    )
    return result


def update_pro_cache():
    global _pro_cache
    result = run_pro_signals()
    _pro_cache["data"] = result
    _pro_cache["updated_at"] = datetime.utcnow()
    eco  = result.get("economic_events", [])
    earn = result.get("upcoming_earnings", [])
    logger.info(
        f"Señales pro actualizadas | "
        f"earnings próximos: {len(earn)} | eventos macro: {len(eco)}"
    )
    return result


def _get_active_tickers() -> list[str]:
    """
    Retorna los tickers que tienen mercado abierto AHORA.
    Crypto siempre. Stocks/ETFs solo en horario NYSE. Futuros casi siempre.
    """
    now = datetime.utcnow()
    return [t for t in WATCHLIST if is_market_open(now, t)]


def scan_and_trade(tickers: list[str] | None = None) -> list[dict]:
    """
    Ciclo principal de trading multi-mercado.
    Si se pasa 'tickers', solo escanea esos (ej: solo crypto).
    """
    actions = []

    # Si no se especifica, usar todos los que tienen mercado abierto ahora
    active = list(tickers) if tickers else _get_active_tickers()
    if not active:
        return [{"type": "INFO", "msg": "No hay mercados activos en este momento"}]

    # ── Screener dinámico: añadir candidatos cuando NYSE está abierto ─────────
    screener_tickers: list[str] = []
    if tickers is None and SCREENER_ENABLED:
        mkt_check = market_status()
        if mkt_check["open"]:
            try:
                screener_tickers = get_screener_tickers()
                new_ones = [t for t in screener_tickers if t not in active]
                if new_ones:
                    logger.info(f"Screener añade {len(new_ones)} candidatos: {new_ones}")
                    active = active + new_ones
            except Exception as e:
                logger.warning(f"Screener error: {e}")

    # Clasificar por tipo para el log
    crypto_active   = [t for t in active if get_asset_class(t) == "crypto"]
    stock_active    = [t for t in active if get_asset_class(t) == "stock"]
    etf_active      = [t for t in active if get_asset_class(t) in ("etf", "intl")]
    commo_active    = [t for t in active if get_asset_class(t) == "commodity"]
    screened_count  = len([t for t in active if t in screener_tickers])

    mkt = market_status()
    logger.info(
        f"Mercado NYSE: {mkt['status']} | "
        f"Activos escaneando: stocks={len(stock_active)} ETFs={len(etf_active)} "
        f"crypto={len(crypto_active)} commodities={len(commo_active)} "
        f"screener={screened_count}"
    )

    # ── 1. Obtener precios ───────────────────────────────────────
    current_prices = get_current_prices(active)
    if not current_prices:
        logger.warning("No se pudieron obtener precios.")
        return actions

    equity = get_equity(current_prices)

    # ── 2. Circuit breaker ───────────────────────────────────────
    cb = circuit_breaker.check(equity)

    if cb["halted"]:
        logger.critical(f"[HALT] {cb['reason']} — cerrando todas las posiciones.")
        tg.notify_halt(cb["reason"])
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
    exits = check_exits(current_prices)
    for exit_order in exits:
        pnl = close_position(exit_order["ticker"], exit_order["price"], exit_order["reason"])
        logger.info(
            f"CERRADA {exit_order['ticker']} @ ${exit_order['price']:.4f} "
            f"[{exit_order['reason']}] PnL=${pnl:+.2f}"
        )
        tg.notify_sell(exit_order["ticker"], exit_order["price"], pnl, exit_order["reason"])
        actions.append({"type": "SELL", "ticker": exit_order["ticker"],
                        "price": exit_order["price"], "pnl": pnl,
                        "reason": exit_order["reason"]})

    # ── 4. Régimen de mercado ────────────────────────────────────
    regime = get_market_regime()
    if regime["regime"] == "bear":
        logger.warning(f"[RÉGIMEN] {regime['detail']}")
    elif regime["regime"] == "neutral":
        logger.info(f"[RÉGIMEN] {regime['detail']}")
    else:
        logger.info(f"[RÉGIMEN] {regime['detail']}")

    # ── 5. Escanear entradas ─────────────────────────────────────
    if not cb["can_open"]:
        logger.warning(f"[CB nivel {cb['level']}] No se abren nuevas posiciones.")
    else:
        news_data        = get_news_cache()
        pro_data         = get_pro_cache()
        market_sentiment = news_data.get("market_sentiment", 0.0)

        for ticker in active:
            try:
                tech = analyze_ticker(ticker)
                if tech is None:
                    continue

                asset_class  = get_asset_class(ticker)
                params       = get_asset_params(ticker)
                ticker_news  = news_data.get("ticker_news", {}).get(ticker, {"news_score": 0.0})
                ticker_pro   = pro_data.get("ticker_signals", {}).get(ticker)
                options_score = get_ticker_options_score(ticker)

                # Umbral ajustado por régimen de mercado
                adjusted_min_score = params["min_score"] * regime["min_score_mult"]

                signal = strategy.generate_signal(
                    tech, ticker_news, market_sentiment, ticker_pro,
                    min_score=adjusted_min_score,
                    options_score=options_score,
                )
                price = current_prices.get(ticker, tech["price"])

                if signal["action"] == "BUY":
                    ok, reason = can_open_position(ticker, current_prices)
                    if not ok:
                        logger.debug(f"[{ticker}] BUY bloqueado: {reason}")
                        continue

                    qty = calc_position_size(ticker, price, current_prices)
                    if qty <= 0:
                        continue

                    stop, tp = calc_stops(ticker, price, tech["atr"])
                    open_position(ticker, qty, price, stop, tp)
                    logger.info(
                        f"ABIERTA [{asset_class.upper()}] {ticker} {qty:.6f}x @ ${price:.4f} "
                        f"[SL=${stop:.4f} TP=${tp:.4f}] conf={signal['confidence']:.2f} "
                        f"régimen={regime['regime']} score_min={adjusted_min_score:.3f}"
                    )
                    tg.notify_buy(
                        ticker, qty, price, stop, tp,
                        signal["confidence"], asset_class,
                        regime=regime["regime"],
                    )
                    actions.append({
                        "type": "BUY", "ticker": ticker, "asset_class": asset_class,
                        "qty": qty, "price": price,
                        "confidence": signal["confidence"],
                        "reason": signal["reason"]
                    })

                elif signal["action"] == "SELL":
                    pos = get_position(ticker)
                    if pos:
                        pnl = close_position(ticker, price, "signal_sell")
                        logger.info(f"VENDIDA {ticker} @ ${price:.4f} PnL=${pnl:+.2f}")
                        tg.notify_sell(ticker, price, pnl, "signal_sell")
                        actions.append({"type": "SELL", "ticker": ticker,
                                        "price": price, "pnl": pnl, "reason": "signal_sell"})

            except Exception as e:
                logger.error(f"[{ticker}] error: {e}", exc_info=True)

    # ── 5. Resumen del ciclo ─────────────────────────────────────
    risk = risk_check_portfolio(current_prices)
    logger.info(
        f"Equity=${equity:.2f} | Cash=${risk['cash']:.2f} | "
        f"Posiciones={risk['open_positions']} | "
        f"Por clase: {risk['by_class']} | CB={cb['label']}"
    )

    return actions


def scan_crypto_only() -> list[dict]:
    """Ciclo dedicado a crypto (se llama cuando NYSE está cerrado)."""
    return scan_and_trade(tickers=CRYPTO)


def scan_all_markets() -> list[dict]:
    """Ciclo completo: todos los activos con mercado abierto."""
    return scan_and_trade()
