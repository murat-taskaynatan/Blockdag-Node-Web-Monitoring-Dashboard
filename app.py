#!/usr/bin/env python3
import os, re, json, subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# ------------------ tiny response cache (avoid overlapping docker logs) ------------------
_RESP = {'ts': 0.0, 'json': None}
_RESP_TTL = 2.0

# ------------------ state (height cache + running totals) ------------------
STATE_PATH = os.path.join(os.path.dirname(__file__), ".state.json")
def _state_default():
    return {"last_seen_ts": None, "last_height": None, "counters": {"mined":0, "processed":0, "sealed":0}}
def load_state():
    try:
        with open(STATE_PATH,"r") as f:
            d=json.load(f)
        s=_state_default()
        s["last_seen_ts"]=d.get("last_seen_ts")
        s["last_height"]=d.get("last_height")
        s["counters"].update(d.get("counters",{}))
        return s
    except Exception:
        return _state_default()
def save_state(s):
    try:
        tmp=STATE_PATH+".tmp"
        with open(tmp,"w") as f: json.dump(s,f)
        os.replace(tmp,STATE_PATH)
    except Exception:
        pass

# ------------------ docker helpers (no sudo) ------------------
def docker_cmd(): return ["docker"]
def container_exists(dcmd, name):
    try:
        out=subprocess.check_output(dcmd+["ps","-a","--format","{{.Names}}"], text=True)
        return any(line.strip()==name for line in out.splitlines())
    except Exception: return False

# ------------------ time & parsing helpers ------------------
TS_RGX = re.compile(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})?')

def _parse_rfc3339_any(ts):
    if not ts: return None
    t=ts.strip()
    if t.endswith('Z'): t=t[:-1]+'+00:00'
    m=re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(.*)', t)
    if not m: return None
    base, frac, rest = m.groups()
    if frac: t=f"{base}.{(frac+'000000')[:6]}{rest}"
    try: return datetime.fromisoformat(t).astimezone(timezone.utc)
    except Exception: return None

def pretty_local_ts(ts_raw, tz='America/New_York'):
    dt=_parse_rfc3339_any(ts_raw)
    if not dt: return ts_raw or 'N/A'
    try: dt=dt.astimezone(ZoneInfo(tz))
    except Exception: pass
    return dt.strftime('%b %d, %Y %I:%M:%S %p %Z')

def extract_max_int(patterns, text):
    vals=[]
    for pat in patterns:
        for m in re.findall(pat, text, flags=re.I):
            if isinstance(m, tuple):
                m=[x for x in m if x]
                m=m[-1] if m else ''
            s=re.sub(r'[,\s]','',str(m))
            d=re.search(r'(\d+)', s)
            if d: vals.append(int(d.group(1)))
    return max(vals) if vals else None

def count_occurrences(pats, text):
    return sum(len(re.findall(p, text, flags=re.I)) for p in pats)

def derive_health_from_logs(logs):
    """
    Decide health state based on recent logs.
    Only report "error" if more than 5 error-like lines are found.
    """
    if not logs:
        return ("unclear","❔ No logs")

    # Count errors
    err_hits = re.findall(r'(error|fatal|panic)', logs, re.I)
    if len(err_hits) > 5:
        return ("error","❌ Errors detected ({}+)".format(len(err_hits)))

    if re.search(r'downloading blocks|sync(ing)?|catching up', logs, re.I):
        return ("syncing","⏳ Syncing (downloading blocks)")
    if re.search(r'(mined|mining|accepted|sealed)', logs, re.I):
        return ("mining","✅ Mining/processing activity")
    if re.search(r'connected|peers?', logs, re.I):
        return ("connected","🔗 Connected to peers")
    return ("unclear","❔ Status unclear — check logs")
    if re.search(r'downloading blocks|sync(ing)?|catching up', logs, re.I): return ("syncing","⏳ Syncing (downloading blocks)")
    if re.search(r'\b(mined|mining|accepted|sealed)\b', logs, re.I): return ("mining","✅ Mining/processing activity")
    if re.search(r'\bconnected\b|\bpeers?\b', logs, re.I): return ("connected","🔗 Connected to peers")
    return ("unclear","❔ Status unclear — check logs")

def derive_sync_status(logs):
    if re.search(r'error', logs, re.I): return "❌ Error"
    if re.search(r'sync|downloading block', logs, re.I): return "⏳ Syncing"
    if re.search(r'Imported new chain segment', logs, re.I): return "✅ Synced"
    return "N/A"

# ------------------ docker logs ------------------
def tail_logs(dcmd, container, since, tail):
    cmd=dcmd+["logs","--timestamps"]
    if since: cmd+=["--since", since]
    cmd+=["--tail", str(tail), container]
    try: return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e: return e.output or ""
    except Exception: return ""

