"""Read-only Intelligence dashboard for smkit feed.

Serves a new page at /intelligence on the existing dashboard server.
Uses only stdlib http.server primitives and reads from
content/feed/intelligence/*.json snapshots.

Read-only:
  - No publishing
  - No editing
  - No side effects
  - Generate Brief button produces a local brief JSON only
  - Save Snapshot copies the current filtered view to a JSON file
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .feed_intelligence import (
    IntelligenceCard,
    generate_brief_for_top,
    run_intelligent_feed,
    save_intelligence,
)
from .feed_content_hook import build_brief, ContentBrief

INTEL_DIR = Path(__file__).resolve().parents[1] / "content" / "feed" / "intelligence"
SNAPSHOTS_DIR = INTEL_DIR

INTELLIGENCE_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>smkit Intelligence</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
header{padding:18px 24px;background:#1e293b;border-bottom:1px solid #334155;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{margin:0;font-size:18px}main{max-width:1200px;margin:0 auto;padding:24px;display:grid;gap:20px}
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px}
label{display:block;font-size:13px;color:#94a3b8;margin:10px 0 4px}
input,select,textarea{width:100%;padding:9px;border-radius:8px;border:1px solid #475569;background:#0f172a;color:#e2e8f0}
.row{display:flex;gap:12px;flex-wrap:wrap}.row>*{flex:1;min-width:140px}
button{padding:10px 16px;border:0;border-radius:8px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer}
button.secondary{background:#334155}
button:disabled{opacity:.5}.chk{display:flex;align-items:center;gap:8px;margin-top:12px}
.chk input{width:auto}pre{white-space:pre-wrap;background:#0f172a;padding:12px;border-radius:8px;max-height:340px;overflow:auto;font-size:13px}
.muted{color:#94a3b8;font-size:13px}.pill{display:inline-block;background:#334155;border-radius:999px;padding:2px 10px;font-size:12px;margin:2px}
.pill.good{background:#166534}.pill.warn{background:#854d0e}.pill.bad{background:#7f1d1d}
ul{padding-left:18px;margin:6px 0}a{color:#60a5fa}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.icard{background:#0f172a;border:1px solid #334155;border-radius:10px;padding:14px}
.icard h4{margin:0 0 8px;font-size:15px}
.icard .meta{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.icard .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.icard .actions button{font-size:12px;padding:6px 10px}
.hidden{display:none}
#loading{margin:20px 0}
</style></head><body>
<header><h1>🧠 smkit Intelligence</h1><span class=muted>read-only dashboard</span>
<a href="/" style="color:#60a5fa;margin-left:auto">← Main dashboard</a></header>
<main>
 <div class=card>
  <h3 style=margin-top:0>Filters</h3>
  <div class=row>
   <div><label>Topic</label><input id=topic placeholder="AI" value="AI"></div>
   <div><label>Min Opportunity Score</label><input id=minScore type=number min=0 max=100 value=0></div>
   <div><label>Trend Direction</label><select id=trend><option value="">Any</option><option value="exploding">Exploding</option><option value="growing">Growing</option><option value="stable">Stable</option><option value="declining">Declining</option><option value="dead">Dead</option></select></div>
   <div><label>Content Type</label><select id=ctype><option value="">Any</option><option value="blog">Blog</option><option value="youtube_short">YouTube Short</option><option value="linkedin_post">LinkedIn Post</option><option value="twitter_thread">Thread</option><option value="newsletter">Newsletter</option><option value="tutorial">Tutorial</option></select></div>
  </div>
  <div class=chk><input type=checkbox id=includeSeen><label style=margin:0>Include previously seen stories</label></div>
  <div style="margin-top:12px">
   <button onclick=loadIntelligence()>Run Intelligence</button>
   <button class=secondary onclick=loadSnapshots()>Load Latest Snapshot</button>
  </div>
  <div id=loading class=muted hidden>working…</div>
 </div>

 <div class=card>
  <h3 style=margin-top:0>Top Opportunities <span class=muted id=count></span></h3>
  <div id=cards class=muted>Click “Run Intelligence” or “Load Latest Snapshot”.</div>
 </div>

 <div class=card>
  <h3 style=margin-top:0>Recent Intelligence Snapshots <span class=muted id=scount></span></h3>
  <div id=snapshots class=muted>…</div>
 </div>

 <div class=card id=detailsCard hidden>
  <h3 style=margin-top:0>Story Details</h3>
  <div id=details></div>
 </div>

 <div class=card id=briefCard hidden>
  <h3 style=margin-top:0>Generated Brief</h3>
  <pre id=briefOut></pre>
 </div>
</main>
<script>
const $=s=>document.querySelector(s);
function fmt(n){return Number(n).toFixed(2)}
function badge(score){if(score>=70)return 'good';if(score>=40)return 'warn';return 'bad'}
function trendBadge(d){return {exploding:'good',growing:'good',stable:'warn',declining:'bad',dead:'bad'}[d]||'warn'}
let currentCards=[];
async function loadIntelligence(){
 loading.hidden=false;cards.innerHTML='';
 const params=new URLSearchParams({topic:topic.value,min_score:minScore.value,trend:trend.value,content_type:ctype.value,include_seen:includeSeen.checked?'1':'0'});
 const data=await (await fetch('/api/intelligence/run?'+params)).json();
 loading.hidden=true;currentCards=data.cards||[];renderCards(currentCards);
}
async function loadSnapshots(){
 const snaps=await (await fetch('/api/intelligence/snapshots')).json();
 scount.textContent='('+snaps.length+')';
 snapshots.innerHTML=snaps.length?'<ul>'+snaps.slice(0,20).map(s=>`<li><a href="#" onclick="loadSnapshot('${s.name}');return false">${s.name}</a> <span class=muted>${s.when}</span></li>`).join('')+'</ul>':'No snapshots yet.';
 if(snaps.length) loadSnapshot(snaps[0].name);
}
async function loadSnapshot(name){
 loading.hidden=false;
 const data=await (await fetch('/api/intelligence/snapshot?name='+encodeURIComponent(name))).json();
 loading.hidden=true;currentCards=data.cards||[];renderCards(currentCards);
}
function renderCards(list){
 count.textContent='('+list.length+')';
 if(!list.length){cards.innerHTML='<span class=muted>No cards match filters.</span>';return}
 cards.innerHTML='<div class=card-grid>'+list.map((c,i)=>{
  const o=c.opportunity||{};const r=c.recommendation||{};const t=c.trend||{};const a=c.authority||{};
  return `<div class=icard>
   <h4>${c.previously_seen?'<span class="pill bad">SEEN</span> ':''}${escapeHtml(c.cluster&&c.cluster.headline||'(no headline)')}</h4>
   <div class=meta>
    <span class="pill ${badge(o.opportunity_score)}">Score ${o.opportunity_score}</span>
    <span class="pill ${trendBadge(t.direction)}">Trend ${t.direction}</span>
    <span class=pill>Authority ${fmt(a.final_score)}</span>
    <span class=pill>${r.recommendation}</span>
    <span class="pill ${badge(r.confidence_score)}">Confidence ${r.confidence_score}</span>
   </div>
   <p class=muted>${escapeHtml(r.reason||'')}</p>
   <div class=actions>
    <button onclick="details(${i})">Details</button>
    <button class=secondary onclick="generateBrief(${i})">Generate Brief</button>
    <button class=secondary onclick="openSource('${escapeHtml((c.cluster&&c.cluster.urls&&c.cluster.urls[0])||'')})">Open Source</button>
   </div>
  </div>`;
 }).join('')+'</div>';
}
function details(i){
 const c=currentCards[i];const o=c.opportunity||{};const r=c.recommendation||{};const t=c.trend||{};
 detailsCard.hidden=false;
 details.innerHTML=`<div class=row><div><b>Opportunity Score</b><br>${o.opportunity_score}</div><div><b>Trend</b><br>${t.direction}</div><div><b>Authority</b><br>${c.authority&&c.authority.final_score}</div></div>
  <p><b>Explanation:</b> ${escapeHtml(r.reason||'')}</p>
  <p><b>Signals:</b> ${(o.signals||[]).map(s=>`<span class=pill>${escapeHtml(s)}</span>`).join(' ')}</p>
  <p><b>Sources:</b> ${(c.cluster&&c.cluster.sources||[]).map(s=>`<span class=pill>${escapeHtml(s)}</span>`).join(' ')}</p>
  <p><b>URLs:</b><ul>${(c.cluster&&c.cluster.urls||[]).map(u=>`<li><a href="${encodeURI(u)}" target=_blank>${escapeHtml(u)}</a></li>`).join('')}</ul></p>`;
}
async function generateBrief(i){
 const c=currentCards[i];
 const data=await (await fetch('/api/intelligence/brief',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({card:c})})).json();
 briefCard.hidden=false;briefOut.textContent=JSON.stringify(data.brief,null,2);
}
function openSource(url){if(url)window.open(url,'_blank')}
function escapeHtml(t){return String(t||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
loadSnapshots();
</script></body></html>"""


