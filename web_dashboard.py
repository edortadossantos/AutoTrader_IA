"""
Dashboard web — abre en el navegador en http://localhost:5000
Muestra: equity curve, posiciones, historial, circuit breaker, horario de mercado.

Uso:
    python web_dashboard.py
"""
import sqlite3
import webbrowser
import threading
from datetime import datetime
from flask import Flask, render_template_string, jsonify, send_from_directory, request

from config import INITIAL_CAPITAL, WATCHLIST, DISPLAY_CURRENCY
from config import DRAWDOWN_WARN_PCT, DRAWDOWN_REDUCE_PCT, DRAWDOWN_HALT_PCT
from modules.portfolio import get_positions, get_trade_history, get_stats, init_db, get_initial_capital_usd, get_active_cooldowns
from modules.market_analyzer import get_current_prices
from modules.risk_manager import risk_check_portfolio
from modules.market_hours import market_status
from modules import circuit_breaker
from modules.currency import get_usd_eur_rate, currency_symbol, to_display
from modules.market_regime import get_market_regime

import os as _os
app = Flask(__name__, static_folder=_os.path.join(_os.path.dirname(__file__), "static"))

HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>AutoTrader IA</title>
<!-- PWA / iPhone home screen -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="AutoTrader">
<link rel="apple-touch-icon" sizes="180x180" href="/static/icon.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0d1117">
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9;
       padding-bottom: env(safe-area-inset-bottom); }
header { background: #161b22; padding: 14px 28px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #30363d;
         padding-top: calc(14px + env(safe-area-inset-top));
         padding-left: calc(28px + env(safe-area-inset-left));
         padding-right: calc(28px + env(safe-area-inset-right)); }
