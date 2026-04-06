"""
Estrategia combinada: pondera señales técnicas + noticias + señales profesionales + opciones.

Pesos (con opciones disponibles):
  Técnico         35%  — RSI, MACD, Bollinger, SMA
  Pro signals     30%  — Analyst consensus, Earnings surprise, Insider buying
  Noticias RSS    15%  — Sentimiento de 150+ artículos de fuentes premium
  Macro mercado   10%  — Sentimiento general del mercado
  Opciones flow   10%  — Flujo inusual de calls/puts (smart money)

Las señales pro son las que usan fondos e institucionales.
Si hay riesgo de earnings o evento macro → señal atenuada automáticamente.
"""
from strategies.base_strategy import BaseStrategy
from config import MIN_SIGNAL_SCORE


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

        # Si hay riesgo alto por earnings o macro, señal pro ya viene atenuada
        earnings_risk = (pro_signal or {}).get("earnings_risk", {}).get("risk", "LOW")
        macro_risk    = (pro_signal or {}).get("macro_risk", {}).get("risk", "LOW")

        if pro_signal and opt_score != 0.0:
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
            # Sin pro pero con opciones
            combined = (
                tech_score * 0.55
                + news_score * 0.20
                + mkt_score  * 0.10
                + opt_score  * 0.15
            )
        else:
            # Sin señales pro ni opciones, redistribuir pesos
            combined = tech_score * 0.65 + news_score * 0.25 + mkt_score * 0.10

        confidence = abs(combined)
        sig_names  = [s[0] for s in technical.get("signals", [])]

        # Contexto opciones para el log
        opt_detail = f" | opciones={opt_score:+.3f}" if opt_score != 0.0 else ""

        # Contexto pro para el log
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

        threshold = min_score if min_score is not None else MIN_SIGNAL_SCORE

        if combined > threshold:
            action = "BUY"
            reason = (
                f"Score={combined:.3f} "
                f"(técnico={tech_score:.3f} noticias={news_score:.3f} mercado={mkt_score:.3f})"
                f"{opt_detail}{pro_detail} | Señales: {', '.join(sig_names)}"
            )
        elif combined < -threshold:
            action = "SELL"
            reason = (
                f"Score={combined:.3f} "
                f"(técnico={tech_score:.3f} noticias={news_score:.3f} mercado={mkt_score:.3f})"
                f"{opt_detail}{pro_detail} | Señales: {', '.join(sig_names)}"
            )
        else:
            action = "HOLD"
            reason = f"Score insuficiente: {combined:.3f} (umbral ±{threshold}){pro_detail}"

        return {
            "action":         action,
            "confidence":     round(confidence, 4),
            "combined_score": round(combined, 4),
            "reason":         reason,
            "earnings_risk":  earnings_risk,
            "macro_risk":     macro_risk,
        }
