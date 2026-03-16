"""
main.py — Flask web app + APScheduler
Chạy: python main.py
Deploy: Railway sẽ chạy lệnh này tự động
"""
import os
import time
import logging
import threading
from datetime import datetime

from flask import Flask, jsonify, render_template_string, request, abort
from apscheduler.schedulers.background import BackgroundScheduler

import db
from scanner  import get_symbols, scan_market, filter_top_signals
from notifier import notify_top_signals, notify_scan_start, notify_scan_done

# ─── Config ───────────────────────────────────────────────────────────────────
LOG_LEVEL      = os.environ.get("LOG_LEVEL", "INFO")
PORT           = int(os.environ.get("PORT", 8080))
SCAN_INTERVAL  = int(os.environ.get("SCAN_INTERVAL_MIN", 30))   # phút
MAX_SYMBOLS    = int(os.environ.get("MAX_SYMBOLS", 500))
API_KEY        = os.environ.get("API_KEY", "")                  # optional auth

logging.basicConfig(
    level    = getattr(logging, LOG_LEVEL),
    format   = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt  = "%H:%M:%S",
)
log = logging.getLogger("main")

# ─── App & DB ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
db.init_db()

# Trạng thái scan hiện tại
scan_state = {
    "running":    False,
    "last_scan":  None,
    "last_count": 0,
    "duration":   0,
    "progress":   0,
    "error":      None,
}
scan_lock = threading.Lock()


# ─── Scan job ─────────────────────────────────────────────────────────────────
def run_scan():
    with scan_lock:
        if scan_state["running"]:
            log.warning("Scan already running, skipping")
            return
        scan_state["running"] = True
        scan_state["error"]   = None

    t0 = time.time()
    log.info("=== SCAN START ===")
    try:
        symbols = get_symbols(MAX_SYMBOLS)
        if not symbols:
            raise RuntimeError("No symbols loaded")

        notify_scan_start(len(symbols))
        run_id = db.start_run(len(symbols))

        results = scan_market(symbols)
        db.save_signals(run_id, results)
        db.end_run(run_id, "done")

        duration = time.time() - t0
        top      = filter_top_signals(results)
        notify_top_signals(top)
        notify_scan_done(len(results), duration)

        with scan_lock:
            scan_state["last_scan"]  = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            scan_state["last_count"] = len(results)
            scan_state["duration"]   = round(duration, 1)

        log.info(f"=== SCAN DONE: {len(results)} results in {duration:.0f}s ===")

    except Exception as e:
        log.error(f"Scan failed: {e}", exc_info=True)
        db.end_run(run_id if "run_id" in dir() else 0, "error")
        with scan_lock:
            scan_state["error"] = str(e)
    finally:
        with scan_lock:
            scan_state["running"] = False


# ─── Scheduler ────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="UTC")
scheduler.add_job(run_scan, "interval", minutes=SCAN_INTERVAL, id="scan_job")
scheduler.start()
log.info(f"Scheduler started — scan every {SCAN_INTERVAL}min")

# Chạy ngay lần đầu khi khởi động (background)
threading.Thread(target=run_scan, daemon=True).start()


