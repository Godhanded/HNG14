"""
dashboard.py — Live Metrics Web Dashboard

Serves a single-page dashboard that auto-refreshes every 3 seconds.
Built with Flask (Python) + vanilla JS + Chart.js for the baseline graph.

The page has two parts:
  1. The HTML/JS frontend — a dark-themed page with live metrics cards,
     a banned IPs table, a top-10 IPs table, and a baseline history graph.
  2. A /api/metrics JSON endpoint — the JS polls this every 3 seconds and
     updates the DOM without a full page reload.

Your host Nginx should proxy your monitor subdomain to this port (default 8888).
"""

import time
import logging
import psutil
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string

logger = logging.getLogger(__name__)
app    = Flask(__name__)

# Shared state — populated by run_dashboard() before the server starts
_state: dict = {}

# ─── HTML Template ─────────────────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HNG Anomaly Detector — Live Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body   { font-family: 'Courier New', monospace; background: #0d1117; color: #e6edf3; padding: 24px; }
  h1     { color: #58a6ff; margin-bottom: 4px; font-size: 1.4rem; }
  h2     { color: #8b949e; font-size: 1rem; margin-bottom: 12px; }
  .sub   { color: #8b949e; font-size: 0.75rem; margin-bottom: 24px; }
  .grid  { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .card  { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
  .val   { font-size: 2rem; font-weight: bold; color: #58a6ff; line-height: 1.1; }
  .lbl   { font-size: 0.72rem; color: #8b949e; margin-top: 4px; text-transform: uppercase; letter-spacing: .05em; }
  .alert { color: #f85149; }
  table  { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th     { color: #8b949e; text-align: left; padding: 8px 12px; border-bottom: 1px solid #30363d; font-size: 0.75rem; text-transform: uppercase; }
  td     { padding: 8px 12px; border-bottom: 1px solid #21262d; }
  tr:last-child td { border-bottom: none; }
  .ip-banned { color: #f85149; font-weight: bold; }
  .ip-ok     { color: #3fb950; }
  .badge     { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; font-weight: bold; }
  .badge-red { background: rgba(248,81,73,.2); color: #f85149; border: 1px solid #f8514940; }
  .chart-wrap { position: relative; height: 220px; }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #3fb950; margin-right: 6px; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:.4 } }
</style>
</head>
<body>

<h1><span class="status-dot"></span>HNG Anomaly Detection Engine</h1>
<p class="sub" id="last-update">Loading…</p>

<!-- ── Metrics Cards ─────────────────────────────────────────────────────── -->
<div class="grid">
  <div class="card"><div class="val" id="global-rate">—</div><div class="lbl">Global req/s</div></div>
  <div class="card"><div class="val alert" id="banned-count">—</div><div class="lbl">Banned IPs</div></div>
  <div class="card"><div class="val" id="mean">—</div><div class="lbl">Baseline Mean</div></div>
  <div class="card"><div class="val" id="stddev">—</div><div class="lbl">Baseline StdDev</div></div>
  <div class="card"><div class="val" id="cpu">—</div><div class="lbl">CPU Usage</div></div>
  <div class="card"><div class="val" id="mem">—</div><div class="lbl">Memory Usage</div></div>
  <div class="card"><div class="val" id="uptime">—</div><div class="lbl">Uptime</div></div>
</div>

<!-- ── Baseline History Graph ─────────────────────────────────────────────── -->
<div class="card" style="margin-bottom:20px">
  <h2>Baseline Mean Over Time</h2>
  <div class="chart-wrap"><canvas id="baseline-chart"></canvas></div>
</div>

<!-- ── Two-column tables ──────────────────────────────────────────────────── -->
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">

  <div class="card">
    <h2>Banned IPs (<span id="banned-count2">0</span>)</h2>
    <table>
      <thead><tr><th>IP</th><th>Banned At</th><th>Unban In</th><th>Bans</th></tr></thead>
      <tbody id="banned-table"><tr><td colspan="4" style="color:#8b949e">No banned IPs</td></tr></tbody>
    </table>
  </div>

  <div class="card">
    <h2>Top 10 Source IPs (last 60s)</h2>
    <table>
      <thead><tr><th>IP</th><th>Rate (req/s)</th></tr></thead>
      <tbody id="top-table"><tr><td colspan="2" style="color:#8b949e">No traffic yet</td></tr></tbody>
    </table>
  </div>

</div>

<script>
// ── Chart setup ───────────────────────────────────────────────────────────────
const ctx = document.getElementById('baseline-chart').getContext('2d');
const baselineChart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: [],
    datasets: [{
      label: 'Effective Mean (req/s)',
      data: [],
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88,166,255,.1)',
      borderWidth: 2,
      pointRadius: 2,
      tension: 0.3,
      fill: true
    },{
      label: 'Mean + StdDev',
      data: [],
      borderColor: 'rgba(248,81,73,.6)',
      borderDash: [4,4],
      borderWidth: 1,
      pointRadius: 0,
      fill: false
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: { ticks: { color: '#8b949e', maxTicksLimit: 10 }, grid: { color: '#21262d' } },
      y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' }, beginAtZero: true }
    },
    plugins: { legend: { labels: { color: '#8b949e', font: { size: 11 } } } }
  }
});

// ── Data fetch and DOM update ─────────────────────────────────────────────────
async function refresh() {
  try {
    const r    = await fetch('/api/metrics');
    const data = await r.json();

    // Metric cards
    document.getElementById('global-rate').textContent  = data.global_rate.toFixed(3);
    document.getElementById('banned-count').textContent  = data.banned_ips.length;
    document.getElementById('banned-count2').textContent = data.banned_ips.length;
    document.getElementById('mean').textContent          = data.effective_mean.toFixed(3);
    document.getElementById('stddev').textContent        = data.effective_stddev.toFixed(3);
    document.getElementById('cpu').textContent           = data.cpu + '%';
    document.getElementById('mem').textContent           = data.memory + '%';
    document.getElementById('uptime').textContent        = data.uptime;
    document.getElementById('last-update').textContent   = 'Last updated: ' + data.timestamp;

    // Banned IPs table
    const bannedTbody = document.getElementById('banned-table');
    if (data.banned_ips.length === 0) {
      bannedTbody.innerHTML = '<tr><td colspan="4" style="color:#8b949e">No banned IPs</td></tr>';
    } else {
      bannedTbody.innerHTML = data.banned_ips.map(b =>
        `<tr>
          <td class="ip-banned">${b.ip}</td>
          <td>${b.banned_at}</td>
          <td>${b.unban_in}</td>
          <td><span class="badge badge-red">${b.ban_count}x</span></td>
        </tr>`
      ).join('');
    }

    // Top IPs table
    const topTbody = document.getElementById('top-table');
    if (!data.top_ips || data.top_ips.length === 0) {
      topTbody.innerHTML = '<tr><td colspan="2" style="color:#8b949e">No traffic yet</td></tr>';
    } else {
      topTbody.innerHTML = data.top_ips.map(([ip, rate]) => {
        const cls = data.banned_ips.some(b => b.ip === ip) ? 'ip-banned' : 'ip-ok';
        return `<tr><td class="${cls}">${ip}</td><td>${rate.toFixed(4)}</td></tr>`;
      }).join('');
    }

    // Baseline history chart
    if (data.baseline_history && data.baseline_history.length > 0) {
      const labels = data.baseline_history.map(h => h.time);
      const means  = data.baseline_history.map(h => h.mean);
      const upper  = data.baseline_history.map(h => h.mean + h.stddev);
      baselineChart.data.labels           = labels;
      baselineChart.data.datasets[0].data = means;
      baselineChart.data.datasets[1].data = upper;
      baselineChart.update('none');  // 'none' = no animation on update
    }

  } catch(e) {
    document.getElementById('last-update').textContent = 'Connection error — retrying…';
  }
}

// Refresh immediately, then every 3 seconds
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""


# ─── API Endpoint ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Serve the dashboard HTML page."""
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/metrics')
def metrics():
    """
    JSON endpoint polled by the dashboard JS every 3 seconds.
    Returns all live metrics the frontend needs.
    """
    detector = _state['detector']
    baseline = _state['baseline']
    blocker  = _state['blocker']
    unbanner = _state['unbanner']

    mean, stddev         = baseline.get_baseline()
    blocked_ips          = blocker.get_blocked_ips()
    pending_unbans       = unbanner.get_pending_unbans()
    ban_counts           = unbanner.get_ban_counts()

    # Build banned IPs list for the table
    banned_list = []
    for ip, blocked_at in blocked_ips.items():
        secs_remaining = pending_unbans.get(ip)
        if secs_remaining is not None:
            m, s         = divmod(int(secs_remaining), 60)
            unban_in_str = f"{m}m {s:02d}s"
        else:
            unban_in_str = "PERMANENT"

        banned_list.append({
            'ip':        ip,
            'banned_at': datetime.fromtimestamp(blocked_at, tz=timezone.utc).strftime('%H:%M:%S UTC'),
            'unban_in':  unban_in_str,
            'ban_count': ban_counts.get(ip, 1),
        })

    # Uptime string HH:MM:SS
    elapsed   = int(time.time() - _state['start_time'])
    h, rem    = divmod(elapsed, 3600)
    m, s      = divmod(rem, 60)
    uptime_str = f"{h:02d}:{m:02d}:{s:02d}"

    # Baseline history for the chart (last 100 points)
    raw_history = baseline.get_history()[-100:]
    history_out = [
        {
            'time':   datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%H:%M'),
            'mean':   round(mn, 4),
            'stddev': round(sd, 4),
            'slot':   slot,
        }
        for ts, mn, sd, slot in raw_history
    ]

    return jsonify({
        'global_rate':       round(detector.get_global_rate(), 4),
        'top_ips':           detector.get_top_ips(10),
        'banned_ips':        banned_list,
        'effective_mean':    round(mean,   4),
        'effective_stddev':  round(stddev, 4),
        'cpu':               psutil.cpu_percent(),
        'memory':            psutil.virtual_memory().percent,
        'uptime':            uptime_str,
        'baseline_history':  history_out,
        'timestamp':         datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
    })


@app.route('/health')
def health():
    """Simple liveness probe — returns 200 OK."""
    return jsonify({'status': 'ok', 'uptime': int(time.time() - _state.get('start_time', time.time()))})


# ─── Entry point ───────────────────────────────────────────────────────────────

def run_dashboard(detector, baseline, blocker, unbanner, port: int = 8888) -> None:
    """
    Start the Flask dashboard server. Called from main.py in a background thread.
    Populates the shared _state dict so the route handlers can access the live objects.
    """
    _state['detector']   = detector
    _state['baseline']   = baseline
    _state['blocker']    = blocker
    _state['unbanner']   = unbanner
    _state['start_time'] = time.time()

    logger.info(f"Dashboard starting on http://0.0.0.0:{port}")
    # use_reloader=False: the reloader would spawn a second process that doesn't
    # have the shared state and would crash. Always disable it in threaded mode.
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
