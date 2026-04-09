# AutoTrader IA

Bot de trading algorítmico multi-mercado que combina análisis técnico con las mismas fuentes de información que usan traders profesionales: mercados de predicción, datos del regulador, indicadores macro compuestos y flujo institucional de opciones.

Opera en modo **paper trading** (simulado, sin dinero real) sobre acciones US, ETFs, crypto y commodities. Envía alertas por Telegram y tiene dashboard web en tiempo real.

---

## Fuentes de datos integradas

### Datos de mercado
| Fuente | Datos | Plan |
|--------|-------|------|
| **yfinance** | OHLCV diario e intradiario (stocks, ETFs, crypto, futuros) | Gratuito |
| **Finnhub API** | Noticias por ticker, datos de mercado en tiempo real | Gratuito (60 req/min) |

### Mercados de predicción
Traders profesionales usan mercados de predicción para medir probabilidades de eventos macro con capital real en juego — más fiables que encuestas.

| Fuente | Por qué importa | Plan |
|--------|----------------|------|
| **[Polymarket](https://polymarket.com)** | Mayor mercado de predicción descentralizado del mundo. +$500M de liquidez. Probabilidades de: bajada tipos Fed, recesión, rendimiento S&P, resultados electorales. API pública sin auth. | Gratuito |
| **[Kalshi](https://kalshi.com)** | Único exchange de predicción regulado por la CFTC en EEUU. Especializado en eventos macro financieros: tipos Fed, CPI, NFP, recesión. Regulación federal garantiza integridad. | Gratuito (lectura) |

### Señales profesionales (Finnhub)
| Señal | Por qué importa |
|-------|----------------|
| **Insider Transactions (Form 4 SEC)** | Los directivos compran por una sola razón: creen que el precio va a subir |
| **Analyst Consensus + Upgrades** | Un upgrade de Goldman/Morgan Stanley mueve el precio 3-8% en sesión |
| **Earnings Surprise (últimos 4Q)** | Empresas que baten consistentemente tienen momentum comprador sostenido |
| **Economic Calendar** | Bloquea operaciones antes de FOMC/CPI/NFP (volatilidad extrema) |

### Señales macro (traders profesionales)
| Fuente | Datos | Por qué importa |
|--------|-------|----------------|
| **[CNN Fear & Greed Index](https://money.cnn.com/data/fear-and-greed/)** | Compuesto de 7 indicadores: momentum, amplitud, put/call, VIX, junk bonds, safe haven, market momentum | Indicador contrario: miedo extremo = oportunidad de compra; codicia extrema = señal de venta |
| **[Crypto Fear & Greed (Alternative.me)](https://alternative.me/crypto/fear-and-greed-index/)** | Volatilidad BTC, momentum, social media, dominancia BTC, tendencias Google | Más preciso que el CNN para crypto |
| **[FRED API (Federal Reserve)](https://fred.stlouisfed.org)** | Curva de tipos 10Y-2Y (T10Y2Y), VIX (VIXCLS) | Curva invertida predice recesión 12-18 meses. VIX >30 = pánico = oportunidad contraria |
| **[CFTC COT Report](https://www.cftc.gov/MarketReports/CommitmentsofTraders)** | Posicionamiento semanal de hedge funds y CTA en futuros (S&P, NASDAQ, oro, petróleo, bonos, BTC) | Los fondos no pueden mentirle al regulador — es el dato más honesto del mercado |
| **[Put/Call Ratio (CBOE)](https://www.cboe.com/data/historical-options-data/)** | Ratio puts/calls del mercado de opciones US | Contrario: ratio >1.2 = pesimismo extremo → precede rebotes; <0.7 = complacencia → precede correcciones |
| **[AAII Sentiment Survey](https://www.aaii.com/sentimentsurvey)** | Encuesta semanal inversores minoristas desde 1987 | Indicador contrario clásico: bears extremos >50% históricamente preceden rebotes de +15-20% |

### Noticias y sentimiento
| Fuente | Datos |
|--------|-------|
| **35+ feeds RSS** | Reuters, CNBC, MarketWatch, Benzinga, Barron's, Seeking Alpha, AP, SEC EDGAR, Federal Reserve, US Treasury, CoinDesk, CoinTelegraph, OilPrice, Kitco, Unusual Whales... |
| **Alpha Vantage** | Sentimiento por ticker con score cuantitativo |
| **NewsAPI** | Búsqueda de noticias financieras |
| **Reddit PRAW** | r/wallstreetbets, r/investing, r/stocks — detecta momentum retail |

### Flujo de opciones (actividad inusual)
| Fuente | Datos |
|--------|-------|
| **Barchart Unusual Options** | Detección de volumen inusual de calls/puts — señal de información privilegiada o posicionamiento institucional |
| **Finviz Options Scanner** | Scanner alternativo de opciones inusuales |

---

## Arquitectura de señales

```
                    ┌─────────────────────────────────┐
                    │        CombinedStrategy          │
                    │                                 │
  Técnico    28%    │  RSI, MACD, BB, SMA, ADX, Vol  │
  Pro        22%    │  Insiders + Analyst + Earnings  │
  Noticias   12%    │  35+ RSS + Finnhub + Reddit     │
  Pred. Mkt  12%    │  Polymarket + Kalshi            │
  Macro      10%    │  FRED + CNN F&G + COT + PCR     │
  Mercado     8%    │  Sentimiento índice S&P         │
  Opciones    8%    │  Barchart unusual flow          │
                    └─────────────┬───────────────────┘
                                  │
                    ┌─────────────▼───────────────────┐
                    │         Risk Manager             │
                    │  Position sizing + Stop/TP      │
                    │  Circuit breakers + Cooldowns    │
                    └─────────────┬───────────────────┘
                                  │
                    ┌─────────────▼───────────────────┐
                    │         Portfolio + DB           │
                    │  SQLite + Telegram + Dashboard   │
                    └─────────────────────────────────┘
```

---

## Universo de activos

| Clase | Activos |
|-------|---------|
| **US Tech** | AAPL, MSFT, GOOGL, NVDA, META, AMZN, TSLA, AMD, NFLX, ORCL |
| **US Financials** | JPM, BAC, GS, BRK-B |
| **US Energy** | XOM, CVX |
| **US Health** | JNJ, UNH |
| **US Consumer** | WMT, HD |
| **ETFs** | SPY, QQQ, IWM + sectoriales + GLD, SLV, USO, TLT |
| **ETFs inversos** | SH, PSQ, SDS, SQQQ (posición larga en mercados bajistas) |
| **Crypto** | BTC, ETH, SOL, BNB, XRP, AVAX, LINK |
| **Commodities** | Oro (GC=F), Petróleo WTI (CL=F), Plata (SI=F) |
| **Internacional** | EFA (mercados desarrollados), EEM (emergentes) |

---

## Gestión de riesgo

- **Sizing dinámico** por clase de activo (crypto 5%, ETF 12%, stocks 10%)
- **Stop-loss** adaptado por clase (crypto 8%, stocks 5%, commodities 4%)
- **Trailing stop** activado tras +3% de beneficio
- **Circuit breakers**: reducción exposición al -20% drawdown, halt al -50%
- **Límite pérdida diaria**: -5% del capital
- **Cooldown tras stop**: 2-6h según clase de activo
- **Bloqueo earnings**: no entrar en los 2 días previos a resultados
- **Límite concentración**: máx 2 posiciones por sector simultáneamente
- **Exposición máxima**: crypto 25%, commodities 15%, internacional 15%

---

## Instalación

```bash
git clone https://github.com/tu-usuario/AutoTrader_IA.git
cd AutoTrader_IA
pip install -r requirements.txt
cp .env.example .env
# Editar .env con tus claves API
python main.py
```

### Variables de entorno

```env
# Obligatorio para señales pro
FINNHUB_API_KEY=tu_clave          # https://finnhub.io (gratuito)

# Para señales macro FRED
FRED_API_KEY=tu_clave             # https://fred.stlouisfed.org/docs/api/api_key.html (gratuito)

# Alertas Telegram
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_CHAT_ID=tu_chat_id

# Opcionales
ALPHA_VANTAGE_KEY=tu_clave       # https://www.alphavantage.co (25 req/día gratis)
NEWS_API_KEY=tu_clave            # https://newsapi.org (100 req/día gratis)
REDDIT_CLIENT_ID=tu_id
REDDIT_CLIENT_SECRET=tu_secret
KALSHI_API_KEY=tu_clave          # Opcional para datos Kalshi avanzados

# Capital y modo
INITIAL_CAPITAL=10000
TRADING_MODE=paper               # "paper" = simulado, sin dinero real
```

### Comandos

```bash
python main.py           # Bot continuo 24/7
python main.py --once    # Un ciclo y salir
python main.py --report  # Solo mostrar dashboard
python web_dashboard.py  # Dashboard web en localhost:5000
```

---

## Estructura del proyecto

```
AutoTrader_IA/
├── main.py                      # Punto de entrada y scheduler
├── config.py                    # Configuración centralizada
├── web_dashboard.py             # Dashboard web (Flask)
├── requirements.txt
│
├── modules/
│   ├── trader.py                # Orquestador de trading
│   ├── market_analyzer.py       # Análisis técnico (RSI, MACD, BB, ADX...)
│   ├── news_analyzer.py         # Sentimiento multi-fuente (RSS + APIs)
│   ├── pro_signals.py           # Señales Finnhub (insiders, analistas, earnings)
│   ├── prediction_markets.py    # Polymarket + Kalshi
│   ├── macro_signals.py         # CNN F&G + FRED + COT + Put/Call + AAII
│   ├── options_flow.py          # Flujo inusual de opciones (Barchart)
│   ├── market_screener.py       # Screener dinámico S&P 500 + MidCap
│   ├── market_regime.py         # Detección de régimen de mercado
│   ├── portfolio.py             # Gestión de posiciones (SQLite)
│   ├── risk_manager.py          # Sizing, stops, circuit breakers
│   ├── circuit_breaker.py       # Límites de drawdown y pérdida diaria
│   ├── telegram_notifier.py     # Alertas en tiempo real
│   ├── backtester.py            # Motor de backtesting
│   └── market_hours.py          # Horarios NYSE/crypto
│
└── strategies/
    ├── base_strategy.py
    └── combined_strategy.py     # Agregación ponderada de todas las señales
```

---

## Dashboard

El dashboard web (Flask, `localhost:5000`) muestra en tiempo real:
- P&L del portafolio con histórico
- Posiciones abiertas con stops y profit actual
- Señales activas por ticker
- Logs del bot
- Régimen de mercado actual

También accesible desde móvil en la red local.

---

## Notas

- **Paper trading**: el bot no ejecuta órdenes reales. Simula compras/ventas con precios de mercado reales.
- **Polymarket y Kalshi**: datos de mercados de predicción con capital real, no encuestas. Son indicadores forward-looking más fiables para eventos macro.
- **COT Report**: publicado cada viernes por la CFTC. Muestra el posicionamiento real de hedge funds y CTAs — el dato más honesto del mercado porque es regulatorio.
- **FRED API**: gratuita con registro en fred.stlouisfed.org. Curva de tipos invertida (T10Y2Y negativa) es el predictor de recesión más fiable históricamente.
- **AAII**: requiere `openpyxl` (incluido en requirements.txt) para parsear el Excel semanal.
