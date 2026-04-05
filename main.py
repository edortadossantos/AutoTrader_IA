"""
AutoTrader IA — Punto de entrada principal.

Uso:
    python main.py           # modo bot continuo (24/7 paper trading)
    python main.py --once    # ejecutar un ciclo y salir
    python main.py --report  # mostrar dashboard y salir
"""
import sys
import io
import time
import logging
import schedule
from datetime import datetime, timezone
from pathlib import Path

# ── Setup de logging ─────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

# Forzar UTF-8 en consola Windows
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

from config import SCAN_INTERVAL_MINUTES, NEWS_INTERVAL_MINUTES, WATCHLIST
from modules.portfolio import init_db
from modules.trader import scan_and_trade, update_news_cache
from modules.market_analyzer import get_current_prices
from modules.reporter import print_dashboard, console
from modules.portfolio import save_daily_snapshot
from modules.risk_manager import risk_check_portfolio


_last_actions: list[dict] = []


def trading_cycle():
    global _last_actions
    logger.info("=" * 60)
    logger.info("INICIO DE CICLO DE TRADING")
    actions = scan_and_trade()
    _last_actions = actions

    current_prices = get_current_prices(WATCHLIST)
    print_dashboard(current_prices, actions)


def news_cycle():
    logger.info("Actualizando noticias...")
    update_news_cache()


def daily_snapshot():
    current_prices = get_current_prices(WATCHLIST)
    risk = risk_check_portfolio(current_prices)
    from modules.portfolio import get_stats
    stats = get_stats()
    from config import INITIAL_CAPITAL
    equity = risk["equity"]
    daily_pnl = equity - INITIAL_CAPITAL  # simplificado; en prod calcularías delta diario
    save_daily_snapshot(equity, daily_pnl)
    logger.info(f"Snapshot diario guardado. Equity=${equity:.2f}")


def run_once():
    init_db()
    update_news_cache()
    trading_cycle()


def run_bot():
    init_db()
    console.print("[bold cyan]AutoTrader IA iniciado en modo PAPER TRADING[/bold cyan]")
    console.print(f"Intervalo de mercado: {SCAN_INTERVAL_MINUTES} min | Noticias: {NEWS_INTERVAL_MINUTES} min\n")

    # Primera ejecución inmediata
    update_news_cache()
    trading_cycle()

    # Programar tareas periódicas
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(trading_cycle)
    schedule.every(NEWS_INTERVAL_MINUTES).minutes.do(news_cycle)
    schedule.every().day.at("21:05").do(daily_snapshot)  # snapshot al cierre de NYSE (UTC)

    logger.info("Bot activo. Ctrl+C para detener.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
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
