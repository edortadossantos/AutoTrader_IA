"""
AutoTrader IA — Punto de entrada principal.

Uso:
    python main.py           # modo bot continuo (24/7 multi-mercado)
    python main.py --once    # ejecutar un ciclo y salir
    python main.py --report  # mostrar dashboard y salir

Mercados activos:
  • US Stocks/ETFs   → NYSE 9:30-16:00 ET (L-V)
  • Crypto (BTC/ETH/SOL) → 24/7 — el bot NUNCA duerme por crypto
  • Commodities futuros  → casi 24h (CME, pausa 1h/día)
"""
import sys
import io
import os
import time
import logging
import schedule
from datetime import datetime, timezone
from pathlib import Path

# ── Setup de logging ─────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

stdout_handler = logging.StreamHandler(
    io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "buffer") else sys.stdout
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/autotrader.log", encoding="utf-8"),
        stdout_handler,
    ],
)
logger = logging.getLogger("main")

from config import (
    SCAN_INTERVAL_MINUTES, CRYPTO_SCAN_INTERVAL_MIN,
    NEWS_INTERVAL_MINUTES, PRO_SIGNALS_INTERVAL_MIN,
    WATCHLIST, CRYPTO,
)
from modules.portfolio import init_db
from modules.trader import scan_all_markets, scan_crypto_only, update_news_cache, update_pro_cache
from modules.market_analyzer import get_current_prices
from modules.reporter import print_dashboard, console
from modules.portfolio import save_daily_snapshot
from modules.risk_manager import risk_check_portfolio
from modules.market_hours import is_market_open, market_status, next_market_open_utc
from modules import telegram_notifier as tg

_last_actions: list[dict] = []
_last_regime: str = ""


# ── Ciclos programados ───────────────────────────────────────────

def trading_cycle_all():
    """Escaneo completo: todos los activos con mercado abierto."""
    global _last_actions, _last_regime
    logger.info("=" * 60)
    logger.info("CICLO COMPLETO — Stocks + ETFs + Crypto + Commodities")
    actions = scan_all_markets()
    _last_actions = actions
    current_prices = get_current_prices(WATCHLIST)
    print_dashboard(current_prices, actions)
    # Detectar cambio de régimen de mercado
    try:
        from modules.market_regime import get_market_regime
        reg = get_market_regime()
        if _last_regime and reg["regime"] != _last_regime:
            tg.notify_regime_change(_last_regime, reg["regime"], reg["detail"])
        _last_regime = reg["regime"]
    except Exception:
        pass


def trading_cycle_crypto():
    """Ciclo solo crypto (cuando NYSE está cerrado)."""
    global _last_actions
    logger.info("-" * 40)
    logger.info("CICLO CRYPTO (NYSE cerrado)")
    actions = scan_crypto_only()
    _last_actions = actions
    current_prices = get_current_prices(CRYPTO)
    print_dashboard(current_prices, actions)


def news_cycle():
    update_news_cache()


def pro_cycle():
    update_pro_cache()


def daily_snapshot():
    current_prices = get_current_prices(WATCHLIST)
    risk = risk_check_portfolio(current_prices)
    from config import INITIAL_CAPITAL
    equity = risk["equity"]
    daily_pnl = equity - INITIAL_CAPITAL
    save_daily_snapshot(equity, daily_pnl)
    logger.info(f"Snapshot diario guardado. Equity=${equity:.2f}")


# ── Helpers ──────────────────────────────────────────────────────

def _setup_schedule_nyse_open():
    """Jobs para cuando NYSE está abierto (todos los mercados)."""
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(trading_cycle_all)
    schedule.every(NEWS_INTERVAL_MINUTES).minutes.do(news_cycle)
    schedule.every(PRO_SIGNALS_INTERVAL_MIN).minutes.do(pro_cycle)
    schedule.every().day.at("21:05").do(daily_snapshot)


def _setup_schedule_nyse_closed():
    """Jobs para cuando NYSE está cerrado (solo crypto + commodities)."""
    schedule.every(CRYPTO_SCAN_INTERVAL_MIN).minutes.do(trading_cycle_crypto)
    schedule.every(NEWS_INTERVAL_MINUTES).minutes.do(news_cycle)
    schedule.every().day.at("21:05").do(daily_snapshot)


def _wait_for_next_event() -> str:
    """
    Espera en bucle eficiente hasta que cambia el estado del mercado.
    Retorna 'nyse_open' o 'nyse_closed' según el cambio detectado.
    """
    was_open = is_market_open()
    while True:
        time.sleep(30)
        now_open = is_market_open()
        schedule.run_pending()
        if now_open != was_open:
            return "nyse_open" if now_open else "nyse_closed"


# ── Modos de ejecución ───────────────────────────────────────────

def run_once():
    init_db()
    update_news_cache()
    update_pro_cache()
    trading_cycle_all()


def run_bot():
    import atexit
    _PID_FILE = Path("bot.pid")
    _PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: _PID_FILE.unlink(missing_ok=True))

    init_db()
    mkt = market_status()

    console.print("[bold cyan]AutoTrader IA — MULTI-MARKET PAPER TRADING[/bold cyan]")
    console.print(
        f"Mercados: US Stocks (NYSE), Crypto 24/7, Commodities CME\n"
        f"NYSE ahora: [{'green' if mkt['open'] else 'yellow'}]{mkt['status']}[/] — {mkt['detail']}\n"
        f"Crypto: [green]SIEMPRE ACTIVO[/green]\n"
    )

    # Carga inicial de datos
    update_news_cache()
    update_pro_cache()

    # Notificar arranque por Telegram
    try:
        from modules.risk_manager import risk_check_portfolio
        _cp = get_current_prices(CRYPTO)
        _eq = risk_check_portfolio(_cp)["equity"]
        tg.notify_startup(_eq, mode="paper")
    except Exception:
        pass

    logger.info("Bot multi-mercado activo. Ctrl+C para detener.")

    try:
        while True:
            nyse_open = is_market_open()
            schedule.clear()

            if nyse_open:
                logger.info("NYSE ABIERTO — activando ciclo completo (stocks + crypto + commodities)")
                _setup_schedule_nyse_open()
                trading_cycle_all()   # ciclo inmediato
            else:
                mkt = market_status()
                logger.info(
                    f"NYSE CERRADO ({mkt['detail']}) — "
                    f"modo crypto-only activado (ciclo cada {CRYPTO_SCAN_INTERVAL_MIN} min)"
                )
                console.print(
                    f"[dim]NYSE cerrado — operando solo crypto/commodities. "
                    f"Dashboard: http://localhost:5000[/dim]"
                )
                _setup_schedule_nyse_closed()
                trading_cycle_crypto()  # ciclo inmediato

            # Esperar hasta que cambie el estado del mercado
            _wait_for_next_event()

    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario.")
        console.print("\n[yellow]Bot detenido.[/yellow]")


def show_report():
    init_db()
    current_prices = get_current_prices(WATCHLIST)
    print_dashboard(current_prices)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--once" in args:
        run_once()
    elif "--report" in args:
        show_report()
    else:
        run_bot()