header h1 { font-size: 1.3rem; color: #58a6ff; }
.badge { font-size: 0.7rem; font-weight: bold; padding: 3px 10px; border-radius: 12px; }
.badge-paper { background: #f0e080; color: #0d1117; }
.badge-open  { background: #3fb950; color: #0d1117; }
.badge-closed{ background: #30363d; color: #8b949e; }
.badge-warn  { background: #f0a030; color: #0d1117; }
.badge-halt  { background: #f85149; color: #fff; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
.header-right { margin-left: auto; display: flex; align-items: center; gap: 12px; }
.timestamp { font-size: 0.78rem; color: #8b949e; }
.refresh-btn { background: #238636; border: none; color: #fff; padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
.refresh-btn:hover { background: #2ea043; }

/* Circuit breaker banner */
#cb-banner { display: none; padding: 10px 28px; font-size: 0.88rem; font-weight: 600; }
.cb-0 { display: none !important; }
.cb-1 { display: block !important; background: #2d2000; border-left: 4px solid #f0a030; color: #f0a030; }
.cb-2 { display: block !important; background: #2d0000; border-left: 4px solid #f85149; color: #f85149; }
.cb-3 { display: block !important; background: #f85149; color: #fff; text-align: center; font-size: 1rem; }

.grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; padding: 20px 28px 0; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 18px; }
.card h3 { font-size: 0.7rem; color: #8b949e; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
.card .value { font-size: 1.6rem; font-weight: 700; }
.card .sub { font-size: 0.75rem; color: #8b949e; margin-top: 3px; }
.green { color: #3fb950; } .red { color: #f85149; } .yellow { color: #f0e080; } .blue { color: #58a6ff; }

.watchlist { display: flex; flex-wrap: wrap; gap: 8px; padding: 14px 28px 0; }
.chip { background: #21262d; border: 1px solid #30363d; border-radius: 20px; padding: 4px 12px; font-size: 0.78rem; }
.chip .price { color: #58a6ff; font-weight: 600; }
.chip.has-pos { border-color: #3fb950; }

.charts { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; padding: 14px 28px 0; }
.charts-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; padding: 14px 28px 0; }
.chart-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 16px; }
.chart-card h2 { font-size: 0.78rem; color: #8b949e; margin-bottom: 10px; text-transform: uppercase; letter-spacing: .05em; }
.tables { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 14px 28px 28px; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
th { color: #8b949e; font-weight: 600; text-align: left; padding: 7px 10px; border-bottom: 1px solid #30363d; font-size: 0.7rem; text-transform: uppercase; }
td { padding: 8px 10px; border-bottom: 1px solid #21262d; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #1c2128; }
.no-data { color: #8b949e; text-align: center; padding: 24px; font-size: 0.82rem; }

/* CB gauge */
.cb-gauge { display: flex; gap: 6px; align-items: center; margin-top: 4px; }
.cb-dot { width: 10px; height: 10px; border-radius: 50%; }
.limits-info { font-size: 0.7rem; color: #8b949e; line-height: 1.6; }

/* ── Responsivo móvil ── */
@media (max-width: 700px) {
  header { flex-wrap: wrap; padding: 10px 14px; gap: 8px;
           padding-top: calc(10px + env(safe-area-inset-top));
           padding-left: calc(14px + env(safe-area-inset-left));
           padding-right: calc(14px + env(safe-area-inset-right)); }
  header h1 { font-size: 1.1rem; }
  .header-right { width: 100%; justify-content: space-between; }
  #mkt-detail { display: none; }
  .grid { grid-template-columns: repeat(2, 1fr); padding: 12px 12px 0; gap: 10px; }
  .grid .card:nth-child(5), .grid .card:nth-child(6) { grid-column: span 1; }
  .card .value { font-size: 1.25rem; }
  .watchlist { padding: 10px 12px 0; gap: 6px; }
  .chip { font-size: 0.72rem; padding: 3px 9px; }
  .charts { grid-template-columns: 1fr; padding: 10px 12px 0; }
  .charts-3 { grid-template-columns: 1fr; padding: 10px 12px 0; }
  .tables { grid-template-columns: 1fr; padding: 10px 12px 14px; }
  #bottom-row { grid-template-columns: 1fr !important; padding: 0 12px 14px !important; }
  table { font-size: 0.75rem; }
  th, td { padding: 5px 6px; }
}
</style>
</head>
<body>

<header>
  <h1>&#9654; AutoTrader IA</h1>
  <span class="badge badge-paper">PAPER TRADING</span>
  <span class="badge" id="mkt-badge">—</span>
  <span id="mkt-detail" style="font-size:0.78rem;color:#8b949e"></span>
  <div class="header-right">
    <a href="/backtest" style="color:#58a6ff;font-size:.78rem;text-decoration:none">&#128202; Backtest</a>
    <a href="/logs" style="color:#8b949e;font-size:.78rem;text-decoration:none">&#128196; Logs</a>
    <span class="timestamp" id="ts">—</span>
    <button class="refresh-btn" onclick="loadData()">&#8635; Actualizar</button>
  </div>
</header>

<div id="cb-banner">&#9888; <span id="cb-msg"></span></div>

<div class="grid">
  <div class="card"><h3>Equity</h3><div class="value" id="equity">—</div><div class="sub" id="equity-sub">—</div></div>
  <div class="card"><h3>PnL Total</h3><div class="value" id="pnl">—</div><div class="sub" id="pnl-pct">—</div></div>
  <div class="card"><h3>Cash Libre</h3><div class="value" id="cash">—</div><div class="sub" id="rate-info">—</div></div>
  <div class="card"><h3>Operaciones</h3><div class="value" id="trades">—</div><div class="sub" id="winrate">—</div></div>
  <div class="card">
    <h3>Proteccion capital</h3>
    <div class="cb-gauge">
      <div class="cb-dot" id="cb-dot" style="background:#3fb950"></div>
      <span class="value" style="font-size:1rem" id="cb-label">OK</span>
    </div>
    <div class="sub" id="cb-sub">—</div>
    <div class="limits-info" style="margin-top:8px">
      Aviso: -{{ warn_pct }}<br>
      Reduccion: -{{ reduce_pct }}<br>
      HALT: -{{ halt_pct }}
    </div>
  </div>
  <div class="card">
    <h3>Regimen Mercado</h3>
    <div class="value" style="font-size:1rem" id="regime-label">—</div>
    <div class="sub" id="regime-detail">—</div>
    <div class="sub" id="regime-vix" style="margin-top:4px">—</div>
  </div>
</div>

<div class="watchlist" id="watchlist-row"></div>

<div class="charts">
  <div class="chart-card">
    <h2>&#128200; Equity Curve ({{ currency }})</h2>
    <div id="equity-chart" style="height:260px;"></div>
  </div>
  <div class="chart-card">
    <h2>&#9676; Exposicion por posicion</h2>
    <div id="pie-chart" style="height:260px;"></div>
  </div>
</div>

<div class="charts-3">
  <div class="chart-card">
    <h2>&#128185; PnL por operacion ({{ currency }})</h2>
    <div id="pnl-chart" style="height:200px;"></div>
  </div>
  <div class="chart-card">
    <h2>&#128268; Drawdown (%)</h2>
    <div id="drawdown-chart" style="height:200px;"></div>
  </div>
  <div class="chart-card">
    <h2>&#128340; Compras vs Ventas</h2>
    <div id="signals-chart" style="height:200px;"></div>
  </div>
</div>

<div class="tables">
  <div class="chart-card">
    <h2>&#128203; Posiciones Abiertas</h2>
    <div id="positions-table"></div>
  </div>
  <div class="chart-card">
    <h2>&#128196; Ultimas Operaciones</h2>
    <div id="trades-table"></div>
  </div>
</div>
<div style="padding: 0 28px 28px; display:grid; grid-template-columns:1fr 1fr; gap:14px" id="bottom-row">
  <div class="chart-card">
    <h2>&#9203; Cooldowns Activos</h2>
    <div id="cooldowns-table"></div>
  </div>
  <div class="chart-card">
    <h2>&#128270; Screener (ultimos candidatos)</h2>
    <div id="screener-table"></div>
  </div>
</div>

<script>
const SYM = "{{ sym }}";
const INITIAL = {{ initial_display }};
const INITIAL_USD = {{ initial_usd }};

function fmt(usd, d=2) {
  const v = usd * {{ rate }};
  return SYM + v.toLocaleString('es-ES', {minimumFractionDigits:d, maximumFractionDigits:d});
}
function fmtPct(n) { return (n>=0?'+':'') + (n*100).toFixed(2) + '%'; }
function cc(n) { return n >= 0 ? 'green' : 'red'; }

const CB_COLORS = ['#3fb950','#f0a030','#f85149','#f85149'];
const CB_LABELS = ['OK','AVISO','REDUCCION','HALT'];

function loadData() {
  fetch('/api/data').then(r=>r.json()).then(d => {
    document.getElementById('ts').textContent = 'Actualizado: ' + new Date().toLocaleTimeString('es-ES');

    // Mercado
    const mb = document.getElementById('mkt-badge');
    mb.textContent = d.market.status;
    mb.className = 'badge ' + (d.market.open ? 'badge-open' : 'badge-closed');
    document.getElementById('mkt-detail').textContent = d.market.detail + '  |  ' + d.market.et_time;

    // Circuit breaker
    const cb = d.circuit_breaker;
    const banner = document.getElementById('cb-banner');
    banner.className = 'cb-' + cb.level;
    document.getElementById('cb-msg').textContent = cb.reason;
    document.getElementById('cb-dot').style.background = CB_COLORS[cb.level];
    document.getElementById('cb-label').textContent = CB_LABELS[cb.level];
    document.getElementById('cb-label').className = 'value ' + (cb.level===0?'green':cb.level===1?'yellow':'red');
    document.getElementById('cb-sub').textContent =
      'Drawdown: ' + fmtPct(cb.drawdown_pct) +
      ' | Dia: ' + fmtPct(cb.daily_loss_pct) +
      ' | Rachas: ' + cb.consecutive_losses;

    // Tarjetas
    const equity_usd = d.equity;
    const pnl_usd = equity_usd - INITIAL_USD;
    const pnlPct = pnl_usd / INITIAL_USD;
    document.getElementById('equity').innerHTML = `<span class="${cc(pnl_usd)}">${fmt(equity_usd)}</span>`;
    document.getElementById('equity-sub').textContent = 'Inicial: ' + fmt(INITIAL_USD);
    document.getElementById('pnl').innerHTML = `<span class="${cc(pnl_usd)}">${fmt(pnl_usd)}</span>`;
    document.getElementById('pnl-pct').innerHTML = `<span class="${cc(pnl_usd)}">${fmtPct(pnlPct)}</span>`;
    document.getElementById('cash').textContent = fmt(d.cash);
    document.getElementById('rate-info').textContent = d.rate_info;
    document.getElementById('trades').textContent = d.stats.total_trades;
    document.getElementById('winrate').innerHTML = d.stats.total_trades > 0
      ? `Win rate: <span class="${cc(d.stats.win_rate-0.5)}">${(d.stats.win_rate*100).toFixed(1)}%</span>`
      : 'Sin operaciones';

    // Watchlist chips
    document.getElementById('watchlist-row').innerHTML = Object.entries(d.prices).map(([t, p]) => {
      const hasPos = d.positions.some(x => x.ticker === t);
      return `<div class="chip${hasPos?' has-pos':''}">${t}${hasPos?' &#11044;':''} <span class="price">${fmt(p)}</span></div>`;
    }).join('');

    // Equity curve
    if (d.snapshots.length > 1) {
      Plotly.newPlot('equity-chart', [
        { x: d.snapshots.map(s=>s.date), y: d.snapshots.map(s=>s.equity * {{ rate }}),
          type:'scatter', mode:'lines+markers', name:'Equity',
          line:{color:'#58a6ff',width:2}, marker:{size:4},
          fill:'tozeroy', fillcolor:'rgba(88,166,255,0.08)' },
        { x: d.snapshots.map(s=>s.date), y: d.snapshots.map(()=>INITIAL),
          type:'scatter', mode:'lines', name:'Capital inicial',
          line:{color:'#8b949e',width:1,dash:'dash'} }
      ], layoutDark({ yaxis:{tickprefix:SYM} }), {responsive:true, displayModeBar:false});
    } else {
      document.getElementById('equity-chart').innerHTML = '<p class="no-data">El grafico aparecera despues del primer dia de operaciones</p>';
    }

    // Pie posiciones
    if (d.positions.length > 0) {
      Plotly.newPlot('pie-chart',
        [{ labels: d.positions.map(p=>p.ticker),
           values: d.positions.map(p => p.qty * (d.prices[p.ticker]||p.avg_price)),
           type:'pie', hole:0.4, textinfo:'label+percent',
           marker:{colors:['#58a6ff','#3fb950','#f0e080','#f85149','#bc8cff','#ff8c00']} }],
        layoutDark({}), {responsive:true, displayModeBar:false});
    } else {
      document.getElementById('pie-chart').innerHTML = '<p class="no-data">Sin posiciones abiertas</p>';
    }

    // PnL barras
    const sells = d.trades.filter(t=>t.side==='SELL'&&t.pnl!=null);
    if (sells.length > 0) {
      Plotly.newPlot('pnl-chart',
        [{ x: sells.map(t=>t.ticker), y: sells.map(t=>t.pnl * {{ rate }}),
           type:'bar', marker:{color: sells.map(t=>t.pnl>=0?'#3fb950':'#f85149')} }],
        layoutDark({margin:{t:10,b:40,l:50,r:10}, yaxis:{tickprefix:SYM}}),
        {responsive:true, displayModeBar:false});
    } else {
      document.getElementById('pnl-chart').innerHTML = '<p class="no-data">Sin operaciones cerradas</p>';
    }

    // Drawdown
    if (d.snapshots.length > 1) {
      const dd = d.snapshots.map(s => ((INITIAL - s.equity * {{ rate }}) / INITIAL) * 100);
      Plotly.newPlot('drawdown-chart',
        [{ x: d.snapshots.map(s=>s.date), y: dd,
           type:'scatter', mode:'lines', fill:'tozeroy',
           fillcolor:'rgba(248,81,73,0.15)', line:{color:'#f85149',width:2} },
         { x: d.snapshots.map(s=>s.date), y: d.snapshots.map(()=>{{ warn_num }}),
           type:'scatter', mode:'lines', line:{color:'#f0a030',width:1,dash:'dot'}, name:'Aviso' },
         { x: d.snapshots.map(s=>s.date), y: d.snapshots.map(()=>{{ halt_num }}),
           type:'scatter', mode:'lines', line:{color:'#f85149',width:1,dash:'dot'}, name:'HALT' }],
        layoutDark({yaxis:{ticksuffix:'%',autorange:'reversed'}}),
        {responsive:true, displayModeBar:false});
    } else {
      document.getElementById('drawdown-chart').innerHTML = '<p class="no-data">Sin datos aun</p>';
    }

    // Compras vs ventas
    const buys = d.trades.filter(t=>t.side==='BUY').length;
    const sellsN = d.trades.filter(t=>t.side==='SELL').length;
    if (buys + sellsN > 0) {
      Plotly.newPlot('signals-chart',
        [{ labels:['Compras','Ventas'], values:[buys,sellsN], type:'pie', hole:0.5,
           marker:{colors:['#3fb950','#f85149']}, textinfo:'label+value' }],
        layoutDark({}), {responsive:true, displayModeBar:false});
    } else {
      document.getElementById('signals-chart').innerHTML = '<p class="no-data">Sin senales aun</p>';
    }

    // Régimen de mercado
    const reg = d.regime;
    if (reg) {
      const regColors = { bull: '#3fb950', neutral: '#f0e080', bear: '#f85149' };
      const regEmoji = { bull: '&#128994; BULL', neutral: '&#128993; NEUTRAL', bear: '&#128308; BEAR' };
      document.getElementById('regime-label').innerHTML =
        `<span style="color:${regColors[reg.regime]}">${regEmoji[reg.regime]||reg.regime.toUpperCase()}</span>`;
      document.getElementById('regime-detail').textContent =
        `SPY: ${reg.spy_vs_sma200>=0?'+':''}${reg.spy_vs_sma200}% vs SMA200`;
      document.getElementById('regime-vix').textContent = `VIX=${reg.vix} | mult×${reg.min_score_mult}`;
    }

    // Cooldowns
    const coolDiv = document.getElementById('cooldowns-table');
    if (d.cooldowns && d.cooldowns.length > 0) {
      coolDiv.innerHTML = `<table><tr><th>Ticker</th><th>Razon</th><th>Bloqueado hasta</th></tr>` +
        d.cooldowns.map(c => `<tr>
          <td><strong>${c.ticker}</strong></td>
          <td style="color:#f0a030">${c.reason}</td>
          <td style="font-size:.7rem;color:#8b949e">${c.blocked_until.slice(5,16)} UTC</td>
        </tr>`).join('') + '</table>';
    } else {
      coolDiv.innerHTML = '<p class="no-data">Sin cooldowns activos</p>';
    }

    // Screener
    const scrDiv = document.getElementById('screener-table');
    if (d.screener && d.screener.length > 0) {
      scrDiv.innerHTML = `<table><tr><th>Ticker</th><th>Score</th><th>Vol ratio</th><th>Momentum</th></tr>` +
        d.screener.map(s => `<tr>
          <td><strong>${s.ticker}</strong></td>
          <td style="color:#58a6ff">${(s.score*100).toFixed(0)}</td>
          <td>${s.vol_ratio ? s.vol_ratio.toFixed(1)+'x' : '—'}</td>
          <td class="${s.momentum>=0?'green':'red'}">${s.momentum>=0?'+':''}${(s.momentum*100).toFixed(1)}%</td>
        </tr>`).join('') + '</table>';
    } else {
      scrDiv.innerHTML = '<p class="no-data">Screener: sin datos (solo activo con NYSE abierto)</p>';
    }

    // Tabla posiciones
    const posDiv = document.getElementById('positions-table');
    if (d.positions.length > 0) {
      posDiv.innerHTML = `<table><tr>
        <th>Ticker</th><th>Precio</th><th>Entrada</th><th>PnL</th><th>Stop</th><th>TP</th><th>Trail Max</th>
      </tr>` + d.positions.map(p => {
        const curr = d.prices[p.ticker] || p.avg_price;
        const pnl = (curr - p.avg_price) * p.qty;
        const pp = (curr/p.avg_price - 1)*100;
        const th = p.trailing_high || p.avg_price;
        const thPct = ((th/p.avg_price)-1)*100;
        return `<tr>
          <td><strong>${p.ticker}</strong></td>
          <td>${fmt(curr)}</td><td>${fmt(p.avg_price)}</td>
          <td class="${cc(pnl)}">${fmt(pnl)} <small>(${pp>=0?'+':''}${pp.toFixed(2)}%)</small></td>
          <td style="color:#f85149">${fmt(p.stop_loss)}</td>
          <td style="color:#3fb950">${fmt(p.take_profit)}</td>
          <td style="color:#58a6ff">${fmt(th)} <small>(${thPct>=0?'+':''}${thPct.toFixed(1)}%)</small></td>
        </tr>`;
      }).join('') + '</table>';
    } else {
      posDiv.innerHTML = '<p class="no-data">Sin posiciones abiertas</p>';
    }

    // Tabla historial
    const trDiv = document.getElementById('trades-table');
    if (d.trades.length > 0) {
      trDiv.innerHTML = `<table><tr>
        <th>Fecha</th><th>Ticker</th><th>Lado</th><th>Precio</th><th>PnL</th><th>Razon</th>
      </tr>` + d.trades.slice(0,20).map(t => {
        const pnlStr = t.pnl != null ? `<span class="${cc(t.pnl)}">${fmt(t.pnl)}</span>` : '—';
        const sideC = t.side==='BUY' ? 'green' : 'red';
        return `<tr>
          <td style="font-size:.7rem;color:#8b949e">${t.executed_at.slice(5,16)}</td>
          <td><strong>${t.ticker}</strong></td>
          <td class="${sideC}">${t.side}</td>
          <td>${fmt(t.price)}</td>
          <td>${pnlStr}</td>
          <td style="font-size:.7rem;color:#8b949e">${(t.reason||'').slice(0,18)}</td>
        </tr>`;
      }).join('') + '</table>';
    } else {
      trDiv.innerHTML = '<p class="no-data">Sin operaciones aun</p>';
    }
  });
}

function layoutDark(extra) {
  return Object.assign({
    paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
    font:{color:'#c9d1d9', size:11},
    margin:{t:10,b:30,l:50,r:10},
    xaxis:{gridcolor:'#21262d'},
    yaxis:{gridcolor:'#21262d'},
    showlegend:false
  }, extra);
}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    sym = currency_symbol()
    rate = get_usd_eur_rate()
    initial_usd = get_initial_capital_usd()
    initial_display = round(to_display(initial_usd), 2)
    rate_info = f"1 USD = {rate:.4f} EUR" if DISPLAY_CURRENCY == "EUR" else "Moneda: USD"
    return render_template_string(
        HTML,
        initial_usd=round(initial_usd, 2),
        initial_display=initial_display,
        sym=sym,
        rate=round(rate, 6),
        currency=DISPLAY_CURRENCY,
        rate_info=rate_info,
        warn_pct=f"{DRAWDOWN_WARN_PCT:.0%}",
        reduce_pct=f"{DRAWDOWN_REDUCE_PCT:.0%}",
        halt_pct=f"{DRAWDOWN_HALT_PCT:.0%}",
        warn_num=round(DRAWDOWN_WARN_PCT * 100, 1),
        halt_num=round(DRAWDOWN_HALT_PCT * 100, 1),
    )


@app.route("/api/data")
def api_data():
    current_prices = get_current_prices(WATCHLIST)
    risk = risk_check_portfolio(current_prices)
    stats = get_stats()
    positions = get_positions()
    trades = get_trade_history(limit=50)
    mkt = market_status()
    rate = get_usd_eur_rate()
    equity = risk["equity"]
    cb = circuit_breaker.check(equity)

    with sqlite3.connect("data/portfolio.db") as con:
        rows = con.execute(
            "SELECT date, equity, cash FROM daily_snapshots ORDER BY date ASC"
        ).fetchall()
    snapshots = [{"date": r[0], "equity": r[1], "cash": r[2]} for r in rows]
    snapshots.append({
        "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "equity": round(equity, 2),
        "cash": round(risk["cash"], 2),
    })

    # Market regime (cached 30 min, no se bloquea el dashboard)
    try:
        regime = get_market_regime()
    except Exception:
        regime = None

    # Cooldowns activos
    cooldowns = get_active_cooldowns()

    # Screener últimos candidatos (desde cache, sin re-descargar)
    screener = []
    try:
        from modules.market_screener import _screener_cache
        screener = [
            {**c, "momentum": c.get("pct_1d", 0) / 100}
            for c in _screener_cache.get("candidates", [])[:15]
        ]
    except Exception:
        pass

    return jsonify({
        "equity": round(equity, 2),
        "cash": round(risk["cash"], 2),
        "positions": positions,
        "trades": trades,
        "stats": stats,
        "prices": {k: round(v, 2) for k, v in current_prices.items()},
        "snapshots": snapshots,
        "market": mkt,
        "circuit_breaker": cb,
        "rate_info": f"1 USD = {rate:.4f} EUR" if DISPLAY_CURRENCY == "EUR" else "USD",
        "regime": regime,
        "cooldowns": cooldowns,
        "screener": screener,
    })


@app.route("/iconos")
def icon_picker():
    options = [
        ("opt1", "Minimalista", "Fondo verde oscuro, flecha arriba"),
        ("opt2", "Candlestick", "Velas japonesas verde/rojo"),
        ("opt3", "Letra A", "Gradiente azul-morado, letra grande"),
        ("opt4", "Badge circular", "Círculo con borde verde y curva"),
        ("opt5", "Neon", "Fondo negro, línea neón verde"),
    ]
    cards = "".join(f"""
    <div style="background:#161b22;border:2px solid #30363d;border-radius:16px;padding:16px;text-align:center">
      <img src="/static/{k}_512.png" style="width:120px;height:120px;border-radius:22px;box-shadow:0 4px 20px #0004">
      <div style="color:#fff;font-weight:700;margin:10px 0 4px">{title}</div>
      <div style="color:#8b949e;font-size:.78rem;margin-bottom:12px">{desc}</div>
      <a href="/set-icon/{k}" style="background:#238636;color:#fff;padding:8px 20px;border-radius:8px;text-decoration:none;font-size:.85rem">Usar este</a>
    </div>""" for k, title, desc in options)
    return f"""<!DOCTYPE html><html><head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Elige tu icono</title>
    <style>body{{background:#0d1117;color:#c9d1d9;font-family:sans-serif;padding:20px;margin:0}}
    h2{{color:#58a6ff;margin-bottom:16px}}
    .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
    @media(min-width:600px){{.grid{{grid-template-columns:repeat(3,1fr)}}}}</style>
    </head><body>
    <a href="/" style="color:#58a6ff;text-decoration:none;font-size:.85rem">&larr; Volver</a>
    <h2 style="margin-top:12px">Elige el icono</h2>
    <div class="grid">{cards}</div>
    </body></html>"""


@app.route("/set-icon/<name>")
def set_icon(name):
    import shutil, os
    allowed = {"opt1", "opt2", "opt3", "opt4", "opt5"}
    if name not in allowed:
        return "Invalid", 400
    src = f"static/{name}_512.png"
    src180 = f"static/{name}.png"
    if os.path.exists(src):
        shutil.copy(src, "static/icon_512.png")
        shutil.copy(src180, "static/icon.png")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{{background:#0d1117;color:#c9d1d9;font-family:sans-serif;padding:30px;text-align:center}}</style>
    </head><body>
    <div style="font-size:3rem">✅</div>
    <h2 style="color:#3fb950;margin:12px 0">Icono actualizado</h2>
    <p style="color:#8b949e">Borra el atajo antiguo del inicio y vuelve a añadirlo desde Safari.</p>
    <br><a href="/iconos" style="color:#58a6ff">← Volver a opciones</a>
    &nbsp;&nbsp;<a href="/" style="color:#58a6ff">Ir al dashboard</a>
    </body></html>"""


@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "AutoTrader IA",
        "short_name": "AutoTrader",
        "description": "Paper trading dashboard",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0d1117",
        "theme_color": "#0d1117",
        "icons": [
            {"src": "/static/icon.png", "sizes": "180x180", "type": "image/png"},
            {"src": "/static/icon_512.png", "sizes": "512x512", "type": "image/png"},
        ]
    })


@app.route("/api/reset-halt", methods=["POST"])
def reset_halt():
    circuit_breaker.reset_halt()
    return jsonify({"ok": True})


@app.route("/backtest")
def backtest_page():
    return """<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtester — AutoTrader IA</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',sans-serif;padding:20px}
h1{color:#58a6ff;margin-bottom:16px;font-size:1.3rem}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
input,select{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:8px 12px;border-radius:6px;font-size:.9rem}
input{width:160px}
button{background:#238636;border:none;color:#fff;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:.9rem}
button:hover{background:#2ea043}
button:disabled{background:#30363d;cursor:not-allowed}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin:16px 0}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
.card h3{font-size:.65rem;color:#8b949e;text-transform:uppercase;margin-bottom:4px}
.card .v{font-size:1.3rem;font-weight:700}
.green{color:#3fb950}.red{color:#f85149}.blue{color:#58a6ff}.yellow{color:#f0e080}
.chart-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:14px}
.chart-card h2{font-size:.78rem;color:#8b949e;text-transform:uppercase;margin-bottom:10px}
a{color:#58a6ff;text-decoration:none;font-size:.85rem;display:inline-block;margin-bottom:16px}
#status{color:#8b949e;font-size:.85rem;margin-top:4px}
@media(max-width:600px){.cards{grid-template-columns:1fr 1fr}}
</style></head><body>
<a href="/">&larr; Dashboard</a>
<h1>&#128202; Backtester — Análisis histórico de la estrategia</h1>
<div class="row">
  <input id="ticker" value="AAPL" placeholder="Ticker (AAPL, BTC-USD...)" />
  <select id="period">
    <option value="6mo">6 meses</option>
    <option value="1y" selected>1 año</option>
    <option value="2y">2 años</option>
    <option value="5y">5 años</option>
  </select>
  <button id="btn" onclick="runBacktest()">&#9654; Ejecutar</button>
</div>
<div id="status"></div>
<div id="results" style="display:none">
  <div class="cards" id="cards"></div>
  <div class="chart-card"><h2>&#128200; Equity Curve vs Buy &amp; Hold</h2><div id="eq-chart" style="height:280px"></div></div>
</div>
<script>
const darkLayout = (extra={}) => Object.assign({
  paper_bgcolor:'#161b22',plot_bgcolor:'#161b22',font:{color:'#c9d1d9',size:11},
  margin:{t:10,b:40,l:60,r:10},xaxis:{gridcolor:'#21262d'},yaxis:{gridcolor:'#21262d'},showlegend:true
},extra);

function runBacktest() {
  const ticker = document.getElementById('ticker').value.trim().toUpperCase();
  const period = document.getElementById('period').value;
  const btn = document.getElementById('btn');
  const st  = document.getElementById('status');
  if (!ticker) return;
  btn.disabled = true;
  btn.textContent = 'Calculando...';
  st.textContent = 'Descargando datos históricos y ejecutando simulación...';
  document.getElementById('results').style.display = 'none';

  fetch(`/api/backtest?ticker=${ticker}&period=${period}`)
    .then(r=>r.json())
    .then(d => {
      btn.disabled = false;
      btn.textContent = '▶ Ejecutar';
      if (d.error) { st.textContent = '❌ ' + d.error; return; }
      st.textContent = '';
      document.getElementById('results').style.display = 'block';

      const ret  = d.total_return_pct;
      const bh   = d.buy_hold_return;
      const alpha= (ret - bh).toFixed(1);

      document.getElementById('cards').innerHTML = `
        <div class="card"><h3>Retorno total</h3><div class="v ${ret>=0?'green':'red'}">${ret>=0?'+':''}${ret}%</div></div>
        <div class="card"><h3>Buy &amp; Hold</h3><div class="v ${bh>=0?'green':'red'}">${bh>=0?'+':''}${bh}%</div></div>
        <div class="card"><h3>Alpha vs B&H</h3><div class="v ${alpha>=0?'green':'red'}">${alpha>=0?'+':''}${alpha}%</div></div>
        <div class="card"><h3>Sharpe ratio</h3><div class="v ${d.sharpe>=1?'green':d.sharpe>=0.5?'yellow':'red'}">${d.sharpe}</div></div>
        <div class="card"><h3>Max drawdown</h3><div class="v red">${d.max_drawdown_pct}%</div></div>
        <div class="card"><h3>Win rate</h3><div class="v ${d.win_rate>=0.5?'green':'red'}">${(d.win_rate*100).toFixed(1)}%</div></div>
        <div class="card"><h3>Operaciones</h3><div class="v blue">${d.total_trades}</div></div>
        <div class="card"><h3>Profit factor</h3><div class="v ${d.profit_factor>=1?'green':'red'}">${d.profit_factor}</div></div>
        <div class="card"><h3>Ganancia media</h3><div class="v green">$${d.avg_win}</div></div>
        <div class="card"><h3>Pérdida media</h3><div class="v red">$${d.avg_loss}</div></div>
      `;

      // Equity curve
      const curve = d.equity_curve;
      const bh_curve = curve.map((p,i) => ({
        date: p.date,
        equity: d.initial_capital * (1 + bh/100 * i / curve.length)
      }));
      Plotly.newPlot('eq-chart', [
        { x: curve.map(p=>p.date), y: curve.map(p=>p.equity),
          type:'scatter', mode:'lines', name:'Estrategia',
          line:{color:'#58a6ff',width:2}, fill:'tozeroy', fillcolor:'rgba(88,166,255,0.06)' },
        { x: curve.map(p=>p.date),
          y: curve.map((_,i)=>d.initial_capital*(1+bh/100*i/curve.length)),
          type:'scatter', mode:'lines', name:'Buy & Hold',
          line:{color:'#3fb950',width:1.5,dash:'dash'} },
        { x: curve.map(p=>p.date), y: curve.map(()=>d.initial_capital),
          type:'scatter', mode:'lines', name:'Capital inicial',
          line:{color:'#8b949e',width:1,dash:'dot'} }
      ], darkLayout({yaxis:{tickprefix:'$'}}), {responsive:true,displayModeBar:false});
    })
    .catch(e => {
      btn.disabled = false;
      btn.textContent = '▶ Ejecutar';
      st.textContent = '❌ Error: ' + e.message;
    });
}
document.getElementById('ticker').addEventListener('keydown', e => { if(e.key==='Enter') runBacktest(); });
</script>
</body></html>"""


@app.route("/api/backtest")
def api_backtest():
    from modules.backtester import run_backtest
    ticker = request.args.get("ticker", "AAPL").upper()
    period = request.args.get("period", "1y")
    if period not in ("6mo", "1y", "2y", "5y"):
        period = "1y"
    result = run_backtest(ticker, period)
    # No enviamos la equity_curve completa si es muy larga (>2000 puntos → submuestrear)
    curve = result.get("equity_curve", [])
    if len(curve) > 500:
        step = len(curve) // 500
        result["equity_curve"] = curve[::step]
    return jsonify(result)


@app.route("/logs")
def view_logs():
    from pathlib import Path
    log_path = Path("logs/autotrader.log")
    if not log_path.exists():
        lines = ["(sin logs todavia)"]
    else:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]  # últimas 200 líneas
    lines_html = "".join(
        f'<span style="color:{"#f85149" if "[ERROR]" in l or "[CRITICAL]" in l else "#f0a030" if "[WARNING]" in l else "#adbac7"}">{l}</span>'
        for l in lines
    )
    html = f"""<!DOCTYPE html><html><head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>AutoTrader Logs</title>
    <style>body{{background:#1c2128;color:#adbac7;font-family:monospace;font-size:12px;padding:10px;margin:0}}
    pre{{white-space:pre-wrap;word-break:break-all}}
    a{{color:#388bfd;text-decoration:none;display:block;margin-bottom:10px}}</style>
    <meta http-equiv="refresh" content="30">
    </head><body>
    <a href="/">&larr; Volver al dashboard</a>
    <pre>{lines_html}</pre>
    </body></html>"""
    return html


if __name__ == "__main__":
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    init_db()
    print("Abriendo dashboard en http://localhost:5000 ...")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
