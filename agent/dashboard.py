"""Local web dashboard — a browser control panel for the agent.

Zero extra dependencies: built on Python's stdlib http.server. Run with
`smkit dashboard` and open http://127.0.0.1:8800. Trigger runs, repurpose a
URL, preview drafts, and browse history without touching the CLI.

Binds to localhost by default. It CAN publish live (uncheck "dry run"), so
don't expose it to the network unless you mean to.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import history
from .config import AgentConfig, ROOT, list_profiles, load_profile
from .orchestrator import run_agent
from .prompts import build_goal

DRAFTS_DIR = ROOT / "content" / "drafts"

PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Social Media Agent</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
header{padding:18px 24px;background:#1e293b;border-bottom:1px solid #334155}
h1{margin:0;font-size:18px}main{max-width:920px;margin:0 auto;padding:24px;display:grid;gap:20px}
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px}
label{display:block;font-size:13px;color:#94a3b8;margin:10px 0 4px}
input,select,textarea{width:100%;padding:9px;border-radius:8px;border:1px solid #475569;background:#0f172a;color:#e2e8f0}
.row{display:flex;gap:12px}.row>*{flex:1}
button{margin-top:14px;padding:10px 16px;border:0;border-radius:8px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer}
button:disabled{opacity:.5}.chk{display:flex;align-items:center;gap:8px;margin-top:12px}
.chk input{width:auto}pre{white-space:pre-wrap;background:#0f172a;padding:12px;border-radius:8px;max-height:340px;overflow:auto;font-size:13px}
.muted{color:#94a3b8;font-size:13px}.pill{display:inline-block;background:#334155;border-radius:999px;padding:2px 10px;font-size:12px;margin:2px}
ul{padding-left:18px;margin:6px 0}a{color:#60a5fa}
</style></head><body>
<header><h1>🤖 Social Media Agent</h1><span class=muted>local dashboard</span></header>
<main>
 <div class=card>
  <h3 style=margin-top:0>Create</h3>
  <div class=row>
   <div><label>Mode</label><select id=mode>
    <option value=run>Run (research → write → publish)</option>
    <option value=repurpose>Repurpose (one source → native posts)</option></select></div>
   <div><label>Profile</label><select id=profile></select></div>
  </div>
  <label id=inlabel>Topic</label>
  <input id=input placeholder="e.g. Python asyncio in production">
  <div class=chk><input type=checkbox id=dry checked><label style=margin:0>Dry run (publish nothing)</label></div>
  <button id=go onclick=go()>Run</button>
  <span id=status class=muted></span>
  <pre id=out hidden></pre>
 </div>
 <div class=card><h3 style=margin-top:0>History <span class=muted id=hcount></span></h3><div id=history class=muted>…</div></div>
 <div class=card><h3 style=margin-top:0>Drafts</h3><div id=drafts class=muted>…</div><pre id=draftview hidden></pre></div>
</main>
<script>
const $=s=>document.querySelector(s);
mode.onchange=()=>{const r=mode.value=='repurpose';inlabel.textContent=r?'Source URL or file path':'Topic';input.placeholder=r?'https://yourblog.com/post':'e.g. Python asyncio'};
async function load(){const s=await (await fetch('/api/state')).json();
 profile.innerHTML=s.profiles.map(p=>`<option>${p}</option>`).join('');
 hcount.textContent=`(${s.history.length})`;
 history.innerHTML=s.history.slice(-12).reverse().map(h=>`• <b>${(h.topic||'').slice(0,60)}</b> <span class=muted>${(h.date||'').slice(0,10)}</span> ${(h.channels||[]).map(c=>`<span class=pill>${c}</span>`).join('')}`).join('<br>')||'No runs yet.';
 drafts.innerHTML=s.drafts.length?'<ul>'+s.drafts.map(d=>`<li><a href=# onclick="view('${d}');return false">${d}</a></li>`).join('')+'</ul>':'No drafts yet.';}
async function view(n){const d=await (await fetch('/api/draft?name='+encodeURIComponent(n))).json();draftview.hidden=false;draftview.textContent=d.content;}
async function go(){go_.disabled=true;status.textContent=' working… (this can take a minute)';out.hidden=true;
 const body={mode:mode.value,input:input.value,profile:profile.value,dry_run:dry.checked};
 try{const r=await (await fetch('/api/run',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)})).json();
  out.hidden=false;out.textContent=(r.ok?'✅ ':'❌ ')+(r.summary||r.error||'')+'\\n\\n'+(r.tool_calls||[]).map(t=>'• '+t).join('\\n');
  status.textContent='';load();}catch(e){status.textContent=' error: '+e}go_.disabled=false;}
window.go_=document.getElementById('go');load();
</script></body></html>"""


def _make_handler():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if path == "/api/state":
                drafts = sorted(p.name for p in DRAFTS_DIR.glob("*.md")) \
                    if DRAFTS_DIR.exists() else []
                return self._send(200, {
                    "profiles": list_profiles() or ["default"],
                    "history": history.load(),
                    "drafts": drafts,
                })
            if path == "/api/draft":
                name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
                f = DRAFTS_DIR / name
                if name and f.exists() and f.parent == DRAFTS_DIR:
                    return self._send(200, {"name": name,
                                            "content": f.read_text(encoding="utf-8")})
                return self._send(404, {"error": "not found"})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path != "/api/run":
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            try:
                result = self._run(req)
            except Exception as exc:  # surface any failure to the browser
                return self._send(200, {"ok": False, "error": str(exc)})
            return self._send(200, result)

        def _run(self, req):
            profile = load_profile(req.get("profile") or "default")
            config = AgentConfig.load(dry_run=bool(req.get("dry_run", True)),
                                      auto_confirm=True)
            text = (req.get("input") or "").strip()
            if not text:
                return {"ok": False, "error": "Provide a topic or source."}
            if req.get("mode") == "repurpose":
                from .repurpose import repurpose
                res = repurpose(text, config, profile)
            else:
                res = run_agent(build_goal(text, None, profile), config, profile)
                if res.ok and not config.dry_run:
                    history.record({"topic": text, "profile": profile.get("name"),
                                    "provider": config.provider,
                                    "channels": profile.get("platforms", []),
                                    "steps": res.steps, "summary": res.summary})
            return {"ok": res.ok, "summary": res.summary, "error": res.error,
                    "steps": res.steps,
                    "tool_calls": [c.get("name", "") for c in (res.tool_calls or [])]}

    return Handler


def serve(host="127.0.0.1", port=8800):
    server = ThreadingHTTPServer((host, port), _make_handler())
    print(f"🌐 Dashboard at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Dashboard stopped.")
        server.shutdown()
