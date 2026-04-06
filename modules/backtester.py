"""
Backtester vectorizado — evalúa la estrategia sobre datos históricos.

Uso:
    from modules.backtester import run_backtest
    results = run_backtest("AAPL", period="1y")

    python -m modules.backtester AAPL MSFT BTC-USD

Métricas calculadas:
  - Total return, Sharpe ratio, Max drawdown
  - Win rate, avg win, avg loss, profit factor
  - Número de operaciones
"""
import logging
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, SMA_SHORT, SMA_LONG,
    get_asset_params,
)

logger = logging.getLogger(__name__)


def _download_daily(ticker: str, period: str = "2y") -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna()
    except Exception as e:
        logger.warning(f"Backtester download {ticker}: {e}")
        return None


def _compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula indicadores técnicos en datos diarios."""
    import ta
    close = df["Close"].squeeze()
    high  = df["High"].squeeze()
    low   = df["Low"].squeeze()

    df = df.copy()
    df["rsi"]        = ta.momentum.RSIIndicator(close, window=RSI_PERIOD).rsi()
    macd_obj         = ta.trend.MACD(close, window_slow=MACD_SLOW, window_fast=MACD_FAST, window_sign=MACD_SIGNAL)
    df["macd"]       = macd_obj.macd()
    df["macd_sig"]   = macd_obj.macd_signal()
    df["macd_hist"]  = macd_obj.macd_diff()
    bb               = ta.volatility.BollingerBands(close, window=BB_PERIOD, window_dev=BB_STD)
    df["bb_lower"]   = bb.bollinger_lband()
    df["bb_upper"]   = bb.bollinger_hband()
    df["bb_pct"]     = bb.bollinger_pband()
    df["sma_short"]  = ta.trend.SMAIndicator(close, window=SMA_SHORT).sma_indicator()
    df["sma_long"]   = ta.trend.SMAIndicator(close, window=SMA_LONG).sma_indicator()
    df["atr"]        = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    return df.dropna()


def _generate_raw_signal(row: pd.Series) -> int:
    """
    Señal simplificada (sin noticias/pro — solo técnico).
    +1 = BUY, -1 = SELL, 0 = HOLD
    Usa las mismas condiciones que combined_strategy pero sin pesos externos.
    """
    score = 0.0

    # RSI
    if row["rsi"] < RSI_OVERSOLD:
        score += 0.5
    elif row["rsi"] > RSI_OVERBOUGHT:
        score -= 0.5

    # MACD cruce
    if row["macd"] > row["macd_sig"] and row["macd_hist"] > 0:
        score += 0.3
    elif row["macd"] < row["macd_sig"] and row["macd_hist"] < 0:
        score -= 0.3

    # Bollinger
    if row["bb_pct"] < 0.15:
        score += 0.2
    elif row["bb_pct"] > 0.85:
        score -= 0.2

    # SMA cruce
    if row["sma_short"] > row["sma_long"]:
        score += 0.15
    else:
        score -= 0.15

    if score > 0.40:
        return 1
    elif score < -0.40:
        return -1
    return 0


def run_backtest(ticker: str, period: str = "2y", initial_capital: float = 10_000.0) -> dict:
    """
    Ejecuta backtest de la estrategia técnica sobre datos históricos diarios.

    Args:
        ticker:          Símbolo (AAPL, BTC-USD, etc.)
        period:          Período yfinance (1y, 2y, 5y)
        initial_capital: Capital inicial en USD

    Returns:
        dict con métricas y equity curve.
    """
    df = _download_daily(ticker, period)
    if df is None:
        return {"error": f"No hay datos para {ticker}"}

    df = _compute_signals(df)
    params = get_asset_params(ticker)

    # ── Simulación evento a evento ─────────────────────────────────
    cash    = initial_capital
    pos_qty = 0.0
    entry_p = 0.0
    stop    = 0.0
    tp_p    = 0.0

    equity_curve: list[float] = []
    trades: list[dict] = []

    closes = df["Close"].squeeze()
    dates  = df.index

    for i, (date, row) in enumerate(df.iterrows()):
        price = float(row["Close"])

        # Gestionar posición abierta
        if pos_qty > 0:
            # Stop-loss / take-profit
            if price <= stop:
                pnl = (price - entry_p) * pos_qty
                cash += price * pos_qty
                trades.append({"date": date, "side": "SELL", "price": price,
                               "pnl": pnl, "reason": "stop_loss"})
                pos_qty = 0.0
            elif price >= tp_p:
                pnl = (price - entry_p) * pos_qty
                cash += price * pos_qty
                trades.append({"date": date, "side": "SELL", "price": price,
                               "pnl": pnl, "reason": "take_profit"})
                pos_qty = 0.0

        sig = _generate_raw_signal(row)

        # Abrir posición
        if sig == 1 and pos_qty == 0 and cash > price:
            invest  = cash * params["max_pos"]
            pos_qty = invest / price
            entry_p = price
            stop    = price * (1 - params["stop"])
            tp_p    = price * (1 + params["tp"])
            cash   -= invest
            trades.append({"date": date, "side": "BUY", "price": price,
                           "pnl": None, "reason": "signal"})

        # Cerrar posición por señal bajista
        elif sig == -1 and pos_qty > 0:
            pnl = (price - entry_p) * pos_qty
            cash += price * pos_qty
            trades.append({"date": date, "side": "SELL", "price": price,
                           "pnl": pnl, "reason": "signal_sell"})
            pos_qty = 0.0

        equity_curve.append(round(cash + pos_qty * price, 2))

    # Cerrar posición final si queda abierta
    if pos_qty > 0:
        final_price = float(df["Close"].iloc[-1])
        pnl = (final_price - entry_p) * pos_qty
        cash += final_price * pos_qty
        trades.append({"date": dates[-1], "side": "SELL", "price": final_price,
                       "pnl": pnl, "reason": "end_of_period"})

    # ── Métricas ───────────────────────────────────────────────────
    equity_arr = np.array(equity_curve)
    returns    = np.diff(equity_arr) / equity_arr[:-1]

    final_equity   = equity_arr[-1]
    total_return   = (final_equity / initial_capital - 1) * 100
    sharpe         = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0

    # Drawdown máximo
    peak   = np.maximum.accumulate(equity_arr)
    dd     = (equity_arr - peak) / peak * 100
    max_dd = float(dd.min())

    # Win/loss stats
    sell_trades = [t for t in trades if t["side"] == "SELL" and t["pnl"] is not None]
    pnls        = [t["pnl"] for t in sell_trades]
    wins        = [p for p in pnls if p > 0]
    losses      = [p for p in pnls if p <= 0]
    win_rate    = len(wins) / len(pnls) if pnls else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    # Equity curve como lista de puntos para el dashboard
    curve_dates = [str(d.date()) for d in dates[:len(equity_curve)]]

    return {
        "ticker":          ticker,
        "period":          period,
        "initial_capital": round(initial_capital, 2),
        "final_equity":    round(final_equity, 2),
        "total_return_pct": round(total_return, 2),
        "sharpe":          round(float(sharpe), 3),
        "max_drawdown_pct": round(max_dd, 2),
        "total_trades":    len(pnls),
        "win_rate":        round(win_rate, 3),
        "avg_win":         round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss":        round(sum(losses) / len(losses), 2) if losses else 0,
        "profit_factor":   round(profit_factor, 2) if profit_factor != float("inf") else 99.0,
        "equity_curve":    [{"date": d, "equity": e} for d, e in zip(curve_dates, equity_curve)],
        "buy_hold_return": round(
            (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100, 2
        ),
    }


if __name__ == "__main__":
    import sys
    import json
    logging.basicConfig(level=logging.INFO)
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "BTC-USD"]
    for t in tickers:
        r = run_backtest(t)
        if "error" in r:
            print(f"[{t}] ERROR: {r['error']}")
            continue
        print(
            f"[{t}] Return={r['total_return_pct']:+.1f}% | "
            f"B&H={r['buy_hold_return']:+.1f}% | "
            f"Sharpe={r['sharpe']:.2f} | "
            f"MaxDD={r['max_drawdown_pct']:.1f}% | "
            f"Trades={r['total_trades']} | "
            f"WinRate={r['win_rate']:.1%} | "
            f"PF={r['profit_factor']:.2f}"
        )
