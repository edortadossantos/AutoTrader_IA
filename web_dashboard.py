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
from flask import Flask, render_template_string, jsonify

from config import INITIAL_CAPITAL, WATCHLIST, DISPLAY_CURRENCY
from config import DRAWDOWN_WARN_PCT, DRAWDOWN_REDUCE_PCT, DRAWDOWN_HALT_PCT
from modules.portfolio import get_positions, get_trade_history, get_stats, init_db
from modules.market_analyzer import get_current_prices
from modules.risk_manager import risk_check_portfolio
from modules.market_hours import market_status
from modules import circuit_breaker
from modules.currency import get_usd_eur_rate, currency_symbol, to_display

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AutoTrader IA</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; }
header { background: #161b22; padding: 14px 28px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #30363d; }
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

.grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; padding: 20px 28px 0; }
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
</style>
</head>
<body>

<header>
  <h1>&#9654; AutoTrader IA</h1>
  <span class="badge badge-paper">PAPER TRADING</span>
  <span class="badge" id="mkt-badge">—</span>
  <span id="mkt-detail" style="font-size:0.78rem;color:#8b949e"></span>
  <div class="header-right">
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

    // Tabla posiciones
    const posDiv = document.getElementById('positions-table');
    if (d.positions.length > 0) {
      posDiv.innerHTML = `<table><tr>
        <th>Ticker</th><th>Precio</th><th>Entrada</th><th>PnL</th><th>Stop</th><th>TP</th>
      </tr>` + d.positions.map(p => {
        const curr = d.prices[p.ticker] || p.avg_price;
        const pnl = (curr - p.avg_price) * p.qty;
        const pp = (curr/p.avg_price - 1)*100;
        return `<tr>
          <td><strong>${p.ticker}</strong></td>
          <td>${fmt(curr)}</td><td>${fmt(p.avg_price)}</td>
          <td class="${cc(pnl)}">${fmt(pnl)} <small>(${pp>=0?'+':''}${pp.toFixed(2)}%)</small></td>
          <td style="color:#f85149">${fmt(p.stop_loss)}</td>
          <td style="color:#3fb950">${fmt(p.take_profit)}</td>
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
    initial_display = to_display(INITIAL_CAPITAL)
    rate_info = f"1 USD = {rate:.4f} EUR" if DISPLAY_CURRENCY == "EUR" else "Moneda: USD"
    return render_template_string(
        HTML,
        initial_usd=INITIAL_CAPITAL,
        initial_display=round(initial_display, 2),
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
    })


@app.route("/api/reset-halt", methods=["POST"])
def reset_halt():
    circuit_breaker.reset_halt()
    return jsonify({"ok": True})


if __name__ == "__main__":
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    init_db()
    print("Abriendo dashboard en http://localhost:5000 ...")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