# ── Snapshot helpers ─────────────────────────────────────────────────────────

def list_snapshots() -> list[dict[str, Any]]:
    if not SNAPSHOTS_DIR.exists():
        return []
    out = []
    for p in sorted(SNAPSHOTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)
            out.append({
                "name": p.name,
                "path": str(p),
                "when": mtime.strftime("%Y-%m-%d %H:%M UTC"),
            })
        except OSError:
            continue
    return out


def load_snapshot(name: str) -> dict[str, Any]:
    if ".." in name or "/" in name or "\\" in name:
        return {"error": "invalid name"}
    path = SNAPSHOTS_DIR / name
    if not path.exists():
        return {"error": "snapshot not found"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"error": f"bad json: {exc}"}


# ── Filter helpers ───────────────────────────────────────────────────────────

def _matches_filter(card: dict[str, Any], min_score: int, trend: str, content_type: str) -> bool:
    opp = card.get("opportunity", {})
    rec = card.get("recommendation", {})
    tr = card.get("trend", {})
    if opp.get("opportunity_score", 0) < min_score:
        return False
    if trend and tr.get("direction") != trend:
        return False
    if content_type and rec.get("recommendation") != content_type:
        return False
    return True


def filter_cards(cards: list[dict[str, Any]], min_score: int, trend: str, content_type: str) -> list[dict[str, Any]]:
    return [c for c in cards if _matches_filter(c, min_score, trend, content_type)]