def container_started_at(dcmd, name):
    try:
        out=subprocess.check_output(dcmd+["inspect","-f","{{.State.StartedAt}}",name], text=True).strip()
        m=re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', out)
        return m.group(1) if m else (out or "")
    except Exception: return ""

def fetch_new_logs(dcmd, container, last_seen_ts):
    # sensible caps
    since = last_seen_ts if last_seen_ts else "1h"
    tail  = "5000" if last_seen_ts else "10000"
    try:
        return subprocess.check_output(dcmd+["logs","--timestamps","--since",since,"--tail",tail,container],
                                       stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e: return e.output or ""
    except Exception: return ""

# ------------------ counters & peers ------------------
MINED_PATS     = [r'\bmined\b', r'\bmining\s+completed\b']
PROCESSED_PATS = [r'\bprocessed\b', r'\baccepted\b', r'\bapplied\b']
SEALED_PATS    = [r'\bsealed\b', r'\bblock\s+sealed\b']
HEIGHT_PATS    = [
    r'(?:(?:height|best height|tip height|best|tip)[^0-9]*([0-9,]+))',
    r'(?:(?:number|block[ _-]?number|blk|no\.)[^0-9]*([0-9,]+))',
    r'\bheight=([0-9,]+)\b',
    r'block\s+([0-9,]+)'
]

from time import time
_PEERS_CACHE={'val':None,'ts':0.0}
_PEERS_STALE=90.0

def parse_peers(logs):
    pats=[
        r'\bpeers?\s*[:=]\s*([0-9,]+)\s*/\s*[0-9,]+\b',
        r'\bconnected\s+(?:to\s+)?([0-9,]+)\s+peers?\b',
        r'\b(?:peer_count|peerCount|numPeers|num_peers)\s*[:=]\s*([0-9,]+)\b',
        r'["\'](?:peerCount|connectedPeers|peers)["\']\s*[:=]\s*([0-9,]+)\b',
        r'\bpeers?\s*[:=]\s*([0-9,]+)\b',
    ]
    vals=[]
    for pat in pats:
        for m in re.findall(pat, logs, flags=re.I):
            s=re.sub(r'[,\s]','',m)
            if s.isdigit(): vals.append(int(s))
    if vals: return max(vals)
    # fallback: count unique IDs
    ids=set()
    for pat in [r'\bpeer(?:Id|ID)?=([A-Za-z0-9:/._-]+)', r'(?:/p2p/|/ipfs/)([A-Za-z0-9]+)']:
        for pid in re.findall(pat, logs):
            pid=pid.strip().rstrip('.,;')
            if pid: ids.add(pid)
    return len(ids) if ids else None

def parse_peer_list(logs, max_items=200):
    ids=[]
    for pat in [r'peer=([A-Za-z0-9:/._-]+)', r'(?:/p2p/|/ipfs/)([A-Za-z0-9]+)', r'peerId=([A-Za-z0-9]+)']:
        ids += re.findall(pat, logs)
    cleaned=[]
    for pid in ids:
        pid=(pid or '').strip().rstrip('.,;:[](){}')
        if len(pid)>=6: cleaned.append(pid)
    counts={}
    for pid in cleaned: counts[pid]=counts.get(pid,0)+1
    items=sorted(counts.items(), key=lambda kv:(-kv[1], kv[0]))[:max_items]
    out=[{"id": (pid[:7]+"…"+pid[-3:]) if len(pid)>14 else pid, "count": cnt, "full": pid} for pid,cnt in items]
    # numeric fallback row
    if not out:
        num=parse_peers(logs)
        if num: out=[{"id":"Connected peers","count": int(num), "full": str(num)}]
    return out

def update_totals_from_logs(state, new_logs):
    if not new_logs: return state
    state["counters"]["mined"]     += count_occurrences(MINED_PATS, new_logs)
    state["counters"]["processed"] += count_occurrences(PROCESSED_PATS, new_logs)
    state["counters"]["sealed"]    += count_occurrences(SEALED_PATS, new_logs)
    ts=TS_RGX.findall(new_logs)
    if ts: state["last_seen_ts"]=ts[-1]
    return state

# ------------------ routes ------------------
@app.get("/api/status")
def api_status():
    import time as _t
    now=_t.time()
    if _RESP['json'] is not None and (now-_RESP['ts']<=_RESP_TTL):
        return jsonify(_RESP['json'])

    container=request.args.get("container","blockdag-testnet-network")
    since=request.args.get("since","")
    tail=int(request.args.get("tail","600"))

    dcmd=docker_cmd()
    if not container_exists(dcmd, container):
        return jsonify({"ok":False,"error":f"Container '{container}' not found."}),404

    state=load_state()
    new_logs=fetch_new_logs(dcmd, container, state.get("last_seen_ts"))
    state=update_totals_from_logs(state, new_logs)
    save_state(state)

    live_logs=tail_logs(dcmd, container, since, tail)
    health_state, health_msg = derive_health_from_logs(live_logs)
    sync_status=derive_sync_status(live_logs)

    ts=TS_RGX.findall(live_logs)
    last_ts = ts[-1] if ts else (container_started_at(dcmd, container) or "N/A")

    # peers numeric with short cache
    pv=parse_peers(live_logs)
    _now=time()
    if pv and pv>0:
        _PEERS_CACHE['val']=pv; _PEERS_CACHE['ts']=_now
        peers=str(pv)
    else:
        if _PEERS_CACHE['val'] is not None and (_now-_PEERS_CACHE['ts']<=_PEERS_STALE):
            peers=str(_PEERS_CACHE['val'])
        else:
            peers="N/A" if pv is None else str(pv)

    # height live -> cache; else fallback to cached
    height_val = extract_max_int(HEIGHT_PATS, live_logs)
    height_stale=False
    if height_val is not None:
        state["last_height"]=int(height_val)
        save_state(state)
    else:
        if state.get("last_height") is not None:
            height_val=int(state["last_height"]); height_stale=True

    resp={
        "ok": True,
        "health_state": health_state, "health_msg": health_msg,
        "sync_status": sync_status,
        "last_log_time_raw": last_ts or "N/A",
        "last_log_time_local": pretty_local_ts(last_ts or ""),
        "peers": peers,
        "peers_list": parse_peer_list(live_logs),
        "height": (str(height_val) if height_val is not None else "N/A"),
        "height_stale": height_stale,
        "mined_total": state["counters"]["mined"],
        "processed_total": state["counters"]["processed"],
        "sealed_total": state["counters"]["sealed"],
        "since": since, "tail": tail, "container": container
    }
    _RESP['json']=resp; _RESP['ts']=now
    return jsonify(resp)

@app.post("/api/reset_totals")
def api_reset_totals():
    s=_state_default(); save_state(s)
    _RESP['json']=None
    return jsonify({"ok":True,"message":"Totals reset."})

INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>BlockDAG Dashboard</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    :root { --bg:#0b1020; --card:#121a33; --text:#e7eaf6; --muted:#9aa4c7; --ok:#22c55e; --warn:#f59e0b; --err:#ef4444; --link:#06b6d4; }
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Helvetica,Arial}
    .wrap{max-width:1100px;margin:24px auto;padding:0 16px}
    .card{background:var(--card);border-radius:16px;padding:20px;box-shadow:0 10px 24px rgba(0,0,0,.25)}
    h1{margin:0 0 12px;font-size:22px}
    .row{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0 18px}
    label{display:flex;flex-direction:column;font-size:12px;color:var(--muted);gap:6px}
    input,button{background:#0f1630;color:var(--text);border:1px solid #2a3358;border-radius:10px;padding:10px 12px}
    input{min-width:220px}
    button{cursor:pointer}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
    .pill{display:inline-block;padding:6px 10px;border-radius:999px;font-weight:600}
    .ok{background:rgba(34,197,94,.15);color:var(--ok)}
    .warn{background:rgba(245,158,11,.15);color:var(--warn)}
    .err{background:rgba(239,68,68,.18);color:var(--err)}
    .muted{color:var(--muted)}
    .k{color:var(--muted)}
    .stat{background:#0f1630;border:1px solid #2a3358;border-radius:14px;padding:12px}
    .stat .num{font-size:22px;font-weight:700}
    .tbl{width:100%;border-collapse:collapse;background:#0f1630;border:1px solid #2a3358;border-radius:12px;overflow:hidden}
    .tbl th,.tbl td{padding:10px 12px;border-bottom:1px solid #1f274b;font-size:13px}
    .tbl th{color:#9aa4c7;text-align:left;background:#11183a}
    .tbl tr:last-child td{border-bottom:none}
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
    footer{margin:18px 0;color:var(--muted);font-size:12px}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>BlockDAG Node Status</h1>
      <div class="row">
        <label>Container <input id="container" value="blockdag-testnet-network"></label>
        <label>Since <input id="since" placeholder="e.g. 5m, 1h"></label>
        <label>Tail <input id="tail" value="600" style="width:100px"></label>
        <button id="refreshBtn">Refresh</button>
        <button id="resetBtn" title="Reset running totals">Reset totals</button>
      </div>

      <div id="healthLine" class="pill muted">Loading…</div>
      <div id="syncLine" class="pill muted" style="margin-top:8px; display:none">Sync: Synced</div>

      <div class="grid" style="margin-top:12px">
        <div><span class="k">Last log time</span><div id="last_ts">—</div></div>
        <div><span class="k">Peers</span><div id="peers">—</div></div>
        <div><span class="k">Height</span><div id="height">—</div></div>
      </div>

      <div style="margin-top:16px">
        <div class="k" style="margin-bottom:8px">Block activity (running totals)</div>
        <div class="grid-3">
          <div class="stat"><div class="k">Mined</div><div class="num" id="mined_total">0</div></div>
          <div class="stat"><div class="k">Processed / Accepted</div><div class="num" id="processed_total">0</div></div>
          <div class="stat"><div class="k">Sealed</div><div class="num" id="sealed_total">0</div></div>
        </div>
      </div>

      <div style="margin-top:18px">
        <div class="k" style="margin-bottom:8px">Peers (from current log window)</div>
        <table class="tbl" id="peersTable">
          <thead><tr><th>#</th><th>Peer</th><th>Seen</th></tr></thead>
          <tbody id="peersBody"><tr><td colspan="3" class="k">Waiting for logs…</td></tr></tbody>
        </table>
      </div>

      <footer>Auto-refreshes every 10s. Health & Sync are derived from logs.</footer>
    </div>
  </div>

<script>
let timer=null;

function setHealth(state,msg){
  const el=document.getElementById('healthLine'); if(!el) return;
  let cls='pill muted';
  let text=msg||'—';
  if(state==='mining'){ cls='pill ok'; text='✅ Mining'; }
  else if(state==='syncing'){ cls='pill warn'; text='⏳ Syncing'; }
  else if(state==='connected'){ cls='pill warn'; text=msg||'🔗 Connected'; }
  else if(state==='error'){ cls='pill err'; }
  el.className=cls; el.textContent=text;
}

// Show sync pill ONLY when ✅ Synced
function setSync(text){
  const el=document.getElementById('syncLine'); if(!el) return;
  const t=(text||'').toString();
  if(t.startsWith('✅')){
    el.className='pill ok';
    el.textContent='Sync: Synced';
    el.style.display='inline-block';
  } else {
    el.style.display='none';
  }
}

function renderPeers(list, numericPeers){
  const tb=document.getElementById('peersBody'); if(!tb) return;
  if((!Array.isArray(list) || list.length===0) && numericPeers && numericPeers!=='N/A'){
    tb.innerHTML = `<tr><td>1</td><td class="mono" title="Total connected peers">Connected peers</td><td>${numericPeers}</td></tr>`;
    return;
  }
  if(!Array.isArray(list)){ tb.innerHTML='<tr><td colspan="3" class="k">No peers data</td></tr>'; return; }
  if(list.length===0){ tb.innerHTML='<tr><td colspan="3" class="k">No peers found in current window</td></tr>'; return; }
  let html='';
  for(let i=0;i<list.length;i++){
    const it=list[i]||{}; const idx=i+1;
    const idShort=it.id||''; const count=it.count??0; const full=it.full||idShort;
    html += `<tr><td>${idx}</td><td class="mono" title="${full}">${idShort}</td><td>${count}</td></tr>`;
  }
  tb.innerHTML=html;
}

async function fetchStatus(){
  const container=document.getElementById('container').value.trim();
  const since=document.getElementById('since').value.trim();
  const tail=document.getElementById('tail').value.trim()||"600";
  const qs=new URLSearchParams({container,tail}); if(since) qs.set("since", since);
  let res;
  try{
     res = await fetch("/api/status?"+qs.toString());
  }catch(e){
     // keep last values, just show error pill
     setHealth('error', '❌ Request failed'); setSync('❌ Error');
     return;
  }
  const el=(id)=>document.getElementById(id);
  if(!res.ok){
     let data={}; try{data=await res.json();}catch(e){}
     const msg = "❌ " + (data.error || `Request failed (${res.status})`);
     setHealth('error', msg); setSync('❌ Error');
     return;
  }
  const data=await res.json();
  setHealth(data.health_state, data.health_msg);
  setSync(data.sync_status||'');
  el('last_ts').textContent  = (data.last_log_time_local || data.last_log_time_raw || 'N/A');
  el('peers').textContent    = data.peers;
  el('height').textContent   = data.height + (data.height_stale ? ' (cached)' : '');
  el('mined_total').textContent     = data.mined_total ?? 0;
  el('processed_total').textContent = data.processed_total ?? 0;
  el('sealed_total').textContent    = data.sealed_total ?? 0;
  renderPeers(data.peers_list || [], data.peers);
}

function start(){ fetchStatus(); if(timer) clearInterval(timer); timer=setInterval(fetchStatus, 10000); }
document.getElementById('refreshBtn').addEventListener('click', start);
document.getElementById('resetBtn').addEventListener('click', async ()=>{ await fetch("/api/reset_totals",{method:"POST"}); start(); });
window.addEventListener('load', start);
</script>
</body>
</html>
"""
@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