# ─── Auth decorator ───────────────────────────────────────────────────────────
def require_key(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if API_KEY and request.headers.get("X-API-Key") != API_KEY:
            abort(401, "Invalid API key")
        return f(*args, **kwargs)
    return decorated


# ─── Routes ───────────────────────────────────────────────────────────────────
DASHBOARD_HTML = """
<!DOCTYPE html><html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🚀 Crypto Scanner</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0a0a12;color:#c8c8e0;font-size:14px}
header{background:#111128;border-bottom:1px solid #222250;padding:12px 20px;display:flex;align-items:center;gap:16px}
header h1{font-size:18px;font-weight:600;color:#e0e0ff}
.badge{background:#1a1a3a;border:1px solid #333370;border-radius:6px;padding:2px 8px;font-size:12px;color:#8888bb}
.badge.running{color:#00e5b0;border-color:#00e5b033}
.container{max-width:1400px;margin:0 auto;padding:16px}
.controls{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap;align-items:center}
select,button{background:#111128;color:#c8c8e0;border:1px solid #333370;border-radius:6px;padding:6px 12px;font-size:13px;cursor:pointer}
button.primary{background:#1a1a4a;color:#a0a0ff;border-color:#4444aa}
button.primary:hover{background:#222260}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:16px}
.stat{background:#111128;border:1px solid #1e1e40;border-radius:8px;padding:12px;text-align:center}
.stat .val{font-size:22px;font-weight:700;color:#a0d0ff}
.stat .lbl{font-size:11px;color:#666688;margin-top:2px}
table{width:100%;border-collapse:collapse;background:#0d0d20}
thead th{background:#111130;padding:8px 10px;text-align:left;font-size:12px;color:#888bcc;font-weight:500;border-bottom:1px solid #1e1e40;white-space:nowrap}
tbody tr{border-bottom:1px solid #0f0f28;transition:background .1s}
tbody tr:hover{background:#111128}
tbody td{padding:7px 10px;font-size:13px;white-space:nowrap}
.buy{color:#00e5b0} .sell{color:#ff5577} .neutral{color:#8888bb}
.strong-buy{color:#00ff88;font-weight:700} .strong-sell{color:#ff2255;font-weight:700}
.lean-buy{color:#44ccaa} .lean-sell{color:#cc4466}
.bull{color:#00e5b0} .bear{color:#ff5577}
.net-bar{display:inline-block;width:60px;height:8px;background:#1a1a2e;border-radius:4px;vertical-align:middle;margin-right:4px;position:relative;overflow:hidden}
.net-bar-fill{height:100%;border-radius:4px;transition:width .3s}
.tabs{display:flex;gap:4px;margin-bottom:12px}
.tab{padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;color:#8888bb;background:#111128;border:1px solid #1e1e40}
.tab.active{background:#1a1a4a;color:#a0a0ff;border-color:#4444aa}
#loading{text-align:center;padding:40px;color:#555577}
</style>
</head>
<body>
<header>
  <h1>🚀 Crypto Scanner</h1>
  <span class="badge" id="scan-status">Idle</span>
  <span class="badge" id="last-scan">—</span>
</header>
<div class="container">
  <div class="stats" id="stats"></div>
  <div class="controls">
    <div class="tabs">
      <div class="tab active" onclick="setTF('all')">All TF</div>
      <div class="tab" onclick="setTF('30m')">30m</div>
      <div class="tab" onclick="setTF('4h')">4H</div>
      <div class="tab" onclick="setTF('1d')">1D</div>
    </div>
    <select id="sig-filter" onchange="loadData()">
      <option value="all">Tất cả tín hiệu</option>
      <option value="buy">Chỉ BUY</option>
      <option value="sell">Chỉ SELL</option>
      <option value="strong">Strong only (±15)</option>
    </select>
    <button class="primary" onclick="triggerScan()">▶ Scan Now</button>
    <button onclick="loadData()">⟳ Refresh</button>
  </div>
  <div id="loading">Đang tải...</div>
  <table id="tbl" style="display:none">
    <thead>
      <tr>
        <th>#</th><th>Symbol</th><th>TF</th><th>Signal</th>
        <th>Score NET</th><th>Bull/Bear</th>
        <th>RSI</th><th>ADX</th><th>Δ TL%</th>
        <th>Cloud</th><th>Env</th><th>Price</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<script>
let curTF = 'all';
function setTF(tf){
  curTF=tf;
  document.querySelectorAll('.tab').forEach(t=>{
    t.classList.toggle('active', t.textContent.toLowerCase().includes(tf==='all'?'all':tf));
  });
  loadData();
}
function sigClass(s){
  const m={'STRONG BUY':'strong-buy','BUY':'buy','LEAN BUY':'lean-buy',
           'STRONG SELL':'strong-sell','SELL':'sell','LEAN SELL':'lean-sell'};
  return m[s]||'neutral';
}
function netBar(net){
  const abs=Math.min(Math.abs(net),29);
  const pct=abs/29*100;
  const col=net>0?'#00e5b0':net<0?'#ff5577':'#555577';
  return `<span class="net-bar"><span class="net-bar-fill" style="width:${pct}%;background:${col}"></span></span>${net>0?'+':''}${net}`;
}
async function loadData(){
  document.getElementById('loading').style.display='block';
  document.getElementById('tbl').style.display='none';
  const sf=document.getElementById('sig-filter').value;
  let url='/api/signals?limit=200';
  if(curTF!=='all') url+=`&tf=${curTF}`;
  if(sf==='buy')    url+=`&min_net=5`;
  if(sf==='sell')   url+=`&max_net=-5`;
  if(sf==='strong') url+=`&min_net=15`;
  const r=await fetch(url);
  const d=await r.json();
  if(!d.signals?.length){
    document.getElementById('loading').textContent='Chưa có dữ liệu — đang chờ scan đầu tiên hoàn tất.';
    return;
  }
  // filter sell side
  let rows=d.signals;
  if(sf==='sell') rows=rows.filter(r=>r.net<=-5);
  // stats
  const buys=rows.filter(r=>r.net>0).length;
  const sells=rows.filter(r=>r.net<0).length;
  document.getElementById('stats').innerHTML=`
    <div class="stat"><div class="val">${rows.length}</div><div class="lbl">Kết quả</div></div>
    <div class="stat"><div class="val bull">${buys}</div><div class="lbl">Bull signals</div></div>
    <div class="stat"><div class="val bear">${sells}</div><div class="lbl">Bear signals</div></div>
    <div class="stat"><div class="val">${d.last_scan||'—'}</div><div class="lbl">Last scan</div></div>
  `;
  const tbody=document.getElementById('tbody');
  tbody.innerHTML=rows.map((r,i)=>`
    <tr>
      <td style="color:#555577">${i+1}</td>
      <td><b>${r.symbol.replace('/USDT','')}</b><span style="color:#555577">/USDT</span></td>
      <td><span class="badge">${r.timeframe}</span></td>
      <td><b class="${sigClass(r.signal)}">${r.signal}</b></td>
      <td>${netBar(r.net)}</td>
      <td><span class="bull">${r.bull}</span>/<span class="bear">${r.bear}</span></td>
      <td class="${r.rsi>60?'bear':r.rsi<40?'bull':'neutral'}">${r.rsi}</td>
      <td class="${r.adx>25?'buy':'neutral'}">${r.adx}</td>
      <td class="${r.delta_pct>20?'bull':r.delta_pct<-20?'bear':'neutral'}">${r.delta_pct}%</td>
      <td>${r.above_cloud?'<span class="bull">▲Trên</span>':r.below_cloud?'<span class="bear">▼Dưới</span>':'<span class="neutral">~Trong</span>'}</td>
      <td>${r.bull_env?'<span class="strong-buy">BULL</span>':r.bear_env?'<span class="strong-sell">BEAR</span>':'—'}</td>
      <td style="color:#aaaacc;font-size:12px">${r.close}</td>
    </tr>
  `).join('');
  document.getElementById('loading').style.display='none';
  document.getElementById('tbl').style.display='table';
}
async function pollStatus(){
  const r=await fetch('/api/status');
  const d=await r.json();
  const badge=document.getElementById('scan-status');
  badge.textContent=d.running?'⏳ Scanning...':'✅ Idle';
  badge.className='badge'+(d.running?' running':'');
  if(d.last_scan) document.getElementById('last-scan').textContent='Last: '+d.last_scan;
}
async function triggerScan(){
  await fetch('/api/scan/trigger',{method:'POST'});
  setTimeout(pollStatus,1000);
}
loadData();
setInterval(()=>{pollStatus();}, 10000);
setInterval(()=>{if(document.getElementById('scan-status').classList.contains('running')) loadData();}, 60000);
</script>
</body></html>
"""


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/status")
def api_status():
    with scan_lock:
        return jsonify({**scan_state})


@app.route("/api/signals")
@require_key
def api_signals():
    tf      = request.args.get("tf")
    min_net = int(request.args.get("min_net", 0))
    max_net = request.args.get("max_net")
    limit   = int(request.args.get("limit", 200))

    if max_net is not None:
        signals = db.get_latest_signals(tf, int(max_net), limit)
    else:
        signals = db.get_latest_signals(tf, min_net, limit)

    with scan_lock:
        return jsonify({
            "signals":    signals,
            "last_scan":  scan_state["last_scan"],
            "last_count": scan_state["last_count"],
            "running":    scan_state["running"],
        })


@app.route("/api/scan/trigger", methods=["POST"])
@require_key
def api_trigger():
    if not scan_state["running"]:
        threading.Thread(target=run_scan, daemon=True).start()
        return jsonify({"status": "started"})
    return jsonify({"status": "already_running"})


@app.route("/api/history")
def api_history():
    return jsonify({"runs": db.get_scan_history(20)})


@app.route("/api/symbol/<path:symbol>")
def api_symbol(symbol):
    tf = request.args.get("tf", "4h")
    symbol = symbol.replace("_", "/").upper()
    return jsonify({"history": db.get_symbol_history(symbol, tf)})


@app.route("/health")
def health():
    return jsonify({"ok": True})


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
