mkdir -p ~/blockdag-scripts
cat > ~/blockdag-scripts/app.py <<'EOF'
#!/usr/bin/env python3
import subprocess, shlex, re, json
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# ---- docker / sudo docker autodetect ----
def docker_cmd():
    try:
        subprocess.run(["docker","ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return ["docker"]
    except Exception:
        pass
    try:
        subprocess.run(["sudo","-n","docker","ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return ["sudo","docker"]
    except Exception:
        return None

def container_exists(dcmd, name):
    if not dcmd: return False
    try:
        out = subprocess.check_output(dcmd + ["ps","-a","--format","{{.Names}}"], text=True)
        return any(line.strip() == name for line in out.splitlines())
    except Exception:
        return False

def have_exec(dcmd, name):
    try:
        subprocess.run(dcmd + ["exec", name, "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False

def cin(dcmd, name, url):
    try:
        out = subprocess.check_output(dcmd + ["exec", name, "curl", "-fsS", "--max-time", "2", url],
                                      stderr=subprocess.DEVNULL, text=True)
        return out.strip()
    except Exception:
        return ""

# ---- log helpers ----
TS_RGX = re.compile(r'20\d{2}-[01]\d-[0-3]\d[ T][0-2]\d:[0-5]\d:[0-5]\d(?:\.\d+)?')
INT_RGX = re.compile(r'(\d+)')
HASHRATE_RGX = re.compile(r'([0-9]+(?:\.[0-9]+)?\s*[kMGT]?H/s)', re.I)

def extract_last_int(patterns, text):
    for pat in patterns:
        m = re.findall(pat, text, flags=re.I)
        if m:
            ints = INT_RGX.findall(m[-1])
            if ints:
                return ints[-1]
    return None

def extract_last_hashrate(text):
    m = HASHRATE_RGX.findall(text)
    return m[-1] if m else None

def derive_state(logs, readyz, healthz):
    combined = (readyz or "") + (healthz or "")
    if combined:
        if re.search(r'\b(ok|ready|healthy|pass)\b', combined, re.I):
            state = ("healthy", "✅ Healthy (health endpoints OK)")
        elif re.search(r'(fail|unhealthy|not ready|error)', combined, re.I):
            state = ("unhealthy", "❌ Unhealthy (health endpoints failing)")
        else:
            state = ("waiting", "⏳ Health endpoints reachable, waiting...")
    else:
        state = ("unclear", "❔ Status unclear — check full logs")

    if re.search(r'\berror\b', logs, re.I):
        state = ("error", "❌ Error detected — check logs")
    elif re.search(r'downloading blocks', logs, re.I):
        state = ("syncing", "⏳ Still syncing (downloading blocks)")
    elif re.search(r'mined|mining|accepted|hashrate', logs, re.I):
        state = ("mining", "✅ Mining active (blocks/tx being processed)")
    elif re.search(r'connected', logs, re.I):
        state = ("connected", "🔗 Connected to peers, waiting for mining...")
    return state

def tail_logs(dcmd, container, since, tail):
    cmd = dcmd + ["logs"]
    if since:
        cmd += ["--since", since]
    cmd += ["--tail", str(tail), container]
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e:
        return e.output or ""
    except Exception:
        return ""

@app.get("/api/status")
def api_status():
    default_container = "blockdag-testnet-network"
    container = request.args.get("container", default_container)
    since = request.args.get("since", "")
    tail = int(request.args.get("tail", "600"))

    dcmd = docker_cmd()
    if not dcmd:
        return jsonify({"ok": False, "error": "Docker is not accessible (even with sudo). Is it installed/running?"}), 500
    if not container_exists(dcmd, container):
        return jsonify({"ok": False, "error": f"Container '{container}' not found."}), 404

    readyz = healthz = ""
    if have_exec(dcmd, container):
        readyz = cin(dcmd, container, "http://127.0.0.1:6061/readyz")
        healthz = cin(dcmd, container, "http://127.0.0.1:6061/healthz")

    logs = tail_logs(dcmd, container, since, tail)

    last_ts = None
    ts_matches = TS_RGX.findall(logs)
    if ts_matches:
        last_ts = ts_matches[-1]

    peers = extract_last_int(
        [r'(?:peers|num_peers|connected peers|peers=|numPeers|peer_count)[^0-9]*([0-9]+)'], logs)
    height = extract_last_int(
        [r'(?:height|best height|tip height|tip|best)[^0-9]*([0-9]+)'], logs)
    hashrate = extract_last_hashrate(logs)

    state_key, state_msg = derive_state(logs, readyz, healthz)

    return jsonify({
        "ok": True,
        "container": container,
        "state": state_key,
        "state_msg": state_msg,
        "last_log_time": last_ts or "N/A",
        "peers": peers or "N/A",
        "height": height or "N/A",
        "hashrate": hashrate or "N/A",
        "readyz": readyz,
        "healthz": healthz,
        "since": since,
        "tail": tail
    })

INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>BlockDAG Dashboard</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    :root { --bg:#0b1020; --card:#121a33; --text:#e7eaf6; --muted:#9aa4c7; --ok:#22c55e; --warn:#f59e0b; --err:#ef4444; --link:#06b6d4; }
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Helvetica,Arial}
    .wrap{max-width:1000px;margin:24px auto;padding:0 16px}
    .card{background:var(--card);border-radius:16px;padding:20px;box-shadow:0 10px 24px rgba(0,0,0,.25)}
    h1{margin:0 0 12px;font-size:22px}
    .row{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0 18px}
    label{display:flex;flex-direction:column;font-size:12px;color:var(--muted);gap:6px}
    input,button{background:#0f1630;color:var(--text);border:1px solid #2a3358;border-radius:10px;padding:10px 12px}
    input{min-width:220px}
    button{cursor:pointer}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .k{color:var(--muted)}
    .pill{display:inline-block;padding:6px 10px;border-radius:999px;font-weight:600}
    .ok{background:rgba(34,197,94,.15);color:var(--ok)}
    .warn{background:rgba(245,158,11,.15);color:var(--warn)}
    .err{background:rgba(239,68,68,.18);color:var(--err)}
    .muted{color:var(--muted)}
    pre{white-space:pre-wrap;word-break:break-word;background:#0f1630;border:1px solid #2a3358;border-radius:12px;padding:12px}
    a{color:var(--link);text-decoration:none}
    footer{margin:18px 0;color:var(--muted);font-size:12px}
    details{margin-top:14px}
    summary{cursor:pointer}
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
      </div>

      <div id="stateLine" class="pill muted">Loading…</div>

      <div class="grid" style="margin-top:12px">
        <div><span class="k">Last log time</span><div id="last_ts">—</div></div>
        <div><span class="k">Peers</span><div id="peers">—</div></div>
        <div><span class="k">Height</span><div id="height">—</div></div>
        <div><span class="k">Hashrate</span><div id="hashrate">—</div></div>
      </div>

      <details>
        <summary>Health endpoints</summary>
        <div class="grid" style="margin-top:10px">
          <div><span class="k">/readyz</span><pre id="readyz"></pre></div>
          <div><span class="k">/healthz</span><pre id="healthz"></pre></div>
        </div>
      </details>

      <details>
        <summary>How to use</summary>
        <ul>
          <li>Change container name above or via querystring: <code>?container=NAME&amp;since=5m&amp;tail=800</code></li>
          <li>If <code>curl</code> is missing in the container, health boxes will show “—” but status still works.</li>
          <li>App tries <code>docker</code>, falls back to <code>sudo -n docker</code>.</li>
        </ul>
      </details>

      <footer>Auto-refreshes every 10s. If Docker needs sudo with a password, add your user to the <code>docker</code> group or configure passwordless sudo for docker.</footer>
    </div>
  </div>

<script>
let timer = null;

function pillClass(state){
  if(state==="healthy"||state==="mining") return "pill ok";
  if(state==="syncing"||state==="connected"||state==="waiting") return "pill warn";
  if(state==="unhealthy"||state==="error") return "pill err";
  return "pill muted";
}

async function fetchStatus(){
  const container = document.getElementById('container').value.trim();
  const since = document.getElementById('since').value.trim();
  const tail = document.getElementById('tail').value.trim() || "600";
  const qs = new URLSearchParams({container, tail});
  if(since) qs.set("since", since);

  const res = await fetch("/api/status?"+qs.toString());
  const el = (id)=>document.getElementById(id);

  if(!res.ok){
    const data = await res.json().catch(()=>({error:`HTTP ${res.status}`}));
    el('stateLine').className = "pill err";
    el('stateLine').textContent = "❌ " + (data.error || `Request failed (${res.status})`);
    ["last_ts","peers","height","hashrate","readyz","healthz"].forEach(id=>el(id).textContent="—");
    return;
  }
  const data = await res.json();
  el('stateLine').className = pillClass(data.state);
  el('stateLine').textContent = data.state_msg;

  el('last_ts').textContent = data.last_log_time;
  el('peers').textContent = data.peers;
  el('height').textContent = data.height;
  el('hashrate').textContent = data.hashrate;
  el('readyz').textContent = data.readyz || "—";
  el('healthz').textContent = data.healthz || "—";
}

function start(){
  fetchStatus();
  if(timer) clearInterval(timer);
  timer = setInterval(fetchStatus, 10000);
}

document.getElementById('refreshBtn').addEventListener('click', start);
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
EOF