# ── Route handlers ──────────────────────────────────────────────────────────

def handle_intelligence_get() -> tuple[bytes, str]:
    return INTELLIGENCE_PAGE.encode("utf-8"), "text/html; charset=utf-8"


def handle_run(query: dict[str, list[str]]) -> dict[str, Any]:
    """Run intelligence pipeline with dashboard filters. No side effects."""
    topic = (query.get("topic") or [""])[0] or None
    try:
        min_score = int((query.get("min_score") or ["0"])[0] or 0)
    except ValueError:
        min_score = 0
    trend = (query.get("trend") or [""])[0]
    content_type = (query.get("content_type") or [""])[0]
    include_seen = (query.get("include_seen") or [""])[0] == "1"

    cards = run_intelligent_feed(
        topic=topic,
        profile_name="default",
        limit=20,
        include_seen=include_seen,
    )
    dict_cards = [c.to_dict() for c in cards]
    filtered = filter_cards(dict_cards, min_score, trend, content_type)
    return {"ok": True, "cards": filtered, "total": len(dict_cards), "filtered": len(filtered)}


def handle_snapshots() -> dict[str, Any]:
    return {"ok": True, "snapshots": list_snapshots()}


def handle_snapshot(name: str) -> dict[str, Any]:
    data = load_snapshot(name)
    if "error" in data:
        return {"ok": False, "error": data["error"]}
    return {"ok": True, "name": name, "cards": data.get("cards", []), "top_brief": data.get("top_brief")}


def handle_brief(body: dict[str, Any]) -> dict[str, Any]:
    """Generate a content brief for a single card. No publishing."""
    from .feed_clustering import StoryCluster
    from .feed_recommendations import FormatRecommendation
    from .feed import FeedItem

    card_data = body.get("card", {})
    cluster_data = card_data.get("cluster", {})
    rec_data = card_data.get("recommendation", {})

    items = [FeedItem(**item) for item in cluster_data.get("items", []) if isinstance(item, dict)]
    rep_data = cluster_data.get("representative", {})
    representative = FeedItem(**rep_data) if isinstance(rep_data, dict) else (items[0] if items else FeedItem())

    cluster = StoryCluster(
        cluster_id=cluster_data.get("cluster_id", ""),
        representative=representative,
        items=items,
        headline=cluster_data.get("headline", ""),
        urls=cluster_data.get("urls", []),
        sources=cluster_data.get("sources", []),
        earliest=cluster_data.get("earliest", ""),
        latest=cluster_data.get("latest", ""),
        size=cluster_data.get("size", len(items)),
        score=cluster_data.get("score", 0.0),
    )

    rec = FormatRecommendation(
        recommendation=rec_data.get("recommendation", "blog"),
        confidence_score=rec_data.get("confidence_score", 0),
        reason=rec_data.get("reason", ""),
        platform_fit_scores=rec_data.get("platform_fit_scores", {}),
        suggested_angle=rec_data.get("suggested_angle", ""),
        suggested_hook=rec_data.get("suggested_hook", ""),
        signals=rec_data.get("signals", []),
    )

    brief = build_brief(cluster, rec)
    return {"ok": True, "brief": brief.to_dict()}


# ── Dispatch for dashboard.py integration ───────────────────────────────────

def register_routes(path: str, query: dict[str, list[str]], body: dict[str, Any] | None = None) -> tuple[bytes, str] | dict[str, Any]:
    """Dispatch an Intelligence dashboard request.

    Returns (bytes, content_type) for GET /intelligence,
    or a JSON-serializable dict for API endpoints.
    """
    if path == "/intelligence":
        page, ctype = handle_intelligence_get()
        return page, ctype
    if path == "/api/intelligence/run":
        return handle_run(query)
    if path == "/api/intelligence/snapshots":
        return handle_snapshots()
    if path == "/api/intelligence/snapshot":
        name = (query.get("name") or [""])[0]
        return handle_snapshot(name)
    if path == "/api/intelligence/brief":
        return handle_brief(body or {})
    return {"error": "not found"}
