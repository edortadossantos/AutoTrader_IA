"""
Dashboard en terminal usando Rich.
"""
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

from modules.portfolio import get_stats, get_trade_history, get_positions, get_cash
from modules.risk_manager import risk_check_portfolio
from config import INITIAL_CAPITAL

console = Console()


def _pnl_color(val: float) -> str:
    return "green" if val >= 0 else "red"


def print_dashboard(current_prices: dict, last_actions: list[dict] = None):
    console.clear()

    # ── Header ──────────────────────────────────────────────────
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    console.print(Panel(
        f"[bold cyan]AutoTrader IA[/bold cyan]  |  [dim]{now}[/dim]  |  [yellow]PAPER TRADING[/yellow]",
        box=box.DOUBLE_EDGE
    ))

    # ── Resumen de cuenta ────────────────────────────────────────
    risk = risk_check_portfolio(current_prices)
    stats = get_stats()
    equity = risk["equity"]
    pnl_total = equity - INITIAL_CAPITAL
    pnl_pct = (pnl_total / INITIAL_CAPITAL) * 100

    summary_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary_table.add_column("Key", style="dim")
    summary_table.add_column("Value", style="bold")
    summary_table.add_row("Capital inicial", f"${INITIAL_CAPITAL:,.2f}")
    summary_table.add_row("Equity actual", f"[{_pnl_color(pnl_total)}]${equity:,.2f}[/]")
    summary_table.add_row("PnL total", f"[{_pnl_color(pnl_total)}]{pnl_pct:+.2f}% (${pnl_total:+,.2f})[/]")
    summary_table.add_row("Cash libre", f"${risk['cash']:,.2f}")
    summary_table.add_row("Exposición", f"{risk['exposure_pct']:.1%}")
    summary_table.add_row("Operaciones totales", str(stats["total_trades"]))
    summary_table.add_row("Win rate", f"{stats['win_rate']:.1%}" if stats["total_trades"] > 0 else "—")
    summary_table.add_row("PnL realizado", f"[{_pnl_color(stats['total_pnl'])}]${stats['total_pnl']:+,.2f}[/]")

    console.print(Panel(summary_table, title="[bold]Resumen de Cuenta[/bold]", border_style="cyan"))

    # ── Posiciones abiertas ──────────────────────────────────────
    if risk["position_details"]:
        pos_table = Table(box=box.SIMPLE_HEAD)
        pos_table.add_column("Ticker", style="cyan bold")
        pos_table.add_column("Precio actual", justify="right")
        pos_table.add_column("Precio entrada", justify="right")
        pos_table.add_column("PnL no realizado", justify="right")
        pos_table.add_column("%", justify="right")
        pos_table.add_column("Stop Loss", justify="right")
        pos_table.add_column("Take Profit", justify="right")

        for pos_info in risk["position_details"]:
            ticker = pos_info["ticker"]
            pos = next((p for p in get_positions() if p["ticker"] == ticker), {})
            curr = current_prices.get(ticker, 0)
            pnl_color = _pnl_color(pos_info["unrealized_pnl"])
            pos_table.add_row(
                ticker,
                f"${curr:.2f}",
                f"${pos.get('avg_price', 0):.2f}",
                f"[{pnl_color}]${pos_info['unrealized_pnl']:+,.2f}[/]",
                f"[{pnl_color}]{pos_info['pnl_pct']:+.2f}%[/]",
                f"${pos.get('stop_loss', 0):.2f}",
                f"${pos.get('take_profit', 0):.2f}",
            )
        console.print(Panel(pos_table, title="[bold]Posiciones Abiertas[/bold]", border_style="yellow"))
    else:
        console.print(Panel("[dim]Sin posiciones abiertas[/dim]", border_style="yellow"))

    # ── Últimas operaciones ──────────────────────────────────────
    history = get_trade_history(limit=10)
    if history:
        hist_table = Table(box=box.SIMPLE_HEAD)
        hist_table.add_column("Tiempo (UTC)", style="dim")
        hist_table.add_column("Ticker", style="cyan")
        hist_table.add_column("Lado")
        hist_table.add_column("Precio", justify="right")
        hist_table.add_column("PnL", justify="right")
        hist_table.add_column("Razón")

        for t in history:
            side_style = "green bold" if t["side"] == "BUY" else "red bold"
            pnl_str = f"[{_pnl_color(t['pnl'] or 0)}]${t['pnl']:+,.2f}[/]" if t["pnl"] is not None else "—"
            hist_table.add_row(
                t["executed_at"][:16],
                t["ticker"],
                f"[{side_style}]{t['side']}[/]",
                f"${t['price']:.2f}",
                pnl_str,
                (t["reason"] or "")[:30],
            )
        console.print(Panel(hist_table, title="[bold]Últimas Operaciones[/bold]", border_style="blue"))

    # ── Acciones recientes ──────────────────────────────────────
    if last_actions:
        lines = []
        for a in last_actions[-5:]:
            if a["type"] == "BUY":
                lines.append(f"[green]▲ BUY[/green] {a['ticker']} @ ${a['price']:.2f} (conf={a.get('confidence', 0):.2f})")
            else:
                pnl = a.get("pnl", 0) or 0
                lines.append(f"[red]▼ SELL[/red] {a['ticker']} @ ${a['price']:.2f} PnL=[{_pnl_color(pnl)}]${pnl:+.2f}[/] [{a.get('reason','')}]")
        console.print(Panel("\n".join(lines), title="[bold]Acciones del Ciclo[/bold]", border_style="magenta"))
