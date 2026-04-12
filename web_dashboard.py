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
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="AutoTrader">
<link rel="apple-touch-icon" sizes="180x180" href="/static/icon.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0a0e17">
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
/* ── Reset & Base ─────────────────────────────────────────────── */
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:       #0a0e17;
  --bg2:      #111827;
  --bg3:      #1a2235;
  --border:   #1e2d45;
  --text:     #e2e8f0;
  --muted:    #64748b;
  --green:    #0ecb81;
  --red:      #f6465d;
  --blue:     #3b82f6;
  --yellow:   #f59e0b;
  --purple:   #a855f7;
  --accent:   #f0b90b;
}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);
     padding-bottom:env(safe-area-inset-bottom);min-height:100vh}
.green{color:var(--green)} .red{color:var(--red)} .blue{color:var(--blue)}
.yellow{color:var(--yellow)} .muted{color:var(--muted)}

/* ── Top bar ─────────────────────────────────────────────────── */
.topbar{
  display:flex;align-items:center;gap:10px;
  background:var(--bg2);border-bottom:1px solid var(--border);
  padding:10px 18px;
  padding-top:calc(10px + env(safe-area-inset-top));
  position:sticky;top:0;z-index:100;
}
.topbar-logo{font-size:1rem;font-weight:700;color:#fff;display:flex;align-items:center;gap:6px}
.topbar-logo span{color:var(--accent)}
.pill{font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:20px}
.pill-paper{background:#2d2a00;color:var(--accent);border:1px solid #4a3f00}
.pill-open{background:#052e16;color:var(--green);border:1px solid #166534}
.pill-closed{background:#1a1a1a;color:var(--muted);border:1px solid var(--border)}
.pill-warn{background:#2d1a00;color:var(--yellow);border:1px solid #92400e}
.pill-halt{background:#2d0000;color:var(--red);border:1px solid #991b1b;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.topbar-right{margin-left:auto;display:flex;align-items:center;gap:10px}
.ts-label{font-size:.7rem;color:var(--muted)}
.btn-refresh{background:transparent;border:1px solid var(--border);color:var(--muted);
             padding:4px 12px;border-radius:6px;cursor:pointer;font-size:.72rem;
             transition:all .2s}
.btn-refresh:hover{border-color:var(--blue);color:var(--blue)}
#cb-banner{display:none;padding:8px 18px;font-size:.82rem;font-weight:600;
           border-left:3px solid transparent}
.cb-1{display:block!important;background:#1c1400;border-left-color:var(--yellow);color:var(--yellow)}
.cb-2{display:block!important;background:#1a0000;border-left-color:var(--red);color:var(--red)}
.cb-3{display:block!important;background:var(--red);color:#fff;text-align:center}

/* ── Tab Navigation ──────────────────────────────────────────── */
.tab-nav{
  display:flex;background:var(--bg2);border-bottom:1px solid var(--border);
  padding:0 18px;overflow-x:auto;-webkit-overflow-scrolling:touch;
  scrollbar-width:none;
}
.tab-nav::-webkit-scrollbar{display:none}
.tab-btn{
  padding:12px 18px;font-size:.82rem;font-weight:500;color:var(--muted);
  border:none;background:none;cursor:pointer;white-space:nowrap;
  border-bottom:2px solid transparent;transition:all .2s;
  display:flex;align-items:center;gap:5px;
}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
.tab-badge{background:var(--bg3);color:var(--muted);font-size:.6rem;
           padding:1px 6px;border-radius:10px;font-weight:700}
.tab-btn.active .tab-badge{background:rgba(240,185,11,.15);color:var(--accent)}

/* ── Tab Content ─────────────────────────────────────────────── */
.tab-pane{display:none;padding:16px 18px 32px;animation:fadein .2s}
.tab-pane.active{display:block}
@keyframes fadein{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}

/* ── KPI Cards row ───────────────────────────────────────────── */
.kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
.kpi{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.kpi-label{font-size:.65rem;color:var(--muted);text-transform:uppercase;
           letter-spacing:.06em;margin-bottom:6px}
.kpi-val{font-size:1.5rem;font-weight:700;line-height:1}
.kpi-sub{font-size:.7rem;color:var(--muted);margin-top:4px}
.kpi-accent{border-color:rgba(240,185,11,.2)}

/* ── Charts section ──────────────────────────────────────────── */
.chart-row{display:grid;grid-template-columns:2fr 1fr;gap:10px;margin-bottom:14px}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px}
.card-title{font-size:.7rem;color:var(--muted);text-transform:uppercase;
            letter-spacing:.06em;margin-bottom:12px;display:flex;
            align-items:center;justify-content:space-between}

/* ── Stat bar ────────────────────────────────────────────────── */
.stat-row{display:flex;justify-content:space-between;align-items:center;
          font-size:.75rem;padding:3px 0}
.bar-bg{height:4px;border-radius:2px;background:var(--bg3);margin:4px 0 8px;overflow:hidden}
.bar-fill{height:100%;border-radius:2px;transition:width .4s}

/* ── Position Cards (style like the screenshot) ─────────────── */
.positions-grid{display:flex;flex-direction:column;gap:10px}
.pos-card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
          padding:16px;position:relative;overflow:hidden}
.pos-card::before{content:'';position:absolute;top:0;left:0;width:3px;height:100%;border-radius:2px 0 0 2px}
.pos-card.long::before{background:var(--green)}
.pos-card.short::before{background:var(--red)}
.pos-header{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.pos-ticker{font-size:1.05rem;font-weight:700;color:#fff}
.pos-side-badge{font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:4px}
.pos-side-badge.long{background:rgba(14,203,129,.15);color:var(--green);border:1px solid rgba(14,203,129,.3)}
.pos-side-badge.short{background:rgba(246,70,93,.15);color:var(--red);border:1px solid rgba(246,70,93,.3)}
.pos-asset-class{font-size:.65rem;color:var(--muted);margin-left:auto;text-transform:uppercase;letter-spacing:.05em}
.pos-pnl-row{display:flex;align-items:baseline;gap:8px;margin-bottom:12px}
.pos-pnl-abs{font-size:1.4rem;font-weight:700}
.pos-pnl-pct{font-size:.9rem;font-weight:600}
.pos-data-row{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;
              padding:10px;background:var(--bg3);border-radius:8px;margin-bottom:10px}
.pos-data-item{text-align:center}
.pos-data-label{font-size:.58rem;color:var(--muted);text-transform:uppercase;
                letter-spacing:.04em;margin-bottom:3px}
.pos-data-val{font-size:.82rem;font-weight:600;color:var(--text)}
.pos-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pos-btn{padding:7px;border-radius:7px;border:1px solid var(--border);
         font-size:.72rem;font-weight:600;cursor:default;
         background:var(--bg3);color:var(--muted);text-align:center}
.pos-btn.stop{border-color:rgba(246,70,93,.3);color:var(--red);background:rgba(246,70,93,.07)}
.pos-btn.tp{border-color:rgba(14,203,129,.3);color:var(--green);background:rgba(14,203,129,.07)}

/* ── Markets tab ─────────────────────────────────────────────── */
.markets-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px}
.market-group{background:var(--bg2);border:1px solid var(--border);border-radius:10px;
              padding:12px;overflow:hidden}
.market-group-title{font-size:.62rem;font-weight:700;text-transform:uppercase;
                    letter-spacing:.08em;margin-bottom:8px;padding-bottom:6px;
                    border-bottom:1px solid var(--border)}
.market-row{display:flex;align-items:center;padding:5px 0;border-bottom:1px solid var(--border)}
.market-row:last-child{border-bottom:none}
.market-ticker{font-size:.78rem;font-weight:600;width:80px;flex-shrink:0}
.market-name{font-size:.68rem;color:var(--muted);flex:1;overflow:hidden;
             white-space:nowrap;text-overflow:ellipsis}
.market-price{font-size:.78rem;font-weight:600;color:var(--blue);text-align:right;
              flex-shrink:0;min-width:75px}
.market-row.in-pos .market-ticker{color:var(--green)}
.market-row.in-pos{background:rgba(14,203,129,.04);border-radius:5px}

/* ── History tab ─────────────────────────────────────────────── */
.hist-table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th{color:var(--muted);font-weight:600;text-align:left;padding:7px 10px;
   border-bottom:1px solid var(--border);font-size:.65rem;text-transform:uppercase;letter-spacing:.04em}
td{padding:9px 10px;border-bottom:1px solid rgba(30,45,69,.5)}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(26,34,53,.6)}
.no-data{color:var(--muted);text-align:center;padding:28px;font-size:.82rem}

/* ── System tab ──────────────────────────────────────────────── */
.system-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.system-kpi-row{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
.regime-badge{display:inline-flex;align-items:center;gap:6px;
              padding:4px 12px;border-radius:20px;font-size:.8rem;font-weight:700}
.regime-bull{background:rgba(14,203,129,.12);color:var(--green);border:1px solid rgba(14,203,129,.25)}
.regime-neutral{background:rgba(245,158,11,.12);color:var(--yellow);border:1px solid rgba(245,158,11,.25)}
.regime-bear{background:rgba(246,70,93,.12);color:var(--red);border:1px solid rgba(246,70,93,.25)}
.cb-indicator{display:flex;align-items:center;gap:6px}
.cb-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}

/* ── Responsive mobile ───────────────────────────────────────── */
@media(max-width:680px){
  .topbar{padding:8px 12px;padding-top:calc(8px + env(safe-area-inset-top))}
  .topbar-logo{font-size:.9rem}
  #mkt-detail-top{display:none}
  .tab-btn{padding:10px 12px;font-size:.75rem}
  .tab-pane{padding:12px 12px 28px}
  .kpi-row{grid-template-columns:repeat(2,1fr);gap:8px}
  .kpi-val{font-size:1.2rem}
  .chart-row{grid-template-columns:1fr}
  .pos-data-row{grid-template-columns:repeat(2,1fr)}
  .pos-pnl-abs{font-size:1.2rem}
  .markets-grid{grid-template-columns:1fr}
  .system-grid{grid-template-columns:1fr}
  .system-kpi-row{grid-template-columns:repeat(2,1fr)}
  th,td{padding:6px 6px;font-size:.72rem}
}
</style>
</head>
<body>

<!-- ── Top bar ─────────────────────────────────────────────── -->
<div class="topbar">
  <div class="topbar-logo">&#9654; Auto<span>Trader IA</span></div>
  <span class="pill pill-paper">PAPER</span>
  <span class="pill" id="mkt-badge">—</span>
  <span id="mkt-detail-top" style="font-size:.7rem;color:var(--muted)"></span>
  <div class="topbar-right">
    <a href="/backtest" style="color:var(--blue);font-size:.72rem;text-decoration:none">Backtest</a>
    <a href="/logs" style="color:var(--muted);font-size:.72rem;text-decoration:none">Logs</a>
    <span class="ts-label" id="ts">—</span>
    <button class="btn-refresh" onclick="loadData()">&#8635; Actualizar</button>
  </div>
</div>
<div id="cb-banner">&#9888; <span id="cb-msg"></span></div>

<!-- ── Tabs ────────────────────────────────────────────────── -->
<div class="tab-nav">
  <button class="tab-btn active" onclick="showTab('overview',this)">&#128200; Resumen</button>
  <button class="tab-btn" onclick="showTab('positions',this)">&#128203; Posiciones <span class="tab-badge" id="tab-pos-count">0</span></button>
  <button class="tab-btn" onclick="showTab('markets',this)">&#127758; Mercados</button>
  <button class="tab-btn" onclick="showTab('history',this)">&#128196; Historial</button>
  <button class="tab-btn" onclick="showTab('system',this)">&#9881; Sistema</button>
</div>

<!-- ══════════════════════════════════════════════════════════ -->
<!-- TAB 1 — RESUMEN                                           -->
<!-- ══════════════════════════════════════════════════════════ -->
<div class="tab-pane active" id="tab-overview">

  <div class="kpi-row">
    <div class="kpi kpi-accent">
      <div class="kpi-label">Equity Total</div>
      <div class="kpi-val" id="equity">—</div>
      <div class="kpi-sub" id="equity-sub">—</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">PnL Total</div>
      <div class="kpi-val" id="pnl">—</div>
      <div class="kpi-sub" id="pnl-pct">—</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Balance</div>
      <div style="font-size:.78rem;line-height:2;margin-top:2px">
        <div style="display:flex;justify-content:space-between">
          <span class="muted">En posiciones</span>
          <span id="invested" class="blue" style="font-weight:600">—</span>
        </div>
        <div style="display:flex;justify-content:space-between">
          <span class="muted">Cash libre</span>
          <span id="cash" class="green" style="font-weight:600">—</span>
        </div>
        <div class="bar-bg" style="margin-top:6px">
          <div id="invest-bar" class="bar-fill" style="background:var(--blue);width:0%"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:.65rem;color:var(--muted)">
          <span id="invest-pct">—</span><span id="cash-pct">—</span>
        </div>
      </div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Operaciones</div>
      <div class="kpi-val" id="trades" style="font-size:1.3rem">—</div>
      <div style="margin-top:8px">
        <div class="stat-row">
          <span class="green" style="font-size:.72rem">&#9650; Ganadoras</span>
          <span id="wins-count" class="green" style="font-weight:700;font-size:.82rem">—</span>
        </div>
        <div class="stat-row">
          <span class="red" style="font-size:.72rem">&#9660; Perdedoras</span>
          <span id="losses-count" class="red" style="font-weight:700;font-size:.82rem">—</span>
        </div>
        <div class="bar-bg">
          <div class="bar-fill" id="winrate-bar" style="background:var(--green);width:0%"></div>
        </div>
        <div class="stat-row" style="font-size:.68rem">
          <span class="muted">Win rate</span>
          <span id="winrate-label" style="font-weight:600">—</span>
        </div>
      </div>
    </div>
  </div>

  <div class="chart-row">
    <div class="card">
      <div class="card-title">
        <span>Equity Curve ({{ currency }})</span>
        <span id="equity-change" style="font-size:.78rem;font-weight:700"></span>
      </div>
      <div id="equity-chart" style="height:220px"></div>
    </div>
    <div class="card">
      <div class="card-title">
        <span>Allocacion</span>
        <span id="pos-count-ov" class="muted" style="font-size:.72rem"></span>
      </div>
      <div id="pie-chart" style="height:220px"></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">
      <span>PnL Acumulado ({{ currency }})</span>
      <span id="pnl-total-label" style="font-size:.82rem;font-weight:700"></span>
    </div>
    <div id="pnl-chart" style="height:150px"></div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════ -->
<!-- TAB 2 — POSICIONES                                        -->
<!-- ══════════════════════════════════════════════════════════ -->
<div class="tab-pane" id="tab-positions">
  <div id="pos-summary-bar" style="display:flex;gap:16px;margin-bottom:12px;
       padding:10px 14px;background:var(--bg2);border:1px solid var(--border);
       border-radius:10px;flex-wrap:wrap">
    <div>
      <div class="kpi-label">Posiciones abiertas</div>
      <div style="font-size:1.1rem;font-weight:700" id="ps-count">—</div>
    </div>
    <div style="border-left:1px solid var(--border);padding-left:16px">
      <div class="kpi-label">Valor total</div>
      <div style="font-size:1.1rem;font-weight:700;color:var(--blue)" id="ps-value">—</div>
    </div>
    <div style="border-left:1px solid var(--border);padding-left:16px">
      <div class="kpi-label">PnL no realizado</div>
      <div style="font-size:1.1rem;font-weight:700" id="ps-pnl">—</div>
    </div>
    <div style="border-left:1px solid var(--border);padding-left:16px">
      <div class="kpi-label">Long / Short</div>
      <div style="font-size:.9rem;font-weight:700" id="ps-sides">—</div>
    </div>
  </div>
  <div class="positions-grid" id="positions-cards"></div>
</div>

<!-- ══════════════════════════════════════════════════════════ -->
<!-- TAB 3 — MERCADOS                                          -->
<!-- ══════════════════════════════════════════════════════════ -->
<div class="tab-pane" id="tab-markets">
  <div class="markets-grid" id="markets-grid"></div>
</div>

<!-- ══════════════════════════════════════════════════════════ -->
<!-- TAB 4 — HISTORIAL                                         -->
<!-- ══════════════════════════════════════════════════════════ -->
<div class="tab-pane" id="tab-history">
  <div class="card" style="margin-bottom:12px">
    <div class="card-title">
      <span>PnL Acumulado</span>
      <span id="hist-pnl-label" style="font-size:.82rem;font-weight:700"></span>
    </div>
    <div id="hist-pnl-chart" style="height:140px"></div>
  </div>
  <div class="card">
    <div class="card-title">Ultimas Operaciones</div>
    <div class="hist-table-wrap" id="trades-table"></div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════ -->
<!-- TAB 5 — SISTEMA                                           -->
<!-- ══════════════════════════════════════════════════════════ -->
<div class="tab-pane" id="tab-system">

  <div class="system-kpi-row">
    <div class="kpi">
      <div class="kpi-label">Regimen de Mercado</div>
      <div style="margin-top:6px" id="regime-badge-wrap">—</div>
      <div class="kpi-sub" id="regime-detail" style="margin-top:6px">—</div>
      <div class="kpi-sub" id="regime-vix" style="margin-top:2px">—</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Proteccion Capital</div>
      <div class="cb-indicator" style="margin-top:6px">
        <div class="cb-dot" id="cb-dot" style="background:var(--green)"></div>
        <span style="font-size:1rem;font-weight:700" id="cb-label">OK</span>
      </div>
      <div class="kpi-sub" id="cb-sub" style="margin-top:4px">—</div>
      <div style="font-size:.65rem;color:var(--muted);margin-top:6px;line-height:1.7">
        Aviso: -{{ warn_pct }} &nbsp;|&nbsp; Reduccion: -{{ reduce_pct }} &nbsp;|&nbsp; HALT: -{{ halt_pct }}
      </div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Avg Ganadora / Perdedora</div>
      <div style="margin-top:8px">
        <div class="stat-row">
          <span class="muted" style="font-size:.72rem">Avg Win</span>
          <span id="avg-win" class="green" style="font-weight:700">—</span>
        </div>
        <div class="stat-row">
          <span class="muted" style="font-size:.72rem">Avg Loss</span>
          <span id="avg-loss" class="red" style="font-weight:700">—</span>
        </div>
        <div class="stat-row" style="margin-top:4px">
          <span class="muted" style="font-size:.72rem">Ratio R:R</span>
          <span id="rr-ratio" class="blue" style="font-weight:700">—</span>
        </div>
      </div>
    </div>
  </div>

  <div class="system-grid">
    <div class="card">
      <div class="card-title">&#9203; Cooldowns Activos</div>
      <div id="cooldowns-table"></div>
    </div>
    <div class="card">
      <div class="card-title">&#128270; Screener — Candidatos</div>
      <div id="screener-table"></div>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════ -->
<!-- JAVASCRIPT                                                -->
<!-- ══════════════════════════════════════════════════════════ -->
<script>
const SYM = "{{ sym }}";
const INITIAL_USD = {{ initial_usd }};
const INITIAL = {{ initial_display }};
const RATE = {{ rate }};

/* ── Helpers ──────────────────────────────────────────────── */
function fmt(usd,d=2){
  const v=usd*RATE;
  return SYM+v.toLocaleString('es-ES',{minimumFractionDigits:d,maximumFractionDigits:d});
}
function fmtP(p){
  const v=p*RATE;
  if(p<1) return SYM+v.toLocaleString('es-ES',{minimumFractionDigits:4,maximumFractionDigits:4});
  if(p<10) return SYM+v.toLocaleString('es-ES',{minimumFractionDigits:3,maximumFractionDigits:3});
  return SYM+v.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2});
}
function fmtPct(n){return(n>=0?'+':'')+(n*100).toFixed(2)+'%'}
function cc(n){return n>=0?'green':'red'}
function layoutDark(extra){
  return Object.assign({
    paper_bgcolor:'#111827',plot_bgcolor:'#111827',
    font:{color:'#94a3b8',size:10},
    margin:{t:8,b:28,l:48,r:8},
    xaxis:{gridcolor:'#1e2d45',tickfont:{size:9}},
    yaxis:{gridcolor:'#1e2d45',tickfont:{size:9}},
    showlegend:false
  },extra);
}

/* ── Tab system ───────────────────────────────────────────── */
function showTab(id,btn){
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  btn.classList.add('active');
}

/* ── Ticker metadata ──────────────────────────────────────── */
const TICKER_NAMES={
  'AAPL':'Apple','MSFT':'Microsoft','GOOGL':'Alphabet','NVDA':'NVIDIA',
  'META':'Meta','AMZN':'Amazon','TSLA':'Tesla','AMD':'AMD',
  'NFLX':'Netflix','ORCL':'Oracle','JPM':'JPMorgan','BAC':'Bank of America',
  'GS':'Goldman Sachs','BRK-B':'Berkshire','XOM':'ExxonMobil','CVX':'Chevron',
  'JNJ':'J&J','UNH':'UnitedHealth','WMT':'Walmart','HD':'Home Depot',
  'SPY':'ETF S&P 500','QQQ':'ETF Nasdaq 100','IWM':'ETF Russell 2000',
  'XLK':'ETF Tech','XLF':'ETF Financials','XLE':'ETF Energia',
  'XLV':'ETF Salud','XLI':'ETF Industrial','XLU':'ETF Utilities',
  'XLP':'ETF Consumer','GLD':'ETF Oro','SLV':'ETF Plata',
  'USO':'ETF Petroleo','TLT':'ETF Bonos LP',
  'SH':'Inv S&P x1','PSQ':'Inv Nasdaq x1','SDS':'Inv S&P x2','SQQQ':'Inv Nasdaq x3',
  'BTC-USD':'Bitcoin','ETH-USD':'Ethereum','SOL-USD':'Solana',
  'BNB-USD':'Binance Coin','XRP-USD':'XRP','AVAX-USD':'Avalanche','LINK-USD':'Chainlink',
  'GC=F':'Oro Futuros','CL=F':'WTI Futuros','SI=F':'Plata Futuros',
  'EFA':'Mercados Desarrollados','EEM':'Mercados Emergentes',
};
const ASSET_CLASS={
  'BTC-USD':'Crypto','ETH-USD':'Crypto','SOL-USD':'Crypto','BNB-USD':'Crypto',
  'XRP-USD':'Crypto','AVAX-USD':'Crypto','LINK-USD':'Crypto',
  'GC=F':'Commodity','CL=F':'Commodity','SI=F':'Commodity',
  'SH':'ETF Inv','PSQ':'ETF Inv','SDS':'ETF Inv','SQQQ':'ETF Inv',
};
function assetClass(t){
  if(ASSET_CLASS[t]) return ASSET_CLASS[t];
  if(t.endsWith('-USD')) return 'Crypto';
  if(t.includes('=F')) return 'Commodity';
  if(['SPY','QQQ','IWM','XLK','XLF','XLE','XLV','XLI','XLU','XLP','GLD','SLV','USO','TLT','EFA','EEM'].includes(t)) return 'ETF';
  return 'Stock';
}

const PRICE_GROUPS=[
  {name:'US Tech',color:'#3b82f6',tickers:['AAPL','MSFT','GOOGL','NVDA','META','AMZN','TSLA','AMD','NFLX','ORCL']},
  {name:'Financials / Health',color:'#0ecb81',tickers:['JPM','BAC','GS','BRK-B','JNJ','UNH','WMT','HD']},
  {name:'ETFs Amplios',color:'#a855f7',tickers:['SPY','QQQ','IWM','GLD','SLV','TLT']},
  {name:'ETFs Sectoriales',color:'#06b6d4',tickers:['XLK','XLF','XLE','XLV','XLI','XLU','XLP']},
  {name:'ETFs Inversos',color:'#f6465d',tickers:['SH','PSQ','SDS','SQQQ']},
  {name:'Crypto 24/7',color:'#f0b90b',tickers:['BTC-USD','ETH-USD','SOL-USD','BNB-USD','XRP-USD','AVAX-USD','LINK-USD']},
  {name:'Commodities',color:'#f59e0b',tickers:['GC=F','CL=F','SI=F']},
  {name:'Internacional',color:'#7ee787',tickers:['EFA','EEM']},
];

const CB_COLORS=['#0ecb81','#f59e0b','#f6465d','#f6465d'];
const CB_LABELS=['OK','AVISO','REDUCCION','HALT'];

/* ── Main render ──────────────────────────────────────────── */
function loadData(){
  fetch('/api/data').then(r=>r.json()).then(d=>{
    document.getElementById('ts').textContent=new Date().toLocaleTimeString('es-ES');

    /* Market badge */
    const mb=document.getElementById('mkt-badge');
    mb.textContent=d.market.status;
    mb.className='pill '+(d.market.open?'pill-open':'pill-closed');
    document.getElementById('mkt-detail-top').textContent=d.market.et_time;

    /* Circuit breaker */
    const cb=d.circuit_breaker;
    const banner=document.getElementById('cb-banner');
    banner.className=cb.level>0?'cb-'+cb.level:'';
    banner.style.display=cb.level>0?'block':'none';
    document.getElementById('cb-msg').textContent=cb.reason;
    document.getElementById('cb-dot').style.background=CB_COLORS[cb.level];
    document.getElementById('cb-label').textContent=CB_LABELS[cb.level];
    document.getElementById('cb-label').style.color=CB_COLORS[cb.level];
    document.getElementById('cb-sub').textContent=
      'Drawdown: '+fmtPct(cb.drawdown_pct)+
      '  |  Dia: '+fmtPct(cb.daily_loss_pct)+
      '  |  Rachas: '+cb.consecutive_losses;

    /* KPI cards (Overview) */
    const eq=d.equity, pnl=eq-INITIAL_USD, pct=pnl/INITIAL_USD;
    document.getElementById('equity').innerHTML=`<span class="${cc(pnl)}">${fmt(eq)}</span>`;
    document.getElementById('equity-sub').textContent='Inicial: '+fmt(INITIAL_USD);
    document.getElementById('pnl').innerHTML=`<span class="${cc(pnl)}">${fmt(pnl)}</span>`;
    document.getElementById('pnl-pct').innerHTML=`<span class="${cc(pnl)}">${fmtPct(pct)}</span>`;
    document.getElementById('equity-change').innerHTML=
      `<span class="${cc(pnl)}">${pnl>=0?'+':''}${(pct*100).toFixed(2)}%</span>`;

    const cash=d.cash, inv=eq-cash;
    document.getElementById('invested').textContent=fmt(inv);
    document.getElementById('cash').textContent=fmt(cash);
    const ip=eq>0?(inv/eq*100).toFixed(1):0, cp=eq>0?(cash/eq*100).toFixed(1):100;
    document.getElementById('invest-bar').style.width=ip+'%';
    document.getElementById('invest-pct').textContent='Pos: '+ip+'%';
    document.getElementById('cash-pct').textContent='Cash: '+cp+'%';

    const st=d.stats, tot=st.total_trades;
    const nw=Math.round(tot*st.win_rate), nl=tot-nw;
    document.getElementById('trades').textContent=tot>0?tot+' cerradas':'—';
    document.getElementById('wins-count').textContent=tot>0?nw:'—';
    document.getElementById('losses-count').textContent=tot>0?nl:'—';
    document.getElementById('winrate-bar').style.width=tot>0?(st.win_rate*100).toFixed(1)+'%':'0%';
    document.getElementById('winrate-bar').style.background=st.win_rate>=0.5?'var(--green)':'var(--red)';
    document.getElementById('winrate-label').innerHTML=
      `<span class="${st.win_rate>=0.5?'green':'red'}">${tot>0?(st.win_rate*100).toFixed(1)+'%':'—'}</span>`;

    /* Avg win/loss + R:R */
    document.getElementById('avg-win').textContent=st.avg_win?fmt(st.avg_win):'—';
    document.getElementById('avg-loss').textContent=st.avg_loss?fmt(st.avg_loss):'—';
    const rr=st.avg_win&&st.avg_loss?Math.abs(st.avg_win/st.avg_loss):null;
    document.getElementById('rr-ratio').textContent=rr?rr.toFixed(2)+'x':'—';

    /* Tab badge */
    document.getElementById('tab-pos-count').textContent=d.positions.length;

    /* ── Equity chart ─────────────────────────────── */
    if(d.snapshots.length>1){
      Plotly.react('equity-chart',[
        {x:d.snapshots.map(s=>s.date),y:d.snapshots.map(s=>s.equity*RATE),
         type:'scatter',mode:'lines',name:'Equity',
         line:{color:'#3b82f6',width:2.5},fill:'tozeroy',fillcolor:'rgba(59,130,246,0.07)'},
        {x:d.snapshots.map(s=>s.date),y:d.snapshots.map(()=>INITIAL),
         type:'scatter',mode:'lines',name:'Inicial',
         line:{color:'#475569',width:1,dash:'dot'}}
      ],layoutDark({yaxis:{tickprefix:SYM}}),{responsive:true,displayModeBar:false});
    } else {
      document.getElementById('equity-chart').innerHTML='<p class="no-data">Grafico disponible tras el primer dia de operaciones</p>';
    }

    /* ── Allocation pie ───────────────────────────── */
    document.getElementById('pos-count-ov').textContent=
      d.positions.length>0?d.positions.length+' posiciones abiertas':'';
    if(d.positions.length>0){
      const pieColors=['#3b82f6','#0ecb81','#f0b90b','#f6465d','#a855f7','#f59e0b','#06b6d4','#7ee787'];
      Plotly.react('pie-chart',[{
        labels:d.positions.map(p=>p.ticker),
        values:d.positions.map(p=>{
          const pr=d.prices[p.ticker]||p.avg_price;
          return p.side==='SHORT'?p.qty*(2*p.avg_price-pr):p.qty*pr;
        }),
        type:'pie',hole:0.45,textinfo:'label+percent',
        marker:{colors:pieColors},
        textfont:{size:10}
      }],layoutDark({margin:{t:8,b:8,l:8,r:8}}),{responsive:true,displayModeBar:false});
    } else {
      document.getElementById('pie-chart').innerHTML='<p class="no-data">Sin posiciones abiertas</p>';
    }

    /* ── PnL cumulative chart (overview) ──────────── */
    renderPnlChart('pnl-chart','pnl-total-label',d.trades);

    /* ── Positions tab ────────────────────────────── */
    renderPositions(d.positions, d.prices);

    /* ── Markets tab ──────────────────────────────── */
    renderMarkets(d.prices, d.positions);

    /* ── History tab ──────────────────────────────── */
    renderPnlChart('hist-pnl-chart','hist-pnl-label',d.trades);
    renderTradesTable(d.trades);

    /* ── System tab ───────────────────────────────── */
    renderRegime(d.regime);
    renderCooldowns(d.cooldowns);
    renderScreener(d.screener);
  });
}

/* ── Position Cards ───────────────────────────────────────── */
function renderPositions(positions, prices){
  const container=document.getElementById('positions-cards');
  document.getElementById('tab-pos-count').textContent=positions.length;

  /* summary bar */
  const totalVal=positions.reduce((s,p)=>{
    const pr=prices[p.ticker]||p.avg_price;
    return s+(p.side==='SHORT'?p.qty*(2*p.avg_price-pr):p.qty*pr);
  },0);
  const totalPnl=positions.reduce((s,p)=>{
    const pr=prices[p.ticker]||p.avg_price;
    return s+(p.side==='LONG'?pr-p.avg_price:(p.avg_price-pr))*p.qty;
  },0);
  const longs=positions.filter(p=>(p.side||'LONG')==='LONG').length;
  const shorts=positions.filter(p=>p.side==='SHORT').length;
  document.getElementById('ps-count').textContent=positions.length||'—';
  document.getElementById('ps-value').textContent=positions.length?fmt(totalVal):'—';
  document.getElementById('ps-pnl').innerHTML=positions.length?
    `<span class="${cc(totalPnl)}">${fmt(totalPnl)}</span>`:'—';
  document.getElementById('ps-sides').innerHTML=positions.length?
    `<span class="green">${longs}L</span> / <span class="red">${shorts}S</span>`:'—';

  if(!positions.length){
    container.innerHTML='<div class="no-data" style="padding:40px">Sin posiciones abiertas — el bot esta escaneando el mercado...</div>';
    return;
  }
  container.innerHTML=positions.map(p=>{
    const pr=prices[p.ticker]||p.avg_price;
    const side=(p.side||'LONG');
    const pnl=side==='LONG'?(pr-p.avg_price)*p.qty:(p.avg_price-pr)*p.qty;
    const pct=side==='LONG'?(pr/p.avg_price-1)*100:(p.avg_price/pr-1)*100;
    const coste=p.qty*p.avg_price;
    const ac=assetClass(p.ticker);
    const pnlClass=pnl>=0?'green':'red';

    return `<div class="pos-card ${side.toLowerCase()}">
      <div class="pos-header">
        <span class="pos-ticker">${p.ticker}</span>
        <span class="pos-side-badge ${side.toLowerCase()}">${side==='LONG'?'&#9650; Long':'&#9660; Short'}</span>
        <span class="pos-asset-class">${ac}</span>
      </div>
      <div class="pos-pnl-row">
        <span class="pos-pnl-abs ${pnlClass}">${fmt(pnl)}</span>
        <span class="pos-pnl-pct ${pnlClass}">(${pct>=0?'+':''}${pct.toFixed(2)}%)</span>
      </div>
      <div class="pos-data-row">
        <div class="pos-data-item">
          <div class="pos-data-label">Cantidad</div>
          <div class="pos-data-val">${p.qty%1===0?p.qty:p.qty.toFixed(p.qty<0.01?6:4)}</div>
        </div>
        <div class="pos-data-item">
          <div class="pos-data-label">Precio Entrada</div>
          <div class="pos-data-val">${fmtP(p.avg_price)}</div>
        </div>
        <div class="pos-data-item">
          <div class="pos-data-label">Precio Actual</div>
          <div class="pos-data-val ${pnlClass}">${fmtP(pr)}</div>
        </div>
        <div class="pos-data-item">
          <div class="pos-data-label">Valor Total</div>
          <div class="pos-data-val blue">${fmt(coste)}</div>
        </div>
      </div>
      <div class="pos-actions">
        <div class="pos-btn stop">
          Stop Loss: ${p.stop_loss?fmtP(p.stop_loss):'—'}
        </div>
        <div class="pos-btn tp">
          Take Profit: ${p.take_profit?fmtP(p.take_profit):'—'}
        </div>
      </div>
    </div>`;
  }).join('');
}

/* ── Markets ──────────────────────────────────────────────── */
function renderMarkets(prices, positions){
  const posSet=new Set(positions.map(p=>p.ticker));
  document.getElementById('markets-grid').innerHTML=PRICE_GROUPS.map(g=>{
    const rows=g.tickers.filter(t=>prices[t]!==undefined);
    if(!rows.length) return '';
    return `<div class="market-group">
      <div class="market-group-title" style="color:${g.color}">${g.name}</div>
      ${rows.map(t=>{
        const inPos=posSet.has(t);
        return `<div class="market-row${inPos?' in-pos':''}">
          <span class="market-ticker">${t}${inPos?' ●':''}</span>
          <span class="market-name">${TICKER_NAMES[t]||''}</span>
          <span class="market-price">${fmtP(prices[t])}</span>
        </div>`;
      }).join('')}
    </div>`;
  }).join('');
}

/* ── PnL chart (reusable) ─────────────────────────────────── */
function renderPnlChart(chartId, labelId, trades){
  const closed=[...trades].filter(t=>['SELL','COVER'].includes(t.side)&&t.pnl!=null).reverse();
  if(closed.length>0){
    let cum=0;
    const Y=closed.map(t=>{cum+=t.pnl*RATE;return +cum.toFixed(2)});
    const X=closed.map((t,i)=>(i+1)+'. '+t.ticker);
    const fin=Y[Y.length-1];
    const lc=fin>=0?'#0ecb81':'#f6465d';
    const fc=fin>=0?'rgba(14,203,129,0.1)':'rgba(246,70,93,0.1)';
    document.getElementById(labelId).innerHTML=
      `<span class="${fin>=0?'green':'red'}">${fin>=0?'+':''}${SYM}${Math.abs(fin).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})}</span>`;
    Plotly.react(chartId,[
      {x:X,y:Y,type:'scatter',mode:'lines+markers',
       line:{color:lc,width:2},fill:'tozeroy',fillcolor:fc,
       marker:{size:5,color:closed.map(t=>t.pnl>=0?'#0ecb81':'#f6465d')}},
      {x:[X[0],X[X.length-1]],y:[0,0],type:'scatter',mode:'lines',
       line:{color:'#334155',width:1,dash:'dot'},hoverinfo:'none'}
    ],layoutDark({margin:{t:8,b:44,l:48,r:8},yaxis:{tickprefix:SYM},xaxis:{tickangle:-30}}),
    {responsive:true,displayModeBar:false});
  } else {
    document.getElementById(chartId).innerHTML='<p class="no-data">PnL acumulado aparecera al cerrar operaciones</p>';
    if(labelId) document.getElementById(labelId).textContent='';
  }
}

/* ── Trades table ─────────────────────────────────────────── */
function renderTradesTable(trades){
  const div=document.getElementById('trades-table');
  if(!trades.length){div.innerHTML='<p class="no-data">Sin operaciones aun</p>';return}
  div.innerHTML=`<table>
    <tr><th>Fecha</th><th>Ticker</th><th>Tipo</th>
        <th style="text-align:right">Total</th><th style="text-align:right">PnL</th><th>Motivo</th></tr>`+
  trades.slice(0,30).map(t=>{
    const pnlStr=t.pnl!=null?`<span class="${cc(t.pnl)}" style="font-weight:700">${fmt(t.pnl)}</span>`:'—';
    const isBuy=['BUY','COVER'].includes(t.side);
    const sideColor=isBuy?'var(--green)':'var(--red)';
    return `<tr>
      <td style="font-size:.65rem;color:var(--muted);white-space:nowrap">${t.executed_at.slice(5,16)}</td>
      <td><strong>${t.ticker}</strong></td>
      <td><span style="color:${sideColor};font-weight:700;font-size:.72rem">${t.side}</span></td>
      <td style="text-align:right;color:var(--muted)">${fmt(t.qty*t.price)}</td>
      <td style="text-align:right">${pnlStr}</td>
      <td style="font-size:.65rem;color:var(--muted)">${(t.reason||'').slice(0,20)}</td>
    </tr>`;
  }).join('')+'</table>';
}

/* ── Regime ───────────────────────────────────────────────── */
function renderRegime(reg){
  if(!reg) return;
  const cls={bull:'regime-bull',neutral:'regime-neutral',bear:'regime-bear'};
  const lbl={bull:'&#128994; BULL',neutral:'&#128993; NEUTRAL',bear:'&#128308; BEAR'};
  document.getElementById('regime-badge-wrap').innerHTML=
    `<span class="regime-badge ${cls[reg.regime]||''}">${lbl[reg.regime]||reg.regime.toUpperCase()}</span>`;
  document.getElementById('regime-detail').textContent=
    `SPY: ${reg.spy_vs_sma200>=0?'+':''}${reg.spy_vs_sma200}% vs SMA200`;
  document.getElementById('regime-vix').textContent=
    `VIX=${reg.vix}  |  Mult LONG x${reg.long_mult}  |  SHORT x${reg.short_mult}`;
}

/* ── Cooldowns ────────────────────────────────────────────── */
function renderCooldowns(cooldowns){
  const div=document.getElementById('cooldowns-table');
  if(!cooldowns||!cooldowns.length){
    div.innerHTML='<p class="no-data">Sin cooldowns activos</p>';return;
  }
  div.innerHTML=`<table><tr><th>Ticker</th><th>Motivo</th><th>Hasta (UTC)</th></tr>`+
    cooldowns.map(c=>`<tr>
      <td><strong>${c.ticker}</strong>
          <span style="font-size:.65rem;color:var(--muted);display:block">${(TICKER_NAMES[c.ticker]||'').slice(0,20)}</span>
      </td>
      <td style="color:var(--yellow);font-size:.72rem">${c.reason}</td>
      <td style="font-size:.65rem;color:var(--muted);white-space:nowrap">${c.blocked_until.slice(5,16)}</td>
    </tr>`).join('')+'</table>';
}

/* ── Screener ─────────────────────────────────────────────── */
function renderScreener(screener){
  const div=document.getElementById('screener-table');
  if(!screener||!screener.length){
    div.innerHTML='<p class="no-data">Sin datos (activo con NYSE abierto)</p>';return;
  }
  div.innerHTML=`<table><tr><th>Ticker</th><th style="text-align:right">Score</th>
    <th style="text-align:right">Vol</th><th style="text-align:right">Mom 1d</th></tr>`+
  screener.map(s=>`<tr>
    <td><strong>${s.ticker}</strong></td>
    <td style="text-align:right;color:var(--blue)">${(s.score*100).toFixed(0)}</td>
    <td style="text-align:right">${s.vol_ratio?s.vol_ratio.toFixed(1)+'x':'—'}</td>
    <td style="text-align:right" class="${s.momentum>=0?'green':'red'}">
      ${s.momentum>=0?'+':''}${(s.momentum*100).toFixed(1)}%
    </td>
  </tr>`).join('')+'</table>';
}

/* ── Init ─────────────────────────────────────────────────── */
loadData();
setInterval(loadData,30000);
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

    invested = sum(
        p["qty"] * current_prices.get(p["ticker"], p["avg_price"])
        for p in positions if p.get("side", "LONG") == "LONG"
    )

    return jsonify({
        "equity": round(equity, 2),
        "cash": round(risk["cash"], 2),
        "invested": round(invested, 2),
        "positions": positions,
        "trades": trades,
        "stats": stats,
        "prices": {k: round(v, 4) for k, v in current_prices.items()},
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
  <select id="ticker" style="width:220px">
    <optgroup label="US Tech">
      <option value="AAPL">AAPL — Apple</option>
      <option value="MSFT">MSFT — Microsoft</option>
      <option value="GOOGL">GOOGL — Alphabet</option>
      <option value="NVDA">NVDA — NVIDIA</option>
      <option value="META">META — Meta</option>
      <option value="AMZN">AMZN — Amazon</option>
      <option value="TSLA">TSLA — Tesla</option>
      <option value="AMD">AMD</option>
      <option value="NFLX">NFLX — Netflix</option>
      <option value="ORCL">ORCL — Oracle</option>
    </optgroup>
    <optgroup label="US Financials">
      <option value="JPM">JPM — JPMorgan</option>
      <option value="BAC">BAC — Bank of America</option>
      <option value="GS">GS — Goldman Sachs</option>
      <option value="BRK-B">BRK-B — Berkshire</option>
    </optgroup>
    <optgroup label="US Energy / Health / Consumer">
      <option value="XOM">XOM — Exxon</option>
      <option value="CVX">CVX — Chevron</option>
      <option value="JNJ">JNJ — J&amp;J</option>
      <option value="UNH">UNH — UnitedHealth</option>
      <option value="WMT">WMT — Walmart</option>
      <option value="HD">HD — Home Depot</option>
    </optgroup>
    <optgroup label="ETFs">
      <option value="SPY">SPY — S&amp;P 500</option>
      <option value="QQQ">QQQ — Nasdaq 100</option>
      <option value="IWM">IWM — Russell 2000</option>
      <option value="XLK">XLK — Tech ETF</option>
      <option value="XLF">XLF — Financials ETF</option>
      <option value="XLE">XLE — Energy ETF</option>
      <option value="XLV">XLV — Health ETF</option>
      <option value="GLD">GLD — Oro ETF</option>
      <option value="SLV">SLV — Plata ETF</option>
      <option value="USO">USO — Petróleo ETF</option>
    </optgroup>
    <optgroup label="Crypto (24/7)">
      <option value="BTC-USD">BTC-USD — Bitcoin</option>
      <option value="ETH-USD">ETH-USD — Ethereum</option>
      <option value="SOL-USD">SOL-USD — Solana</option>
    </optgroup>
    <optgroup label="Commodities (futuros CME)">
      <option value="GC=F">GC=F — Oro futuros</option>
      <option value="CL=F">CL=F — Petróleo WTI</option>
      <option value="SI=F">SI=F — Plata futuros</option>
    </optgroup>
    <optgroup label="Internacional">
      <option value="EFA">EFA — Mercados desarrollados</option>
      <option value="EEM">EEM — Mercados emergentes</option>
    </optgroup>
  </select>
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
  const ticker = document.getElementById('ticker').value;
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
document.getElementById('ticker').addEventListener('change', () => runBacktest());
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
    import html as _html
    from pathlib import Path
    log_path = Path("logs/autotrader.log")
    if not log_path.exists():
        raw_lines = ["(sin logs todavia)"]
    else:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()[-300:]

    def _classify(line):
        if any(k in line for k in ("[ERROR]", "[CRITICAL]", "ERROR", "CRITICAL")):
            return "error"
        if any(k in line for k in ("[WARNING]", "WARNING", "WARN")):
            return "warn"
        if any(k in line for k in ("BUY", "SELL", "SHORT", "COVER", "OPEN", "CLOSE", "TRADE")):
            return "trade"
        if any(k in line for k in ("[INFO]", "INFO")):
            return "info"
        return "muted"

    lines_html = ""
    for l in raw_lines:
        cls = _classify(l)
        escaped = _html.escape(l.rstrip())
        lines_html += f'<div class="log-line {cls}">{escaped}</div>\n'

    page = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>AutoTrader — Logs</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', sans-serif;
       padding-bottom: env(safe-area-inset-bottom); }}
header {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 12px 20px;
          padding-top: calc(12px + env(safe-area-inset-top));
          display: flex; align-items: center; gap: 14px; position: sticky; top: 0; z-index: 10; }}
header a {{ color: #58a6ff; text-decoration: none; font-size: .85rem; }}
header h1 {{ font-size: 1rem; color: #c9d1d9; }}
.filters {{ display: flex; gap: 8px; flex-wrap: wrap; padding: 10px 20px;
            background: #161b22; border-bottom: 1px solid #30363d; }}
.filter-btn {{ background: #21262d; border: 1px solid #30363d; color: #8b949e;
               padding: 4px 12px; border-radius: 20px; cursor: pointer; font-size: .75rem;
               transition: all .15s; }}
.filter-btn.active {{ border-color: #58a6ff; color: #58a6ff; background: #0d2137; }}
.filter-btn.f-error.active  {{ border-color: #f85149; color: #f85149; background: #200d0d; }}
.filter-btn.f-warn.active   {{ border-color: #f0a030; color: #f0a030; background: #1f1500; }}
.filter-btn.f-trade.active  {{ border-color: #3fb950; color: #3fb950; background: #0d1f10; }}
#log-container {{ padding: 12px 20px; font-family: 'Cascadia Code','Consolas',monospace;
                  font-size: .76rem; line-height: 1.5; }}
.log-line {{ padding: 4px 8px; border-radius: 3px; white-space: pre-wrap; word-break: break-word;
             border-bottom: 1px solid rgba(48,54,61,0.5); margin-bottom: 1px; }}
.log-line.error {{ color: #f85149; background: rgba(248,81,73,.10); border-left: 3px solid #f85149; }}
.log-line.warn  {{ color: #f0a030; background: rgba(240,160,48,.08); border-left: 3px solid #f0a030; }}
.log-line.trade {{ color: #3fb950; background: rgba(63,185,80,.08); border-left: 3px solid #3fb950; }}
.log-line.info  {{ color: #79c0ff; border-left: 3px solid rgba(88,166,255,.3); }}
.log-line.muted {{ color: #6e7681; border-left: 3px solid transparent; }}
.badge-count {{ font-size: .68rem; background: #30363d; padding: 1px 6px; border-radius: 10px; margin-left: 4px; }}
#scroll-btn {{ position: fixed; bottom: calc(20px + env(safe-area-inset-bottom));
               right: 20px; background: #238636; color: #fff; border: none; border-radius: 50%;
               width: 40px; height: 40px; font-size: 1.1rem; cursor: pointer; box-shadow: 0 2px 8px #0006; }}
@media (max-width:600px) {{
  header {{ padding: 10px 14px; padding-top: calc(10px + env(safe-area-inset-top)); }}
  #log-container {{ padding: 8px 10px; font-size: .72rem; line-height: 1.55; }}
  .log-line {{ padding: 5px 8px; word-break: break-word; }}
  .filters {{ padding: 8px 14px; }}
}}
</style>
</head>
<body>
<header>
  <a href="/">&larr; Dashboard</a>
  <h1>&#128196; Logs del sistema</h1>
  <span style="margin-left:auto;font-size:.72rem;color:#8b949e" id="auto-label">Auto-refresh: 30s</span>
</header>
<div class="filters">
  <button class="filter-btn active" onclick="setFilter('all',this)">Todos</button>
  <button class="filter-btn f-error" onclick="setFilter('error',this)">&#128308; Errores</button>
  <button class="filter-btn f-warn" onclick="setFilter('warn',this)">&#128993; Avisos</button>
  <button class="filter-btn f-trade" onclick="setFilter('trade',this)">&#128994; Trades</button>
  <button class="filter-btn" onclick="setFilter('info',this)">&#128309; Info</button>
</div>
<div id="log-container">
{lines_html}
</div>
<button id="scroll-btn" onclick="window.scrollTo({{top:document.body.scrollHeight,behavior:'smooth'}})">&#8595;</button>
<script>
let currentFilter = 'all';
function setFilter(f, btn) {{
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.log-line').forEach(el => {{
    el.style.display = (f === 'all' || el.classList.contains(f)) ? '' : 'none';
  }});
}}
// auto-refresh
let countdown = 30;
setInterval(() => {{
  countdown--;
  document.getElementById('auto-label').textContent = 'Auto-refresh: ' + countdown + 's';
  if (countdown <= 0) location.reload();
}}, 1000);
// scroll to bottom on load
window.scrollTo(0, document.body.scrollHeight);
</script>
</body>
</html>"""
    return page


if __name__ == "__main__":
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    init_db()
    print("Abriendo dashboard en http://localhost:5000 ...")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
