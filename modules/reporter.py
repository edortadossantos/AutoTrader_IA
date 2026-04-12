"""
Dashboard en terminal usando Rich — versión mejorada.
"""
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich import box

from modules.portfolio import (
    get_stats, get_trade_history, get_positions, get_cash,
    get_equity, get_active_cooldowns,
)
from config import INITIAL_CAPITAL

console = Console()

# ── Nombres legibles por ticker ───────────────────────────────────────────────
TICKER_NAMES = {
    # US Tech
    "AAPL":     "Apple — smartphones & ecosystem",
    "MSFT":     "Microsoft — cloud & software",
    "GOOGL":    "Alphabet — Google search & ads",
    "NVDA":     "NVIDIA — GPUs & AI chips",
    "META":     "Meta — Facebook, Instagram, WhatsApp",
    "AMZN":     "Amazon — e-commerce & AWS cloud",
    "TSLA":     "Tesla — coches eléctricos & energía",
    "AMD":      "AMD — procesadores y GPUs",
    "NFLX":     "Netflix — streaming de vídeo",
    "ORCL":     "Oracle — bases de datos & cloud",
    # US Financials
    "JPM":      "JPMorgan — banco más grande de EEUU",
    "BAC":      "Bank of America",
    "GS":       "Goldman Sachs — banca de inversión",
    "BRK-B":    "Berkshire Hathaway — Buffett holding",
    # US Energy
    "XOM":      "ExxonMobil — petróleo & gas",
    "CVX":      "Chevron — petróleo & gas",
    # US Health
    "JNJ":      "Johnson & Johnson — salud diversificada",
    "UNH":      "UnitedHealth — seguro médico EEUU",
    # US Consumer
    "WMT":      "Walmart — supermercados líder EEUU",
    "HD":       "Home Depot — bricolaje & construcción",
    # ETFs
    "SPY":      "ETF S&P 500 — las 500 mayores empresas USA",
    "QQQ":      "ETF Nasdaq 100 — tech pura americana",
    "IWM":      "ETF Russell 2000 — pequeñas empresas USA",
    "XLK":      "ETF Sector Tecnología USA",
    "XLF":      "ETF Sector Financiero USA",
    "XLE":      "ETF Sector Energía USA",
    "XLV":      "ETF Sector Salud USA",
    "XLI":      "ETF Sector Industrial USA",
    "XLU":      "ETF Sector Utilities (defensivo)",
    "XLP":      "ETF Consumer Staples (defensivo)",
    "GLD":      "ETF Oro físico — refugio en crisis",
    "SLV":      "ETF Plata física",
    "USO":      "ETF Petróleo WTI futuros",
    "TLT":      "ETF Bonos EEUU largo plazo",
    "SH":       "ETF Inverso S&P 500 × 1 (sube si baja el índice)",
    "PSQ":      "ETF Inverso Nasdaq × 1 (sube si baja Nasdaq)",
    "SDS":      "ETF Inverso S&P 500 × 2 (doble apalancado bajista)",
    "SQQQ":     "ETF Inverso Nasdaq × 3 (triple bajista — MUY volátil)",
    # Crypto
    "BTC-USD":  "Bitcoin — líder de mercado cripto",
    "ETH-USD":  "Ethereum — contratos inteligentes & DeFi",
    "SOL-USD":  "Solana — blockchain rápida, alto momentum",
    "BNB-USD":  "Binance Coin — token del exchange Binance",
    "XRP-USD":  "XRP (Ripple) — pagos internacionales",
    "AVAX-USD": "Avalanche — DeFi alternativo, alta volatilidad",
    "LINK-USD": "Chainlink — oráculos: conecta cripto con datos reales",
    # Commodities futuros
    "GC=F":     "Oro futuros — sube con miedo o dólar débil",
    "CL=F":     "Petróleo WTI futuros — ligado a inflación & geopolítica",
    "SI=F":     "Plata futuros — mezcla de metal refugio e industrial",
    # Internacional
    "EFA":      "ETF Mercados desarrollados (Europa, Japón, Australia)",
    "EEM":      "ETF Mercados emergentes (China, India, Brasil)",
}

