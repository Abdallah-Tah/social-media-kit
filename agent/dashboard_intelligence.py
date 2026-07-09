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
h1{margin:0;font-size:18px}main{max-width:1300px;margin:0 auto;padding:24px;display:grid;gap:20px}
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
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px;align-items:stretch}
.icard{background:#0f172a;border:1px solid #334155;border-radius:14px;padding:20px;display:flex;flex-direction:column;gap:14px;height:100%}
.icard h3{margin:0 0 6px;font-size:18px;font-weight:600;line-height:1.35}
.icard .head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}
.icard .score-wrap{text-align:right}
.icard .score-label{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.4px}
.icard .score{font-size:30px;font-weight:700;line-height:1}
.icard .score.good{color:#4ade80}.icard .score.warn{color:#facc15}.icard .score.bad{color:#f87171}
.icard .rec{font-size:15px;color:#cbd5e1;display:flex;align-items:center;gap:8px;line-height:1.4}
.icard .why{font-size:13px;color:#94a3b8;line-height:1.5}
.icard .meta{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0}
.icard .bar-label{font-size:12px;color:#94a3b8;margin-bottom:4px}
.icard .barwrap{background:#334155;border-radius:6px;height:10px;overflow:hidden}
.icard .bar{height:100%;border-radius:6px;transition:width .3s ease;min-width:4px}
.icard .bar.good{background:#4ade80}.icard .bar.warn{background:#facc15}.icard .bar.bad{background:#f87171}
.icard .fit{display:flex;justify-content:space-between;font-size:13px;padding:5px 0;border-bottom:1px solid #1e293b}
.icard .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:auto;padding-top:12px;border-top:1px solid #1e293b}
.icard .actions button{font-size:13px;padding:8px 12px;white-space:nowrap}
.hidden{display:none}
#loading{margin:20px 0}
.details-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:12px}
.detail-box{background:#0f172a;border:1px solid #334155;border-radius:10px;padding:12px}
.detail-box b{display:block;font-size:12px;color:#94a3b8;margin-bottom:4px}
.score-row{display:flex;justify-content:space-between;align-items:center;font-size:13px;padding:5px 0}
.score-row b{font-weight:600}
kbd{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px}
.quick{display:flex;gap:8px;flex-wrap:wrap}
.quick button{font-size:12px;padding:8px 10px}
.source-list{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.source-list .pill{cursor:default}
.spark{font-size:16px;color:#4ade80;letter-spacing:-1px}
.sparkwrap{font-size:16px;color:#4ade80;letter-spacing:-1px;white-space:nowrap}
.icard .meta .pill{margin-bottom:4px}
.assistant{background:linear-gradient(135deg,#1e3a8a 0%,#172554 100%);border:1px solid #2563eb}
.assistant h3{margin-top:0}
.delta.up{color:#4ade80}.delta.down{color:#f87171}
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
  <h3 style=margin-top:0>Quick Filters</h3>
  <div class=quick>
   <button class=secondary onclick=setFilter(70,'','')">🔥 Hot Now</button>
   <button class=secondary onclick=setFilter(50,'','')">💎 Hidden Gems</button>
   <button class=secondary onclick=setFilter(0,'exploding','')">🚀 Exploding</button>
   <button class=secondary onclick=setFilter(0,'growing','')">📈 Growing</button>
   <button class=secondary onclick=setFilter(60,'','')">⭐ High Authority</button>
   <button class=secondary onclick=setFilter(0,'','youtube_short')">🎥 Great for Shorts</button>
   <button class=secondary onclick=setFilter(0,'','linkedin_post')">💼 Great for LinkedIn</button>
   <button class=secondary onclick=setFilter(0,'','tutorial')">🧑‍💻 Tutorials</button>
   <button class=secondary onclick=setFilter(0,'','newsletter')">📬 Newsletter</button>
  </div>
 </div>

 <div class=card>
  <h3 style=margin-top:0>Top Opportunities <span class=muted id=count></span></h3>
  <div id=cards class=muted>Click “Run Intelligence” or “Load Latest Snapshot”.</div>
 </div>

 <div class=card>
  <h3 style=margin-top:0>Recent Intelligence Snapshots <span class=muted id=scount></span></h3>
  <div id=snapshots class=muted>…</div>
 </div>

 <div class="card assistant" id=assistantCard hidden>
  <h3 style=margin-top:0>🤖 AI Assistant Summary</h3>
  <div id=assistant></div>
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
function cls(score){if(score>=80)return 'good';if(score>=50)return 'warn';return 'bad'}
function badge(score){return `<span class="pill ${cls(score)}">${score}</span>`}
function trendBadge(d){return `<span class="pill ${{exploding:'good',growing:'good',stable:'warn',declining:'bad',dead:'bad'}[d]||'warn'}">${d}</span>`}
let currentCards=[];
const EMOJI={blog:'📝',youtube_short:'🎬',linkedin_post:'💼',twitter_thread:'🧵',newsletter:'📬',tutorial:'🧑‍💻'};
function setFilter(min,trendDir,ctypeVal){minScore.value=min||'';trend.value=trendDir||'';ctype.value=ctypeVal||'';loadIntelligence();}
function clusterSources(c){
 const sources=((c.cluster&&c.cluster.sources)||[]).slice().sort();
 const consensus=[];
 if(sources.length>=4)consensus.push(`Consensus: ${sources.length} sources`);
 else if(sources.length>1)consensus.push(`Cluster: ${sources.length} related pickups`);
 return {sources,consensus};
}
function sparkline(points){if(!points||!points.length)return'';const bars='▁▂▃▄▅▆▇█';const max=Math.max(...points,1);return points.map(v=>{bars[Math.min(7,Math.max(0,Math.round((v/max)*7)))]}).join('');}
function renderAssistant(cards){
 assistantCard.hidden=false;
 const actionable=cards.filter(c=>(c.opportunity||{}).opportunity_score>=60);
 const top=cards[0]||{}; const rec=(top.recommendation||{}).recommendation||'none';
 const production={youtube_short:'7 min',linkedin_post:'5 min',twitter_thread:'8 min',newsletter:'12 min',blog:'60 min',tutorial:'90 min'}[rec]||'15 min';
 assistant.innerHTML=`<div class=details-grid>
  <div class=detail-box><b>Stories worth creating</b>${actionable.length}</div>
  <div class=detail-box><b>Highest Opportunity</b>${escapeHtml(top.cluster&&top.cluster.headline||'—')}</div>
  <div class=detail-box><b>Best Format</b>${EMOJI[rec]||'🎯'} ${rec.replace(/_/g,' ')}</div>
  <div class=detail-box><b>Estimated Production Time</b>${production}</div>
  <div class=detail-box><b>Potential Audience</b>Developers / Builders</div>
  <div class=detail-box><b>Recommended Action</b>Generate brief for #1</div>
 </div>`;
}
async function loadIntelligence(){
 loading.hidden=false;cards.innerHTML='';
 const params=new URLSearchParams({topic:topic.value,min_score:minScore.value,trend:trend.value,content_type:ctype.value,include_seen:includeSeen.checked?'1':'0'});
 const data=await (await fetch('/api/intelligence/run?'+params)).json();
 loading.hidden=true;currentCards=data.cards||[];renderCards(currentCards);renderAssistant(currentCards);
}
async function loadSnapshots(){
 const snaps=await (await fetch('/api/intelligence/snapshots')).json().catch(()=>({snapshots:[]}));
 const list=(snaps.snapshots||[]);
 scount.textContent='('+list.length+')';
 snapshots.innerHTML=list.length?'<ul>'+list.slice(0,20).map(s=>`<li><a href="#" onclick="loadSnapshot('${s.name}');return false">${s.name}</a> <span class=muted>${s.when}</span></li>`).join('')+'</ul>':'No snapshots yet.';
 if(list.length) loadSnapshot(list[0].name);
}
async function loadSnapshot(name){
 loading.hidden=false;
 const data=await (await fetch('/api/intelligence/snapshot?name='+encodeURIComponent(name))).json();
 loading.hidden=true;currentCards=data.cards||[];renderCards(currentCards);renderAssistant(currentCards);
 if(data.top_brief){briefCard.hidden=false;briefOut.textContent=JSON.stringify(data.top_brief,null,2);}
}
function progressBar(score){
 const c=cls(score);return `<div class=bar-label>Opportunity Score</div><div class=barwrap><div class="bar ${c}" style="width:${score}%"></div></div>`;
}
function renderCards(list){
 count.textContent='('+list.length+')';
 if(!list.length){cards.innerHTML='<span class=muted>No cards match filters.</span>';return}
 cards.innerHTML='<div class=card-grid>'+list.map((c,i)=>{
  const o=c.opportunity||{};const r=c.recommendation||{};const t=c.trend||{};const a=c.authority||{};
  const fit=(c.platform_fit||[]).slice(0,5);const why=(c.why_care||{}).bullets||[];
  const recEmoji=EMOJI[r.recommendation]||'🎯'; const src=clusterSources(c);
  const hasMultipleSources=src.sources.length>1;
  const hasPlatformFit=fit.length>0;
  return `<div class=icard>
   <div class=head>
    <div>
     <h3>${c.previously_seen?'<span class="pill bad">SEEN</span> ':''}${escapeHtml(c.cluster&&c.cluster.headline||'(no headline)')}</h3>
     <div class=why>${why.map(b=>`<span class=pill>${escapeHtml(b)}</span>`).join(' ')}</div>
    </div>
    <div class=score-wrap>
      <div class=score-label>Opportunity</div>
      <div class="score ${cls(o.opportunity_score)}">${o.opportunity_score||0}</div>
     </div>
   </div>
   ${progressBar(o.opportunity_score||0)}
   <div class=rec>${recEmoji} ${r.recommendation.replace(/_/g,' ')} <span class=muted>— ${escapeHtml(r.suggested_hook||'')}</span></div>
   <div class=meta>
    ${trendBadge(t.direction)}<span class=sparkwrap title="trend sparkline">${sparkline(t.sparkline)}</span>${badge(r.confidence_score)}<span class=pill>Reach ${c.estimated_reach||0}%</span><span class=pill>Difficulty ${c.estimated_difficulty||'Unknown'}</span><span class=pill>Authority ${fmt(a.final_score||0)}</span>
   </div>
   ${hasMultipleSources?`<div><div style="margin-top:4px"><b style="font-size:12px;color:#94a3b8">Source Consensus</b></div>
   <div class=why>${src.consensus.map(b=>`<span class=pill>${escapeHtml(b)}</span>`).join(' ')} <span class=muted>(${src.sources.length})</span></div>
   <div class=source-list>${src.sources.map(s=>`<span class=pill>${escapeHtml(s)}</span>`).join(' ')}</div></div>`:''}
   ${hasPlatformFit?`<div><div style="margin-top:4px"><b style="font-size:13px;color:#94a3b8">Platform Fit</b></div>
   ${fit.map(f=>`<div class=fit><span>${f.emoji} ${f.platform.replace(/_/g,' ')}${f.recommended?' ⭐':''}</span><span class=${cls(f.score)}>${f.score}%</span></div>`).join('')}
   </div>`:''}
   <div class=actions>
    <button onclick="details(${i})">View Details</button>
    <button class=secondary onclick="generateBrief(${i})">Generate Brief</button>
    <button class=secondary onclick="openSource('${escapeHtml((c.cluster&&c.cluster.urls&&c.cluster.urls[0])||'')}')">Open Source</button>
   </div>
   </div>`;
 }).join('')+'</div>';
}
function details(i){
 const c=currentCards[i];const o=c.opportunity||{};const r=c.recommendation||{};const t=c.trend||{};
 detailsCard.hidden=false;
 let breakdownHtml=(c.score_breakdown||[]).map(row=>`<div class=score-row><span>${escapeHtml(row.label)}</span><b>+${row.points}</b></div>`).join('');
 details.innerHTML=`<div class=details-grid>
  <div class=detail-box><b>Opportunity Score</b>${o.opportunity_score}</div>
  <div class=detail-box><b>Trend</b>${trendBadge(t.direction)}</div>
  <div class=detail-box><b>Authority</b>${fmt(c.authority&&c.authority.final_score||0)}</div>
  <div class=detail-box><b>Confidence</b>${badge(r.confidence_score)}</div>
  <div class=detail-box><b>Estimated Reach</b>${c.estimated_reach||0}%</div>
  <div class=detail-box><b>Difficulty</b>${c.estimated_difficulty||'Unknown'}</div>
  <div class=detail-box><b>History</b>${renderHistory(c.history_delta)}</div>
 </div>
 <div class=card style=margin-bottom:12px>
  <b style="font-size:13px;color:#94a3b8">Why It Matters</b>
  <p>${escapeHtml((c.why_care||{}).summary||'')}</p>
  <b style="font-size:13px;color:#94a3b8">Recommendation Reason</b>
  <p class=muted>${escapeHtml(r.reason||'')}</p>
 </div>
 <div class=row>
  <div class=card><b style="font-size:13px;color:#94a3b8">Score Breakdown</b><div style=margin-top:8px>${breakdownHtml}</div><div class=score-row style="border-top:1px solid #334155;margin-top:6px;padding-top:6px"><span>Final</span><b>${o.opportunity_score||0}</b></div></div>
  <div class=card><b style="font-size:13px;color:#94a3b8">Sources <span class=muted>(${c.cluster&&c.cluster.sources&&c.cluster.sources.length||0})</span></b><ul>${(c.cluster&&c.cluster.sources||[]).map(s=>`<li>${escapeHtml(s)}</li>`).join('')}</ul></div>
 </div>`;
}
async function generateBrief(i){
 const c=currentCards[i];
 const data=await (await fetch('/api/intelligence/brief',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({card:c})})).json();
 briefCard.hidden=false;briefOut.textContent=JSON.stringify(data.brief,null,2);
}
function renderHistory(h){
  if(!h||h.previous===null||h.previous===undefined)return '<span class=muted>New story</span>';
  const delta=(h.current||0)-h.previous;
  const cls=delta>=0?'up':'down';const sign=delta>=0?'▲':'▼';
  return `<span class="delta ${cls}">${sign} ${Math.abs(delta)}</span> <span class=muted>from ${h.previous}</span>`;
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
