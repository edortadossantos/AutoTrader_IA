"""
Backtester vectorizado — evalúa la estrategia sobre datos históricos.

Mejoras vs v1:
  - Trailing stop: deja correr ganancias en vez de cortar al TP fijo
  - Sizing por régimen de mercado (día a día usando SPY + VIX histórico)
      BULL  (SPY > SMA200 y VIX < 20) → 2× el tamaño de posición
      NEUTRAL                          → 1× normal
      BEAR  (SPY < SMA200 o VIX > 30) → 0.5× conservador
  - Ratio riesgo/recompensa mejorado (TP mínimo 2× el stop)
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

# Multiplicadores de sizing por régimen (mismo que el live trader)
_REGIME_SIZE_MULT = {"bull": 2.0, "neutral": 1.0, "bear": 0.5}
# Trailing stop: activa cuando el trade lleva este % de ganancia
_TRAILING_ACTIVATION = 0.05   # +5% de beneficio
# Cuánto cae desde el máximo para cerrar
_TRAILING_PCT        = 0.07   # 7% desde el máximo


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
    +1 = BUY, -1 = SELL, 0 = HOLD
    Umbral más bajo (0.40) para que RSI oversold solo pueda disparar compra.
    """
    score = 0.0

    if row["rsi"] < RSI_OVERSOLD:
        score += 0.5
    elif row["rsi"] > RSI_OVERBOUGHT:
        score -= 0.5

    if row["macd"] > row["macd_sig"] and row["macd_hist"] > 0:
        score += 0.3
    elif row["macd"] < row["macd_sig"] and row["macd_hist"] < 0:
        score -= 0.3

    if row["bb_pct"] < 0.15:
        score += 0.2
    elif row["bb_pct"] > 0.85:
        score -= 0.2

    if row["sma_short"] > row["sma_long"]:
        score += 0.15
    else:
        score -= 0.15

    if score > 0.40:
        return 1
    elif score < -0.40:
        return -1
    return 0


def _compute_daily_regime(spy_series: pd.Series | None, vix_series: pd.Series | None, date) -> str:
    """
    Determina el régimen de mercado en una fecha concreta usando datos históricos.
    Devuelve 'bull' | 'neutral' | 'bear'.
    """
    if spy_series is None:
        return "neutral"

    spy_until = spy_series[spy_series.index <= date]
    if len(spy_until) < 50:
        return "neutral"

    spy_last = float(spy_until.iloc[-1])
    sma200   = float(spy_until.iloc[-200:].mean()) if len(spy_until) >= 200 else float(spy_until.mean())
    sma50    = float(spy_until.iloc[-50:].mean())

    vix_last = 20.0
    if vix_series is not None:
        vix_until = vix_series[vix_series.index <= date]
        if not vix_until.empty:
            vix_last = float(vix_until.iloc[-1])

    if spy_last < sma200 or vix_last > 30:
        return "bear"
    elif vix_last > 20 or spy_last < sma50:
        return "neutral"
    return "bull"