# ── Grupos para tabla de precios ──────────────────────────────────────────────
PRICE_GROUPS = [
    ("US Tech",       ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA", "AMD", "NFLX", "ORCL"]),
    ("Financials",    ["JPM", "BAC", "GS", "BRK-B"]),
    ("Energía/Salud", ["XOM", "CVX", "JNJ", "UNH", "WMT", "HD"]),
    ("ETFs Amplios",  ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "USO"]),
    ("ETFs Sector",   ["XLK", "XLF", "XLE", "XLV", "XLI", "XLU", "XLP"]),
    ("ETFs Inversos", ["SH", "PSQ", "SDS", "SQQQ"]),
    ("Crypto",        ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "AVAX-USD", "LINK-USD"]),
    ("Commodities",   ["GC=F", "CL=F", "SI=F"]),
    ("Internacional", ["EFA", "EEM"]),
]


def _color(val: float) -> str:
    return "green" if val >= 0 else "red"


def _pct_bar(pct: float, width: int = 10) -> str:
    """Barra visual de porcentaje (0–100%)."""
    filled = int(min(pct, 1.0) * width)
    return "█" * filled + "░" * (width - filled)


def print_dashboard(current_prices: dict, last_actions: list[dict] = None):
    console.clear()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # ══════════════════════════════════════════════════════════════
    # HEADER
    # ══════════════════════════════════════════════════════════════
    console.print(Panel(
        f"[bold cyan]AutoTrader IA[/bold cyan]   [dim]{now}[/dim]   [bold yellow]◉ PAPER TRADING[/bold yellow]",
        box=box.DOUBLE_EDGE, padding=(0, 2)
    ))

    # ══════════════════════════════════════════════════════════════
    # BALANCE DE CUENTA — desglosado
    # ══════════════════════════════════════════════════════════════
    positions   = get_positions()
    cash        = get_cash()
    invested    = sum(
        p["qty"] * current_prices.get(p["ticker"], p["avg_price"])
        for p in positions if p.get("side", "LONG") == "LONG"
    )
    equity      = cash + invested
    pnl_total   = equity - INITIAL_CAPITAL
    pnl_pct     = (pnl_total / INITIAL_CAPITAL) * 100
    stats       = get_stats()

    # Barra de distribución cash vs invertido
    invest_pct  = invested / equity if equity > 0 else 0
    cash_pct    = cash / equity if equity > 0 else 1

    bal = Table(box=box.SIMPLE, show_header=False, padding=(0, 3))
    bal.add_column("Label", style="dim", min_width=20)
    bal.add_column("Valor", style="bold", justify="right", min_width=14)
    bal.add_column("Info", justify="left")

    bal.add_row(
        "Capital inicial",
        f"${INITIAL_CAPITAL:,.2f}", ""
    )
    bal.add_row(
        "[bold]Equity actual[/bold]",
        f"[{_color(pnl_total)}][bold]${equity:,.2f}[/bold][/]",
        f"[{_color(pnl_total)}]{pnl_pct:+.2f}%  ({'+' if pnl_total>=0 else ''}${pnl_total:,.2f})[/]"
    )
    bal.add_row("", "", "")
    bal.add_row(
        "  Invertido en posiciones",
        f"${invested:,.2f}",
        f"[cyan]{_pct_bar(invest_pct)}[/cyan] {invest_pct:.1%}"
    )
    bal.add_row(
        "  Cash disponible",
        f"[green]${cash:,.2f}[/green]",
        f"[green]{_pct_bar(cash_pct)}[/green] {cash_pct:.1%}"
    )
    bal.add_row("", "", "")
    bal.add_row(
        "Operaciones cerradas",
        str(stats["total_trades"]),
        f"Win rate: [bold]{stats['win_rate']:.1%}[/bold]" if stats["total_trades"] > 0 else "—"
    )
    bal.add_row(
        "PnL realizado",
        f"[{_color(stats['total_pnl'])}]${stats['total_pnl']:+,.2f}[/]",
        f"Avg win ${stats['avg_win']:+,.2f}  /  Avg loss ${stats['avg_loss']:+,.2f}" if stats["total_trades"] > 0 else ""
    )

    console.print(Panel(bal, title="[bold]Resumen de Cuenta[/bold]", border_style="cyan"))

    # ══════════════════════════════════════════════════════════════
    # POSICIONES ABIERTAS — con qty, coste y valor
    # ══════════════════════════════════════════════════════════════
    if positions:
        pos_table = Table(box=box.SIMPLE_HEAD, show_lines=False)
        pos_table.add_column("Ticker",       style="cyan bold", min_width=10)
        pos_table.add_column("Nombre",       style="dim",       min_width=28)
        pos_table.add_column("Lado",         justify="center",  min_width=6)
        pos_table.add_column("Partic.",      justify="right",   min_width=8)
        pos_table.add_column("Precio entr.", justify="right",   min_width=12)
        pos_table.add_column("Precio act.",  justify="right",   min_width=12)
        pos_table.add_column("Coste total",  justify="right",   min_width=12)
        pos_table.add_column("Valor act.",   justify="right",   min_width=12)
        pos_table.add_column("PnL ($)",      justify="right",   min_width=10)
        pos_table.add_column("PnL (%)",      justify="right",   min_width=8)
        pos_table.add_column("Stop",         justify="right",   min_width=10)
        pos_table.add_column("Take Profit",  justify="right",   min_width=10)

        for p in positions:
            ticker      = p["ticker"]
            curr_price  = current_prices.get(ticker, p["avg_price"])
            qty         = p["qty"]
            side        = p.get("side", "LONG")
            coste       = qty * p["avg_price"]
            valor_act   = qty * curr_price
            if side == "LONG":
                pnl_u   = valor_act - coste
                pnl_p   = (curr_price - p["avg_price"]) / p["avg_price"] * 100
            else:
                pnl_u   = (p["avg_price"] - curr_price) * qty
                pnl_p   = (p["avg_price"] - curr_price) / p["avg_price"] * 100

            c = _color(pnl_u)
            side_fmt = f"[green]LONG[/green]" if side == "LONG" else "[red]SHORT[/red]"

            # Formato qty: si es cripto puede ser decimal
            qty_str = f"{qty:,.4f}" if qty < 1 else f"{qty:,.2f}"

            pos_table.add_row(
                ticker,
                TICKER_NAMES.get(ticker, ticker)[:28],
                side_fmt,
                qty_str,
                f"${p['avg_price']:,.2f}",
                f"${curr_price:,.2f}",
                f"${coste:,.2f}",
                f"[{c}]${valor_act:,.2f}[/]",
                f"[{c}]{'+' if pnl_u >= 0 else ''}${pnl_u:,.2f}[/]",
                f"[{c}]{pnl_p:+.2f}%[/]",
                f"${p.get('stop_loss', 0):,.2f}" if p.get('stop_loss') else "—",
                f"${p.get('take_profit', 0):,.2f}" if p.get('take_profit') else "—",
            )

        n_pos = len(positions)
        from config import MAX_OPEN_POSITIONS
        title_pos = f"[bold]Posiciones Abiertas[/bold]  [{n_pos}/{MAX_OPEN_POSITIONS}]"
        console.print(Panel(pos_table, title=title_pos, border_style="yellow"))
    else:
        console.print(Panel(
            "[dim]Sin posiciones abiertas — el bot está buscando señales...[/dim]",
            title="[bold]Posiciones Abiertas[/bold]",
            border_style="yellow"
        ))

    # ══════════════════════════════════════════════════════════════
    # ACCIONES DEL CICLO ACTUAL
    # ══════════════════════════════════════════════════════════════
    if last_actions:
        lines = []
        for a in last_actions[-6:]:
            ticker = a["ticker"]
            nombre = TICKER_NAMES.get(ticker, ticker).split("—")[0].strip()
            if a["type"] == "BUY":
                lines.append(
                    f"[green bold]▲ COMPRA[/green bold]  {ticker} [dim]({nombre})[/dim]  "
                    f"@ ${a['price']:.2f}  confianza={a.get('confidence', 0):.0%}"
                )
            else:
                pnl = a.get("pnl", 0) or 0
                c = _color(pnl)
                lines.append(
                    f"[red bold]▼ VENTA[/red bold]   {ticker} [dim]({nombre})[/dim]  "
                    f"@ ${a['price']:.2f}  PnL=[{c}]${pnl:+.2f}[/]  [{a.get('reason', '')}]"
                )
        console.print(Panel(
            "\n".join(lines),
            title="[bold]Acciones del Ciclo Actual[/bold]",
            border_style="magenta"
        ))

    # ══════════════════════════════════════════════════════════════
    # HISTORIAL — últimas 8 operaciones
    # ══════════════════════════════════════════════════════════════
    history = get_trade_history(limit=8)
    if history:
        hist = Table(box=box.SIMPLE_HEAD)
        hist.add_column("Fecha (UTC)",  style="dim",       min_width=16)
        hist.add_column("Ticker",       style="cyan",      min_width=10)
        hist.add_column("Descripción",  style="dim",       min_width=26)
        hist.add_column("Lado",         justify="center",  min_width=7)
        hist.add_column("Partic.",      justify="right",   min_width=8)
        hist.add_column("Precio",       justify="right",   min_width=10)
        hist.add_column("Total",        justify="right",   min_width=10)
        hist.add_column("PnL",          justify="right",   min_width=10)
        hist.add_column("Motivo",       style="dim",       min_width=20)

        for t in history:
            side_style = "green bold" if t["side"] in ("BUY",) else "red bold"
            pnl_str = (
                f"[{_color(t['pnl'])}]${t['pnl']:+,.2f}[/]"
                if t["pnl"] is not None else "—"
            )
            total = t["qty"] * t["price"]
            qty_str = f"{t['qty']:,.4f}" if t["qty"] < 1 else f"{t['qty']:,.2f}"
            hist.add_row(
                t["executed_at"][:16],
                t["ticker"],
                TICKER_NAMES.get(t["ticker"], t["ticker"])[:26],
                f"[{side_style}]{t['side']}[/]",
                qty_str,
                f"${t['price']:,.2f}",
                f"${total:,.2f}",
                pnl_str,
                (t["reason"] or "")[:22],
            )
        console.print(Panel(hist, title="[bold]Últimas Operaciones[/bold]", border_style="blue"))

    # ══════════════════════════════════════════════════════════════
    # PRECIOS DEL MERCADO — agrupados por clase
    # ══════════════════════════════════════════════════════════════
    if current_prices:
        # Sólo mostrar tickers que tenemos en current_prices
        tables_to_show = []
        for group_name, tickers in PRICE_GROUPS:
            available = [t for t in tickers if t in current_prices]
            if not available:
                continue

            t = Table(box=box.SIMPLE_HEAD, title=f"[bold dim]{group_name}[/bold dim]",
                      show_lines=False, padding=(0, 1))
            t.add_column("Ticker", style="cyan", min_width=10)
            t.add_column("Nombre corto", style="dim", min_width=22)
            t.add_column("Precio", justify="right", min_width=10)

            for ticker in available:
                price = current_prices[ticker]
                name_parts = TICKER_NAMES.get(ticker, ticker).split("—")
                short_name = name_parts[0].strip()[:22]
                in_portfolio = any(p["ticker"] == ticker for p in positions)
                ticker_display = f"[bold]{ticker}[/bold]" if in_portfolio else ticker
                price_fmt = f"${price:,.2f}" if price >= 1 else f"${price:.4f}"
                t.add_row(ticker_display, short_name, price_fmt)

            tables_to_show.append(t)

        if tables_to_show:
            console.print(Panel(
                Columns(tables_to_show, equal=False, expand=False, padding=(0, 2)),
                title="[bold]Precios de Mercado[/bold]  [dim](en negrita = posición abierta)[/dim]",
                border_style="dim"
            ))

    # ══════════════════════════════════════════════════════════════
    # COOLDOWNS ACTIVOS
    # ══════════════════════════════════════════════════════════════
    cooldowns = get_active_cooldowns()
    if cooldowns:
        cd_table = Table(box=box.SIMPLE_HEAD)
        cd_table.add_column("Ticker",       style="cyan",  min_width=10)
        cd_table.add_column("Descripción",  style="dim",   min_width=26)
        cd_table.add_column("Bloqueado hasta (UTC)", style="yellow", min_width=18)
        cd_table.add_column("Motivo",       style="dim",   min_width=18)
        for cd in cooldowns:
            cd_table.add_row(
                cd["ticker"],
                TICKER_NAMES.get(cd["ticker"], cd["ticker"])[:26],
                cd["blocked_until"][:16],
                cd["reason"] or "",
            )
        console.print(Panel(
            cd_table,
            title=f"[bold]Cooldowns Activos[/bold]  [dim]({len(cooldowns)} ticker(s) bloqueados temporalmente)[/dim]",
            border_style="red"
        ))
