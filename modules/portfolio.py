"""
Gestión de cartera paper-trading con persistencia en SQLite.
"""
import sqlite3
from datetime import datetime, timedelta
from config import DB_PATH, INITIAL_CAPITAL, DISPLAY_CURRENCY, COOLDOWN_HOURS
from config import get_asset_class


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _conn() as con:
        cur = con.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY,
            cash REAL NOT NULL,
            initial_capital REAL NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL UNIQUE,
            qty REAL NOT NULL,
            avg_price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            trailing_high REAL,
            opened_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            pnl REAL,
            reason TEXT,
            executed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            equity REAL NOT NULL,
            cash REAL NOT NULL,
            open_positions INTEGER NOT NULL,
            daily_pnl REAL
        );

        CREATE TABLE IF NOT EXISTS cooldowns (
            ticker TEXT PRIMARY KEY,
            blocked_until TEXT NOT NULL,
            reason TEXT
        );
        """)

        # Migración: añadir trailing_high si la tabla ya existía sin ella
        try:
            cur.execute("ALTER TABLE positions ADD COLUMN trailing_high REAL")
            con.commit()
        except Exception:
            pass  # columna ya existe

        # Inicializar cuenta si no existe
        if cur.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 0:
            if DISPLAY_CURRENCY == "EUR":
                from modules.currency import eur_to_usd
                initial_usd = eur_to_usd(INITIAL_CAPITAL)
            else:
                initial_usd = INITIAL_CAPITAL
            cur.execute(
                "INSERT INTO account (id, cash, initial_capital, created_at) VALUES (1, ?, ?, ?)",
                (initial_usd, initial_usd, datetime.utcnow().isoformat())
            )
        con.commit()


def get_cash() -> float:
    with _conn() as con:
        return con.execute("SELECT cash FROM account WHERE id=1").fetchone()[0]


def update_cash(amount: float):
    with _conn() as con:
        con.execute("UPDATE account SET cash = cash + ? WHERE id=1", (amount,))


def get_positions() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT ticker, qty, avg_price, stop_loss, take_profit, trailing_high, opened_at "
            "FROM positions"
        ).fetchall()
    return [
        {
            "ticker": r[0], "qty": r[1], "avg_price": r[2],
            "stop_loss": r[3], "take_profit": r[4],
            "trailing_high": r[5], "opened_at": r[6],
        }
        for r in rows
    ]


def get_position(ticker: str) -> dict | None:
    with _conn() as con:
        r = con.execute(
            "SELECT ticker, qty, avg_price, stop_loss, take_profit, trailing_high, opened_at "
            "FROM positions WHERE ticker=?",
            (ticker,)
        ).fetchone()
    if not r:
        return None
    return {
        "ticker": r[0], "qty": r[1], "avg_price": r[2],
        "stop_loss": r[3], "take_profit": r[4],
        "trailing_high": r[5], "opened_at": r[6],
    }


def open_position(ticker: str, qty: float, price: float, stop_loss: float, take_profit: float):
    cost = qty * price
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO positions "
            "(ticker, qty, avg_price, stop_loss, take_profit, trailing_high, opened_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (ticker, qty, price, stop_loss, take_profit, price, datetime.utcnow().isoformat())
        )
        con.execute("UPDATE account SET cash = cash - ? WHERE id=1", (cost,))
        con.execute(
            "INSERT INTO trades (ticker, side, qty, price, pnl, reason, executed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (ticker, "BUY", qty, price, None, "signal", datetime.utcnow().isoformat())
        )
        con.commit()


def update_trailing_high(ticker: str, price: float):
    """Actualiza el máximo histórico de la posición si el precio actual es mayor."""
    with _conn() as con:
        con.execute(
            "UPDATE positions "
            "SET trailing_high = MAX(COALESCE(trailing_high, avg_price), ?) "
            "WHERE ticker=?",
            (price, ticker)
        )
        con.commit()


def close_position(ticker: str, price: float, reason: str = "signal") -> float:
    pos = get_position(ticker)
    if not pos:
        return 0.0
    pnl = (price - pos["avg_price"]) * pos["qty"]
    proceeds = price * pos["qty"]
    with _conn() as con:
        con.execute("DELETE FROM positions WHERE ticker=?", (ticker,))
        con.execute("UPDATE account SET cash = cash + ? WHERE id=1", (proceeds,))
        con.execute(
            "INSERT INTO trades (ticker, side, qty, price, pnl, reason, executed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (ticker, "SELL", pos["qty"], price, pnl, reason, datetime.utcnow().isoformat())
        )
        con.commit()
    return pnl


# ── Cooldown ─────────────────────────────────────────────────────────────────

def set_cooldown(ticker: str, reason: str = "stop_loss"):
    """Bloquea un ticker para re-entrada durante COOLDOWN_HOURS horas."""
    asset_class = get_asset_class(ticker)
    hours = COOLDOWN_HOURS.get(asset_class, 4)
    blocked_until = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO cooldowns (ticker, blocked_until, reason) VALUES (?,?,?)",
            (ticker, blocked_until, reason)
        )
        con.commit()


def is_in_cooldown(ticker: str) -> bool:
    """Retorna True si el ticker aún está en período de cooldown."""
    with _conn() as con:
        row = con.execute(
            "SELECT blocked_until FROM cooldowns WHERE ticker=?", (ticker,)
        ).fetchone()
    if not row:
        return False
    return datetime.utcnow().isoformat() < row[0]


def get_active_cooldowns() -> list[dict]:
    """Lista de tickers actualmente en cooldown (para el dashboard)."""
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        rows = con.execute(
            "SELECT ticker, blocked_until, reason FROM cooldowns WHERE blocked_until > ?",
            (now,)
        ).fetchall()
    return [{"ticker": r[0], "blocked_until": r[1], "reason": r[2]} for r in rows]


# ── Resto ─────────────────────────────────────────────────────────────────────

def get_equity(current_prices: dict[str, float]) -> float:
    cash = get_cash()
    positions_value = sum(
        p["qty"] * current_prices.get(p["ticker"], p["avg_price"])
        for p in get_positions()
    )
    return cash + positions_value


def save_daily_snapshot(equity: float, daily_pnl: float):
    positions = get_positions()
    cash = get_cash()
    with _conn() as con:
        con.execute(
            "INSERT INTO daily_snapshots (date, equity, cash, open_positions, daily_pnl) "
            "VALUES (?,?,?,?,?)",
            (datetime.utcnow().date().isoformat(), equity, cash, len(positions), daily_pnl)
        )
        con.commit()


def get_trade_history(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT ticker, side, qty, price, pnl, reason, executed_at "
            "FROM trades ORDER BY executed_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [{"ticker": r[0], "side": r[1], "qty": r[2], "price": r[3],
             "pnl": r[4], "reason": r[5], "executed_at": r[6]} for r in rows]


def get_initial_capital_usd() -> float:
    with _conn() as con:
        row = con.execute("SELECT initial_capital FROM account WHERE id=1").fetchone()
        return row[0] if row else INITIAL_CAPITAL


def get_stats() -> dict:
    with _conn() as con:
        initial = con.execute("SELECT initial_capital FROM account WHERE id=1").fetchone()[0]
        trades  = con.execute(
            "SELECT pnl FROM trades WHERE side='SELL' AND pnl IS NOT NULL"
        ).fetchall()
    pnls   = [t[0] for t in trades]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {
        "initial_capital": initial,
        "total_trades":    len(pnls),
        "win_rate":        len(wins) / len(pnls) if pnls else 0,
        "total_pnl":       sum(pnls),
        "avg_win":         sum(wins) / len(wins) if wins else 0,
        "avg_loss":        sum(losses) / len(losses) if losses else 0,
    }
