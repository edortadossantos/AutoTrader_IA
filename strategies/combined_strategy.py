"""
Estrategia combinada: pondera señales técnicas + sentimiento de noticias.
"""
from strategies.base_strategy import BaseStrategy
from config import MIN_SIGNAL_SCORE


class CombinedStrategy(BaseStrategy):
    name = "combined"

    # Pesos de cada fuente de señal (deben sumar 1)
    W_TECHNICAL = 0.65
    W_NEWS = 0.25
    W_MARKET = 0.10

    def generate_signal(self, technical: dict, news: dict, market_sentiment: float) -> dict:
        tech_score = technical.get("score", 0.0)          # -1 a +1
        news_score = news.get("news_score", 0.0)           # -1 a +1
        mkt_score = market_sentiment                        # -1 a +1

        combined = (
            tech_score * self.W_TECHNICAL
            + news_score * self.W_NEWS
            + mkt_score * self.W_MARKET
        )
        confidence = abs(combined)

        # Contexto de las señales técnicas
        sig_names = [s[0] for s in technical.get("signals", [])]

        if combined > MIN_SIGNAL_SCORE:
            action = "BUY"
            reason = (
                f"Score combinado: {combined:.3f} "
                f"(técnico={tech_score:.3f}, noticias={news_score:.3f}, mercado={mkt_score:.3f}) | "
                f"Señales: {', '.join(sig_names)}"
            )
        elif combined < -MIN_SIGNAL_SCORE:
            action = "SELL"
            reason = (
                f"Score negativo: {combined:.3f} "
                f"(técnico={tech_score:.3f}, noticias={news_score:.3f}, mercado={mkt_score:.3f}) | "
                f"Señales: {', '.join(sig_names)}"
            )
        else:
            action = "HOLD"
            reason = f"Score insuficiente: {combined:.3f} (umbral ±{MIN_SIGNAL_SCORE})"

        return {
            "action": action,
            "confidence": round(confidence, 4),
            "combined_score": round(combined, 4),
            "reason": reason,
        }
