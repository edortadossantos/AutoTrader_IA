"""
Estrategia combinada: pondera señales técnicas + noticias + señales pro +
opciones + mercados de predicción + señales macro.

Pesos base (sin señales pro):
  Técnico      65%  — RSI, MACD crossover, Bollinger, SMA + daily trend + volumen + ADX
  Noticias     25%  — Sentimiento de 500+ artículos de fuentes premium
  Mercado      10%  — Sentimiento general del mercado (índice global)

Con todas las señales (modo completo):
  Técnico           28%
  Pro signals       22%  — Analyst consensus, Earnings surprise, Insider buying
  Noticias          12%
  Mercado            8%
  Opciones           8%
  Prediction Mkt    12%  — Polymarket + Kalshi (mercados de predicción con capital real)
  Macro signals     10%  — CNN F&G, FRED yield curve/VIX, COT, Put/Call, AAII

Mejoras v4 — Fuentes de datos profesionales completas:
  - Mercados de predicción (Polymarket + Kalshi): probabilidades de eventos
    macro con dinero real en juego — más predictivos que encuestas
  - Señales macro compuestas: CNN Fear&Greed, FRED (curva tipos, VIX),
    COT institucional (CFTC), Put/Call ratio, encuesta AAII
  - Catalizador de noticias: noticia ticker > ±0.40 reduce el umbral 30%
  - Señales SELL generan SHORT además de cerrar LONG
  - Crypto usa F&G como señal contraria en pánico extremo
  - Block duro si earnings_risk == HIGH (no entrar antes de resultados)
"""
from strategies.base_strategy import BaseStrategy
from config import MIN_SIGNAL_SCORE, CRYPTO

# Sentimiento de mercado por debajo de este umbral → penalizar stocks (no bloquear)
_STOCK_SENTIMENT_VETO = -0.20

# Si la noticia ticker supera este umbral en magnitud → catalizador fuerte
_NEWS_CATALYST_THRESHOLD = 0.38