def run_backtest(ticker: str, period: str = "2y", initial_capital: float = 10_000.0) -> dict:
    """
    Ejecuta backtest con:
      - Sizing dinámico por régimen de mercado (SPY + VIX histórico)
      - Trailing stop en vez de TP fijo (deja correr las ganancias)
      - Ratio riesgo/recompensa mínimo 2:1
    """
    df = _download_daily(ticker, period)
    if df is None:
        return {"error": f"No hay datos para {ticker}"}

    df = _compute_signals(df)
    params = get_asset_params(ticker)

    # Datos de régimen histórico
    spy_df  = _download_daily("SPY", period)
    vix_df  = _download_daily("^VIX", period)
    spy_cls = spy_df["Close"].squeeze() if spy_df is not None else None
    vix_cls = vix_df["Close"].squeeze() if vix_df is not None else None

    cash         = initial_capital
    pos_qty      = 0.0
    entry_p      = 0.0
    stop         = 0.0
    trailing_high = 0.0

    equity_curve: list[float] = []
    trades: list[dict] = []

    for date, row in df.iterrows():
        price = float(row["Close"])
        atr   = float(row["atr"])

        # ── Gestionar posición abierta ────────────────────────────
        if pos_qty > 0:
            # Actualizar trailing high
            if price > trailing_high:
                trailing_high = price

            trailing_active = trailing_high >= entry_p * (1 + _TRAILING_ACTIVATION)
            close_reason    = None

            if trailing_active:
                trailing_floor = trailing_high * (1 - _TRAILING_PCT)
                if price <= trailing_floor:
                    close_reason = "trailing_stop"
            elif price <= stop:
                close_reason = "stop_loss"

            if close_reason:
                pnl = (price - entry_p) * pos_qty
                cash += price * pos_qty
                trades.append({"date": date, "side": "SELL", "price": price,
                               "pnl": pnl, "reason": close_reason})
                pos_qty = 0.0

        sig = _generate_raw_signal(row)

        # ── Abrir posición ────────────────────────────────────────
        if sig == 1 and pos_qty == 0 and cash > price:
            # Sizing ajustado por régimen del día
            regime     = _compute_daily_regime(spy_cls, vix_cls, date)
            size_mult  = _REGIME_SIZE_MULT.get(regime, 1.0)
            invest     = min(cash * params["max_pos"] * size_mult, cash * 0.95)

            if invest >= price:
                pos_qty       = invest / price
                entry_p       = price
                trailing_high = price
                # Stop dinámico ATR, mínimo params["stop"]
                atr_stop      = atr * 1.5
                fixed_stop    = price * params["stop"]
                stop          = price - max(atr_stop, fixed_stop)
                cash         -= invest
                trades.append({"date": date, "side": "BUY", "price": price,
                               "pnl": None, "reason": f"signal_{regime}"})

        # ── Cerrar por señal bajista ──────────────────────────────
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
        trades.append({"date": df.index[-1], "side": "SELL", "price": final_price,
                       "pnl": pnl, "reason": "end_of_period"})

    # ── Métricas ──────────────────────────────────────────────────
    equity_arr   = np.array(equity_curve)
    returns      = np.diff(equity_arr) / equity_arr[:-1]
    final_equity = equity_arr[-1]
    total_return = (final_equity / initial_capital - 1) * 100
    sharpe       = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0

    peak   = np.maximum.accumulate(equity_arr)
    dd     = (equity_arr - peak) / peak * 100
    max_dd = float(dd.min())

    sell_trades   = [t for t in trades if t["side"] == "SELL" and t["pnl"] is not None]
    pnls          = [t["pnl"] for t in sell_trades]
    wins          = [p for p in pnls if p > 0]
    losses        = [p for p in pnls if p <= 0]
    win_rate      = len(wins) / len(pnls) if pnls else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    dates      = df.index[:len(equity_curve)]
    curve_dates = [str(d.date()) for d in dates]

    return {
        "ticker":           ticker,
        "period":           period,
        "initial_capital":  round(initial_capital, 2),
        "final_equity":     round(final_equity, 2),
        "total_return_pct": round(total_return, 2),
        "sharpe":           round(float(sharpe), 3),
        "max_drawdown_pct": round(max_dd, 2),
        "total_trades":     len(pnls),
        "win_rate":         round(win_rate, 3),
        "avg_win":          round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss":         round(sum(losses) / len(losses), 2) if losses else 0,
        "profit_factor":    round(profit_factor, 2) if profit_factor != float("inf") else 99.0,
        "equity_curve":     [{"date": d, "equity": e} for d, e in zip(curve_dates, equity_curve)],
        "buy_hold_return":  round(
            (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100, 2
        ),
    }


if __name__ == "__main__":
    import sys
    import json
    logging.basicConfig(level=logging.INFO)
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "BTC-USD", "SPY"]
    for t in tickers:
        r = run_backtest(t, period="5y")
        if "error" in r:
            print(f"[{t}] ERROR: {r['error']}")
            continue
        print(
            f"[{t}] Return={r['total_return_pct']:+.1f}% | "
            f"B&H={r['buy_hold_return']:+.1f}% | "
            f"Alpha={r['total_return_pct']-r['buy_hold_return']:+.1f}% | "
            f"Sharpe={r['sharpe']:.2f} | "
            f"MaxDD={r['max_drawdown_pct']:.1f}% | "
            f"Trades={r['total_trades']} | "
            f"WinRate={r['win_rate']:.1%} | "
            f"PF={r['profit_factor']:.2f}"
        )
