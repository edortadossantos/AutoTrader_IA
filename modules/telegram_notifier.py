"""
Notificaciones Telegram en tiempo real.

Setup (5 min):
  1. Abre Telegram → busca @BotFather → /newbot → guarda el TOKEN
  2. Manda cualquier mensaje a tu nuevo bot
  3. Abre: https://api.telegram.org/bot<TOKEN>/getUpdates
     → busca "chat":{"id": XXXXXXX} → ese es tu CHAT_ID
  4. Añade a .env (crea el fichero si no existe):
       TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
       TELEGRAM_CHAT_ID=123456789

Sin configurar: el módulo funciona en modo silencioso (sin errores).
"""
import logging
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _send(text: str, silent: bool = False):
    """Envía mensaje al chat configurado. Silencia errores de red."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            _BASE.format(token=TELEGRAM_BOT_TOKEN),
            json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     text,
                "parse_mode":               "HTML",
                "disable_notification":     silent,
                "disable_web_page_preview": True,
            },
            timeout=6,
        )
    except Exception as e:
        logger.debug(f"Telegram send error: {e}")


# ── Eventos de trading ─────────────────────────────────────────────────────────

def notify_buy(
    ticker: str, qty: float, price: float,
    stop: float, tp: float,
    confidence: float, asset_class: str,
    regime: str = "",
):
    label = asset_class.upper()
    reg_str = f"\nRégimen: {regime.upper()}" if regime else ""
    _send(
        f"🟢 <b>COMPRA</b> [{label}] <b>{ticker}</b>\n"
        f"Precio: <code>${price:.4f}</code> × {qty:.4f} uds\n"
        f"🛑 Stop: <code>${stop:.4f}</code>  🎯 TP: <code>${tp:.4f}</code>\n"
        f"Confianza: {confidence:.1%}{reg_str}"
    )


def notify_sell(ticker: str, price: float, pnl: float, reason: str):
    if pnl > 0:
        emoji = "💰"
        pnl_str = f"+${pnl:.2f} ✅"
    else:
        emoji = "🔴"
        pnl_str = f"-${abs(pnl):.2f} ❌"
    _send(
        f"{emoji} <b>VENTA</b> <b>{ticker}</b>\n"
        f"Precio: <code>${price:.4f}</code>\n"
        f"PnL: <b>{pnl_str}</b>\n"
        f"Razón: <i>{reason}</i>"
    )


def notify_halt(reason: str):
    _send(
        f"🚨🚨 <b>CIRCUIT BREAKER ACTIVADO</b> 🚨🚨\n"
        f"<b>{reason}</b>\n"
        f"Todas las posiciones cerradas. Bot pausado."
    )


def notify_regime_change(old_regime: str, new_regime: str, detail: str):
    emojis = {"bull": "🟢", "neutral": "🟡", "bear": "🔴"}
    e_old = emojis.get(old_regime, "⚪")
    e_new = emojis.get(new_regime, "⚪")
    _send(
        f"📊 <b>Cambio de régimen</b>: {e_old} {old_regime.upper()} → {e_new} <b>{new_regime.upper()}</b>\n"
        f"{detail}"
    )


def notify_startup(equity: float, mode: str = "paper"):
    mode_str = "📄 PAPER TRADING" if mode == "paper" else "💵 LIVE"
    _send(
        f"🤖 <b>AutoTrader IA iniciado</b> — {mode_str}\n"
        f"Capital: <code>${equity:,.2f}</code>\n"
        f"Dashboard: http://localhost:5000",
        silent=True,
    )


def notify_options_alert(ticker: str, flow_type: str, score: float):
    """Alerta cuando se detecta flujo inusual de opciones."""
    emoji = "📈" if flow_type == "bullish" else "📉"
    _send(
        f"{emoji} <b>Flujo inusual de opciones</b>: <b>{ticker}</b>\n"
        f"Tipo: {flow_type.upper()} | Score: {score:.2f}\n"
        f"Alguien está apostando fuerte antes de una noticia."
    )


def notify_screener_candidates(candidates: list[dict]):
    """Resumen diario del screener cuando NYSE abre."""
    if not candidates:
        return
    lines = [f"🔍 <b>Screener: {len(candidates)} candidatos</b>"]
    for c in candidates[:5]:
        lines.append(
            f"  • <b>{c['ticker']}</b> — vol×{c.get('vol_ratio',0):.1f} "
            f"| score {c.get('score',0):.2f}"
        )
    _send("\n".join(lines), silent=True)