class CombinedStrategy(BaseStrategy):
    name = "combined"

    # Pesos modo completo (todas las fuentes disponibles)
    W_TECHNICAL   = 0.28
    W_PRO         = 0.22
    W_NEWS        = 0.12
    W_MARKET      = 0.08
    W_OPTIONS     = 0.08
    W_PREDICTION  = 0.12   # Polymarket + Kalshi
    W_MACRO       = 0.10   # CNN F&G + FRED + COT + PCR + AAII

    def generate_signal(
        self,
        technical: dict,
        news: dict,
        market_sentiment: float,
        pro_signal: dict | None = None,
        min_score: float | None = None,
        options_score: float = 0.0,
        prediction_score: float = 0.0,
        macro_score: float = 0.0,
    ) -> dict:
        tech_score = technical.get("score", 0.0)
        news_score = news.get("news_score", 0.0)
        mkt_score  = market_sentiment
        pro_score  = pro_signal.get("pro_score", 0.0) if pro_signal else 0.0
        opt_score  = options_score
        pred_score = prediction_score   # mercados de predicción
        mac_score  = macro_score        # señales macro
        ticker     = technical.get("ticker", "")

        earnings_risk = (pro_signal or {}).get("earnings_risk", {}).get("risk", "LOW")
        macro_risk    = (pro_signal or {}).get("macro_risk", {}).get("risk", "LOW")

        threshold = min_score if min_score is not None else MIN_SIGNAL_SCORE

        # ── BLOCK DURO: no entrar antes de earnings (alta incertidumbre) ─
        if earnings_risk == "HIGH":
            return {
                "action":         "HOLD",
                "confidence":     0.0,
                "combined_score": 0.0,
                "reason":         "BLOQUEADO: earnings_risk=HIGH — no entrar antes de resultados",
                "earnings_risk":  earnings_risk,
                "macro_risk":     macro_risk,
            }

        is_crypto = ticker in CRYPTO

        # ── Catalizador de noticias: umbral reducido ante eventos concretos ─
        # Si hay una noticia ticker muy positiva/negativa (upgrade, earnings beat,
        # merger, FDA approval…) reducimos el umbral para entrar más rápido.
        news_catalyst = abs(news_score) >= _NEWS_CATALYST_THRESHOLD and not is_crypto
        if news_catalyst:
            # Reducción proporcional: cuanto más fuerte la noticia, más bajo el umbral
            catalyst_reduction = min(0.35, (abs(news_score) - _NEWS_CATALYST_THRESHOLD) * 1.5 + 0.20)
            threshold = threshold * (1.0 - catalyst_reduction)

        # ── Veto de sentimiento de mercado (solo stocks) ─────────────────
        if not is_crypto and mkt_score < _STOCK_SENTIMENT_VETO:
            tech_score = tech_score * 0.6   # penalizar, no bloquear

        # ── Ajuste FNG para crypto ────────────────────────────────────────
        crypto_fng_score = mkt_score
        if is_crypto and mkt_score < -0.65:
            # Pánico extremo FNG: señal contraria — neutralizar penalización
            crypto_fng_score = 0.0

        # ── Cálculo del score combinado ───────────────────────────────────
        has_pro      = pro_signal is not None
        has_options  = opt_score != 0.0
        has_pred     = pred_score != 0.0
        has_macro    = mac_score  != 0.0

        if is_crypto:
            # Crypto: técnico + news + F&G + predicción macro
            combined = (
                tech_score      * 0.60
                + news_score    * 0.15
                + crypto_fng_score * 0.10
                + pred_score    * 0.10
                + mac_score     * 0.05
            )

        elif has_pro and has_options and has_pred and has_macro:
            # Modo completo — todas las fuentes disponibles
            combined = (
                tech_score * self.W_TECHNICAL
                + pro_score  * self.W_PRO
                + news_score * self.W_NEWS
                + mkt_score  * self.W_MARKET
                + opt_score  * self.W_OPTIONS
                + pred_score * self.W_PREDICTION
                + mac_score  * self.W_MACRO
            )
        elif has_pro and has_options:
            # Sin mercados de predicción/macro
            combined = (
                tech_score * self.W_TECHNICAL
                + pro_score  * self.W_PRO
                + news_score * self.W_NEWS
                + mkt_score  * self.W_MARKET
                + opt_score  * self.W_OPTIONS
            )
        elif has_pro:
            # Sin opciones — redistribuir peso opciones
            combined = (
                tech_score * self.W_TECHNICAL
                + pro_score  * (self.W_PRO + self.W_OPTIONS * 0.5)
                + news_score * self.W_NEWS
                + mkt_score  * (self.W_MARKET + self.W_OPTIONS * 0.5)
            )
            if has_pred:
                combined = combined * 0.88 + pred_score * self.W_PREDICTION
            if has_macro:
                combined = combined * 0.90 + mac_score  * self.W_MACRO
        elif has_options:
            combined = (
                tech_score * 0.55
                + news_score * 0.20
                + mkt_score  * 0.10
                + opt_score  * 0.15
            )
        else:
            combined = tech_score * 0.65 + news_score * 0.25 + mkt_score * 0.10
            if has_pred:
                combined = combined * 0.88 + pred_score * 0.12
            if has_macro:
                combined = combined * 0.90 + mac_score  * 0.10

        confidence = abs(combined)
        sig_names  = [s[0] for s in technical.get("signals", [])]

        daily_info = (
            f" | daily={technical.get('daily_trend','?')}"
            f" ADX={technical.get('adx', 0):.0f}"
            f" sma200={technical.get('daily_sma200', 0):+.1f}%"
        )

        opt_detail  = f" | opciones={opt_score:+.3f}" if opt_score != 0.0 else ""
        pred_detail = f" | pred_mkt={pred_score:+.3f}" if pred_score != 0.0 else ""
        mac_detail  = f" | macro={mac_score:+.3f}" if mac_score != 0.0 else ""
        cat_detail  = f" | CATALIZADOR_NOTICIAS(umbral→{threshold:.3f})" if news_catalyst else ""

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

        base_reason = (
            f"Score={combined:.3f} "
            f"(técnico={tech_score:.3f} noticias={news_score:.3f} mercado={mkt_score:.3f})"
            f"{daily_info}{opt_detail}{pred_detail}{mac_detail}{cat_detail}{pro_detail}"
            f" | Señales: {', '.join(sig_names)}"
        )

        if combined > threshold:
            action = "BUY"
            reason = base_reason
        elif combined < -threshold:
            action = "SELL"   # SHORT o cierre de LONG
            reason = base_reason
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
            "news_catalyst":  news_catalyst,
        }
