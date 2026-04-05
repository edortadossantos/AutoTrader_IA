"""
Dashboard web — abre en el navegador en http://localhost:5000
Muestra: equity curve, posiciones abiertas, historial de operaciones, métricas.

Uso:
    python web_dashboard.py
"""
import sqlite3
import json
import webbrowser
import threading
from datetime import datetime
from flask import Flask, render_template_string, jsonify

from config import INITIAL_CAPITAL, WATCHLIST
from modules.portfolio import (
    get_positions, get_trade_history, get_stats, get_cash
)
from modules.market_analyzer import get_current_prices
from modules.risk_manager import risk_check_portfolio

app = Flask(__name__)

# ── HTML template (todo inline, sin archivos externos) ───────────
HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AutoTrader IA — Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; }
  header { background: #161b22; padding: 16px 32px; display: flex; align-items: center; gap: 16px; border-bottom: 1px solid #30363d; }
  header h1 { font-size: 1.4rem; color: #58a6ff; }
  header .badge { background: #f0e080; color: #0d1117; font-size: 0.7rem; font-weight: bold; padding: 2px 8px; border-radius: 12px; }
  header .timestamp { margin-left: auto; font-size: 0.8rem; color: #8b949e; }
  .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; padding: 24px 32px 0; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 20px; }
  .card h3 { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
  .card .value { font-size: 1.8rem; font-weight: 700; }
  .card .sub { font-size: 0.8rem; color: #8b949e; margin-top: 4px; }
  .green { color: #3fb950; }
  .red { color: #f85149; }
  .yellow { color: #f0e080; }
  .charts { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; padding: 16px 32px; }
  .chart-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 16px; }
  .chart-card h2 { font-size: 0.9rem; color: #8b949e; margin-bottom: 12px; text-transform: uppercase; }
  .tables { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 0 32px 32px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { color: #8b949e; font-weight: 600; text-align: left; padding: 8px 12px; border-bottom: 1px solid #30363d; font-size: 0.75rem; text-transform: uppercase; }
  td { padding: 10px 12px; border-bottom: 1px solid #21262d; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1c2128; }
  .side-buy { color: #3fb950; font-weight: bold; }
  .side-sell { color: #f85149; font-weight: bold; }
  .refresh-btn { background: #238636; border: none; color: #fff; padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; margin-left: 16px; }
  .refresh-btn:hover { background: #2ea043; }
  .no-data { color: #8b949e; text-align: center; padding: 24px; font-size: 0.85rem; }
  .watchlist { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 32px 16px; }
  .ticker-chip { background: #21262d; border: 1px solid #30363d; border-radius: 20px; padding: 4px 12px; font-size: 0.8rem; }
  .ticker-chip .price { color: #58a6ff; font-weight: 600; }
</style>
</head>
<body>

<header>
  <h1>&#9654; AutoTrader IA</h1>
  <span class="badge">PAPER TRADING</span>
  <span class="timestamp" id="ts">Cargando...</span>
  <button class="refresh-btn" onclick="loadData()">&#8635; Actualizar</button>
</header>

<div class="grid" id="summary-cards">
  <div class="card"><h3>Equity</h3><div class="value" id="equity">—</div><div class="sub" id="equity-sub">—</div></div>
  <div class="card"><h3>PnL Total</h3><div class="value" id="pnl">—</div><div class="sub" id="pnl-pct">—</div></div>
  <div class="card"><h3>Cash Libre</h3><div class="value" id="cash">—</div><div class="sub">disponible para operar</div></div>
  <div class="card"><h3>Operaciones</h3><div class="value" id="trades">—</div><div class="sub" id="winrate">—</div></div>
</div>

<div id="watchlist-row" class="watchlist" style="margin-top:16px;"></div>

<div class="charts">
  <div class="chart-card">
    <h2>&#128200; Equity Curve</h2>
    <div id="equity-chart" style="height:280px;"></div>
  </div>
  <div class="chart-card">
    <h2>&#9676; Exposición por ticker</h2>
    <div id="pie-chart" style="height:280px;"></div>
  </div>
</div>

<div class="charts" style="padding-top:0;">
  <div class="chart-card">
    <h2>&#128185; PnL por operación</h2>
    <div id="pnl-chart" style="height:220px;"></div>
  </div>
  <div class="chart-card">
    <h2>&#128340; Distribución de señales</h2>
    <div id="signals-chart" style="height:220px;"></div>
  </div>
</div>

<div class="tables">
  <div class="chart-card">
    <h2>&#128203; Posiciones Abiertas</h2>
    <div id="positions-table"></div>
  </div>
  <div class="chart-card">
    <h2>&#128196; Últimas 20 Operaciones</h2>
    <div id="trades-table"></div>
  </div>
</div>

<script>
const fmt = (n, d=2) => n != null ? '$' + n.toLocaleString('es-ES', {minimumFractionDigits:d, maximumFractionDigits:d}) : '—';
const fmtPct = (n) => n != null ? (n >= 0 ? '+' : '') + (n*100).toFixed(2) + '%' : '—';
const colorClass = (n) => n >= 0 ? 'green' : 'red';

function loadData() {
  fetch('/api/data').then(r => r.json()).then(d => {
    document.getElementById('ts').textContent = 'Actualizado: ' + new Date().toLocaleTimeString('es-ES');

    // Summary cards
    const pnl = d.equity - {{ initial_capital }};
    const pnlPct = pnl / {{ initial_capital }};
    document.getElementById('equity').innerHTML = `<span class="${colorClass(pnl)}">${fmt(d.equity)}</span>`;
    document.getElementById('equity-sub').textContent = 'Capital inicial: ' + fmt({{ initial_capital }});
    document.getElementById('pnl').innerHTML = `<span class="${colorClass(pnl)}">${fmt(pnl)}</span>`;
    document.getElementById('pnl-pct').innerHTML = `<span class="${colorClass(pnl)}">${fmtPct(pnlPct)}</span>`;
    document.getElementById('cash').textContent = fmt(d.cash);
    document.getElementById('trades').textContent = d.stats.total_trades;
    document.getElementById('winrate').innerHTML = d.stats.total_trades > 0
      ? `Win rate: <span class="${colorClass(d.stats.win_rate - 0.5)}">${(d.stats.win_rate*100).toFixed(1)}%</span>`
      : 'Sin operaciones aún';

    // Watchlist chips
    const wl = document.getElementById('watchlist-row');
    wl.innerHTML = Object.entries(d.prices).map(([t, p]) => {
      const pos = d.positions.find(x => x.ticker === t);
      const dot = pos ? ' 🔵' : '';
      return `<div class="ticker-chip">${t}${dot} <span class="price">${fmt(p)}</span></div>`;
    }).join('');

    // Equity curve
    if (d.snapshots.length > 1) {
      Plotly.newPlot('equity-chart', [{
        x: d.snapshots.map(s => s.date),
        y: d.snapshots.map(s => s.equity),
        type: 'scatter', mode: 'lines+markers',
        line: { color: '#58a6ff', width: 2 },
        marker: { size: 4 },
        fill: 'tozeroy', fillcolor: 'rgba(88,166,255,0.08)',
        name: 'Equity'
      }, {
        x: d.snapshots.map(s => s.date),
        y: d.snapshots.map(() => {{ initial_capital }}),
        type: 'scatter', mode: 'lines',
        line: { color: '#8b949e', width: 1, dash: 'dash' },
        name: 'Capital inicial'
      }], {
        paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
        font: { color: '#c9d1d9', size: 11 },
        margin: { t: 10, b: 30, l: 50, r: 10 },
        xaxis: { gridcolor: '#21262d' },
        yaxis: { gridcolor: '#21262d', tickprefix: '$' },
        showlegend: false
      }, { responsive: true, displayModeBar: false });
    } else {
      document.getElementById('equity-chart').innerHTML = '<p class="no-data">Se generará el gráfico después del primer día de operaciones</p>';
    }

    // Pie chart posiciones
    if (d.positions.length > 0) {
      const vals = d.positions.map(p => (p.qty * (d.prices[p.ticker] || p.avg_price)).toFixed(2));
      Plotly.newPlot('pie-chart', [{
        labels: d.positions.map(p => p.ticker),
        values: vals,
        type: 'pie',
        hole: 0.4,
        textinfo: 'label+percent',
        marker: { colors: ['#58a6ff','#3fb950','#f0e080','#f85149','#bc8cff'] }
      }], {
        paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
        font: { color: '#c9d1d9', size: 11 },
        margin: { t: 10, b: 10, l: 10, r: 10 },
        showlegend: false
      }, { responsive: true, displayModeBar: false });
    } else {
      document.getElementById('pie-chart').innerHTML = '<p class="no-data">Sin posiciones abiertas</p>';
    }

    // PnL por operación
    const sells = d.trades.filter(t => t.side === 'SELL' && t.pnl != null);
    if (sells.length > 0) {
      Plotly.newPlot('pnl-chart', [{
        x: sells.map(t => t.ticker + ' ' + t.executed_at.slice(5,16)),
        y: sells.map(t => t.pnl),
        type: 'bar',
        marker: { color: sells.map(t => t.pnl >= 0 ? '#3fb950' : '#f85149') },
        text: sells.map(t => (t.pnl >= 0 ? '+' : '') + '$' + t.pnl.toFixed(2)),
        textposition: 'auto'
      }], {
        paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
        font: { color: '#c9d1d9', size: 11 },
        margin: { t: 10, b: 60, l: 50, r: 10 },
        xaxis: { gridcolor: '#21262d', tickangle: -30 },
        yaxis: { gridcolor: '#21262d', tickprefix: '$' },
        showlegend: false
      }, { responsive: true, displayModeBar: false });
    } else {
      document.getElementById('pnl-chart').innerHTML = '<p class="no-data">Sin operaciones cerradas aún</p>';
    }

    // Señales pie
    const buys = d.trades.filter(t => t.side === 'BUY').length;
    const sellsN = d.trades.filter(t => t.side === 'SELL').length;
    if (buys + sellsN > 0) {
      Plotly.newPlot('signals-chart', [{
        labels: ['Compras', 'Ventas'],
        values: [buys, sellsN],
        type: 'pie', hole: 0.5,
        marker: { colors: ['#3fb950', '#f85149'] },
        textinfo: 'label+value'
      }], {
        paper_bgcolor: '#161b22', font: { color: '#c9d1d9', size: 12 },
        margin: { t: 10, b: 10, l: 10, r: 10 }, showlegend: false
      }, { responsive: true, displayModeBar: false });
    } else {
      document.getElementById('signals-chart').innerHTML = '<p class="no-data">Sin señales aún</p>';
    }

    // Tabla posiciones abiertas
    const posDiv = document.getElementById('positions-table');
    if (d.positions.length > 0) {
      let rows = d.positions.map(p => {
        const curr = d.prices[p.ticker] || p.avg_price;
        const pnl = (curr - p.avg_price) * p.qty;
        const pnlPct = (curr / p.avg_price - 1) * 100;
        const cls = colorClass(pnl);
        return `<tr>
          <td><strong>${p.ticker}</strong></td>
          <td>${fmt(curr)}</td>
          <td>${fmt(p.avg_price)}</td>
          <td class="${cls}">${fmt(pnl)} <span style="font-size:0.75em">(${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)</span></td>
          <td style="color:#f85149">${fmt(p.stop_loss)}</td>
          <td style="color:#3fb950">${fmt(p.take_profit)}</td>
        </tr>`;
      }).join('');
      posDiv.innerHTML = `<table><tr>
        <th>Ticker</th><th>Precio</th><th>Entrada</th><th>PnL</th><th>Stop</th><th>TP</th>
      </tr>${rows}</table>`;
    } else {
      posDiv.innerHTML = '<p class="no-data">Sin posiciones abiertas</p>';
    }

    // Tabla historial operaciones
    const trDiv = document.getElementById('trades-table');
    if (d.trades.length > 0) {
      let rows = d.trades.slice(0,20).map(t => {
        const pnlStr = t.pnl != null
          ? `<span class="${colorClass(t.pnl)}">${fmt(t.pnl)}</span>` : '—';
        return `<tr>
          <td style="color:#8b949e;font-size:0.75em">${t.executed_at.slice(5,16)}</td>
          <td><strong>${t.ticker}</strong></td>
          <td class="${t.side === 'BUY' ? 'side-buy' : 'side-sell'}">${t.side}</td>
          <td>${fmt(t.price)}</td>
          <td>${pnlStr}</td>
        </tr>`;
      }).join('');
      trDiv.innerHTML = `<table><tr>
        <th>Fecha</th><th>Ticker</th><th>Lado</th><th>Precio</th><th>PnL</th>
      </tr>${rows}</table>`;
    } else {
      trDiv.innerHTML = '<p class="no-data">Sin operaciones aún</p>';
    }
  });
}

loadData();
setInterval(loadData, 60000); // auto-refresh cada 60s
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML, initial_capital=INITIAL_CAPITAL)


@app.route("/api/data")
def api_data():
    current_prices = get_current_prices(WATCHLIST)
    risk = risk_check_portfolio(current_prices)
    stats = get_stats()
    positions = get_positions()
    trades = get_trade_history(limit=50)

    # Snapshots para equity curve
    with sqlite3.connect("data/portfolio.db") as con:
        rows = con.execute(
            "SELECT date, equity, cash FROM daily_snapshots ORDER BY date ASC"
        ).fetchall()
    snapshots = [{"date": r[0], "equity": r[1], "cash": r[2]} for r in rows]

    # Añadir punto actual al final
    equity = risk["equity"]
    snapshots.append({
        "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "equity": round(equity, 2),
        "cash": round(risk["cash"], 2)
    })

    return jsonify({
        "equity": round(equity, 2),
        "cash": round(risk["cash"], 2),
        "positions": positions,
        "trades": trades,
        "stats": stats,
        "prices": {k: round(v, 2) for k, v in current_prices.items()},
        "snapshots": snapshots,
        "risk": risk,
    })


def open_browser():
    webbrowser.open("http://localhost:5000")


if __name__ == "__main__":
    # Inicializar DB si no existe
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    from modules.portfolio import init_db
    init_db()

    print("Abriendo dashboard en http://localhost:5000 ...")
    threading.Timer(1.5, open_browser).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
