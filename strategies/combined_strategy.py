"""
Estrategia combinada: pondera señales técnicas + noticias + señales profesionales + opciones.

Pesos base (sin señales pro):
  Técnico      65%  — RSI, MACD crossover, Bollinger, SMA + daily trend + volumen + ADX
  Noticias     25%  — Sentimiento de 500+ artículos de fuentes premium
  Mercado      10%  — Sentimiento general del mercado (índice global)

Con señales pro (Finnhub):
  Técnico      35%
  Pro signals  30%  — Analyst consensus, Earnings surprise, Insider buying
  Noticias     15%
  Mercado      10%
  Opciones     10%

Mejoras v2:
  - Block duro si earnings_risk == HIGH (no comprar antes de resultados)
  - Veto de sentimiento: mercado muy negativo bloquea stocks (no crypto)
  - Crypto usa solo técnico + noticias (pro signals son stock-oriented)
  - Asset-class aware: detecta si el ticker es crypto para ajustar pesos
"""
from strategies.base_strategy import BaseStrategy
from config import MIN_SIGNAL_SCORE, CRYPTO


# Sentimiento de mercado por debajo de este umbral → no comprar stocks
_STOCK_SENTIMENT_VETO = -0.15


class CombinedStrategy(BaseStrategy):
    name = "combined"

    W_TECHNICAL = 0.35
    W_PRO       = 0.30
    W_NEWS      = 0.15
    W_MARKET    = 0.10
    W_OPTIONS   = 0.10

    def generate_signal(
        self,
        technical: dict,
        news: dict,
        market_sentiment: float,
        pro_signal: dict | None = None,
        min_score: float | None = None,
        options_score: float = 0.0,
    ) -> dict:
        tech_score = technical.get("score", 0.0)
        news_score = news.get("news_score", 0.0)
        mkt_score  = market_sentiment
        pro_score  = pro_signal.get("pro_score", 0.0) if pro_signal else 0.0
        opt_score  = options_score
        ticker     = technical.get("ticker", "")

        earnings_risk = (pro_signal or {}).get("earnings_risk", {}).get("risk", "LOW")
        macro_risk    = (pro_signal or {}).get("macro_risk", {}).get("risk", "LOW")

        threshold = min_score if min_score is not None else MIN_SIGNAL_SCORE

        # ── BLOCK DURO: no comprar antes de earnings ──────────────────
        if earnings_risk == "HIGH":
            return {
                "action":         "HOLD",
                "confidence":     0.0,
                "combined_score": 0.0,
                "reason":         f"BLOQUEADO: earnings_risk=HIGH — no entrar antes de resultados",
                "earnings_risk":  earnings_risk,
                "macro_risk":     macro_risk,
            }

        is_crypto = ticker in CRYPTO

        # ── Veto de sentimiento de mercado (solo stocks) ──────────────
        # Si el mercado está en pánico, no comprar acciones aunque la señal técnica
        # sea alcista. Crypto tiene su propia dinámica y no aplica este veto.
        if not is_crypto and mkt_score < _STOCK_SENTIMENT_VETO:
            # Penalizar el score técnico en entornos de pánico macro
            tech_score = tech_score * 0.5

        # ── Cálculo del score combinado ───────────────────────────────

        if is_crypto:
            # Crypto: sin señales pro ni opciones útiles (son stock-oriented)
            # Más peso técnico + noticias especializadas
            combined = tech_score * 0.70 + news_score * 0.20 + mkt_score * 0.10

        elif pro_signal and opt_score != 0.0:
            combined = (
                tech_score * self.W_TECHNICAL
                + pro_score  * self.W_PRO
                + news_score * self.W_NEWS
                + mkt_score  * self.W_MARKET
                + opt_score  * self.W_OPTIONS
            )
        elif pro_signal:
            combined = (
                tech_score * self.W_TECHNICAL
                + pro_score  * (self.W_PRO + self.W_OPTIONS * 0.5)
                + news_score * self.W_NEWS
                + mkt_score  * (self.W_MARKET + self.W_OPTIONS * 0.5)
            )
        elif opt_score != 0.0:
            combined = (
                tech_score * 0.55
                + news_score * 0.20
                + mkt_score  * 0.10
                + opt_score  * 0.15
            )
        else:
            combined = tech_score * 0.65 + news_score * 0.25 + mkt_score * 0.10

        confidence = abs(combined)
        sig_names  = [s[0] for s in technical.get("signals", [])]

        # Info de daily trend y ADX para el log
        daily_info = (
            f" | daily={technical.get('daily_trend','?')}"
            f" ADX={technical.get('adx', 0):.0f}"
            f" sma200={technical.get('daily_sma200', 0):+.1f}%"
        )

        opt_detail = f" | opciones={opt_score:+.3f}" if opt_score != 0.0 else ""

        pro_detail = ""
        if pro_signal:
            analyst_chg = pro_signal.get("analyst", {}).get("recent_changes", [])
            chg_str = f" | Cambios analistas: {analyst_chg}" if analyst_chg else ""
            pro_detail = (
                f" | pro_score={pro_score:.3f}"
                f" [analyst={pro_signal.get('analyst',{}).get('signal',0):.2f}"
                f" earn={pro_signal.get('earnings',{}).get('signal',0):.2f}"
                f" insider={pro_signal.get('insider',{}).get('signal',0):.2f}]"
                f"{chg_str}"
            )
            if earnings_risk != "LOW":
                pro_detail += f" ⚠ EARNINGS_RISK={earnings_risk}"
            if macro_risk != "LOW":
                pro_detail += f" ⚠ MACRO_RISK={macro_risk}"

        if combined > threshold:
            action = "BUY"
            reason = (
                f"Score={combined:.3f} "
                f"(técnico={tech_score:.3f} noticias={news_score:.3f} mercado={mkt_score:.3f})"
                f"{daily_info}{opt_detail}{pro_detail} | Señales: {', '.join(sig_names)}"
            )
        elif combined < -threshold:
            action = "SELL"
            reason = (
                f"Score={combined:.3f} "
                f"(técnico={tech_score:.3f} noticias={news_score:.3f} mercado={mkt_score:.3f})"
                f"{daily_info}{opt_detail}{pro_detail} | Señales: {', '.join(sig_names)}"
            )
        else:
            action = "HOLD"
            reason = (
                f"Score insuficiente: {combined:.3f} (umbral ±{threshold:.3f})"
                f"{daily_info}{pro_detail}"
            )

        return {
            "action":         action,
            "confidence":     round(confidence, 4),
            "combined_score": round(combined, 4),
            "reason":         reason,
            "earnings_risk":  earnings_risk,
            "macro_risk":     macro_risk,
        }
