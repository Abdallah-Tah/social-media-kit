"""Analytics dashboard page and API for smkit."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analytics import compute_analytics, export_csv, export_json, save_analytics

ANALYTICS_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>smkit Analytics</title><style>
:root{color-scheme:dark;--bg:#0b1120;--panel:#151e32;--border:#2a3856;--muted:#94a3b8;--good:#22c55e;--accent:#3b82f6;--text:#f1f5f9}
*{box-sizing:border-box}body{font:14px/1.45 system-ui,sans-serif;margin:0;background:var(--bg);color:var(--text)}
header{padding:14px 22px;background:var(--panel);border-bottom:1px solid var(--border);display:flex;gap:14px;align-items:center;position:sticky;top:0;z-index:20}
a{color:#60a5fa;text-decoration:none}main{max-width:1200px;margin:0 auto;padding:18px;display:grid;gap:16px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px}
h1{margin:0;font-size:17px}h2{margin:0 0 12px;font-size:16px}.muted{color:var(--muted);font-size:12px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
button{padding:8px 14px;border:0;border-radius:7px;background:var(--accent);color:#fff;font-weight:600;cursor:pointer;font-size:12px}
button.secondary{background:#334155}.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.kpi-box{padding:14px;background:linear-gradient(180deg,#1a2744 0%,var(--panel) 100%);border:1px solid var(--border);border-radius:10px;text-align:center}
.kpi-box b{display:block;font-size:22px}.kpi-box span{font-size:11px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
th,td{padding:8px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600}.barwrap{background:#243049;border-radius:999px;height:8px;overflow:hidden}
.bar{height:100%;border-radius:999px;background:var(--good)}.tag{display:inline-block;background:#243049;border-radius:999px;padding:2px 8px;font-size:11px;margin:2px}
.notice{padding:10px;background:#1e293b;border:1px dashed var(--border);border-radius:8px;color:var(--muted)}
#loading{margin:20px 0}
</style></head><body>
<header><h1>📊 smkit Analytics</h1><a href="/intelligence">← Intelligence</a><span class=muted style="margin-left:auto">Read-only from persisted records</span></header>
<main>
<div class=card>
 <div class=row>
  <div><label class=muted>Days</label><select id=days><option value="">All time</option><option value=7>7 days</option><option value=30 selected>30 days</option><option value=90>90 days</option></select></div>
  <div><label class=muted>Platform</label><select id=platform><option value="">All</option><option value=linkedin>LinkedIn</option><option value=facebook>Facebook</option><option value=x>X</option><option value=threads>Threads</option><option value=reddit>Reddit</option><option value=newsletter>Newsletter</option><option value=youtube>YouTube</option></select></div>
  <button onclick=loadAnalytics()>Refresh</button>
  <button class=secondary onclick=syncAnalytics()>Sync Blog Analytics</button>
  <button class=secondary onclick=saveSnapshot()>Save Snapshot</button>
  <button class=secondary onclick=exportCSV()>Export CSV</button>
  <button class=secondary onclick=exportJSON()>Export JSON</button>
 </div>
 <div class=muted id=meta></div>
</div>
<div id=loading class=muted>loading…</div>
<div id=content></div>
</div>
<script>
const $=s=>document.querySelector(s);
function fmt(n){return n===null||n===undefined?'—':n}
function tag(t){return `<span class=tag>${t}</span>`}
async function loadAnalytics(){
 loading.hidden=false;content.innerHTML='';
 const params=new URLSearchParams({days:days.value,platform:platform.value});
 const data=await (await fetch('/api/analytics?'+params)).json();
 loading.hidden=true;
 meta.textContent=`Generated ${data.generated_at.slice(0,16)} · Window: ${data.start_date.slice(0,10)} to ${data.end_date.slice(0,10)}`;
 const i=data.intelligence,f=data.editorial_funnel,s=data.social,t=data.timing,p=data.performance;
 content.innerHTML=`
  <div class=card><h2>🧠 Intelligence</h2><div class=kpi>
   <div class=kpi-box><b>${i.opportunities_processed}</b><span>Opportunities</span></div>
   <div class=kpi-box><b>${i.average_opportunity_score}</b><span>Avg Score</span></div>
   <div class=kpi-box><b>${i.high_opportunities}</b><span>High ≥70</span></div>
   <div class=kpi-box><b>${i.exploding_count}</b><span>Exploding ≥85</span></div>
  </div>
  <div style=margin-top:12px><b class=muted>Top Formats:</b> ${(i.top_formats||[]).map(([f,c])=>tag(`${f} ${c}`)).join(' ')}</div>
  <div><b class=muted>Top Topics:</b> ${(i.top_topics||[]).map(([t,c])=>tag(`${t} ${c}`)).join(' ')}</div>
  </div>

  <div class=card><h2>📝 Editorial Funnel</h2><div class=kpi>
   <div class=kpi-box><b>${f.drafts_created}</b><span>Drafts Created</span></div>
   <div class=kpi-box><b>${f.drafts_reviewed}</b><span>Reviewed</span></div>
   <div class=kpi-box><b>${f.drafts_approved}</b><span>Approved</span></div>
   <div class=kpi-box><b>${f.blogs_published}</b><span>Blogs Published</span></div>
  </div>
  <table><tr><th>Stage</th><th>Count</th><th>Rate</th></tr>
   <tr><td>Draft → Reviewed</td><td>${f.drafts_reviewed}</td><td><div class=barwrap style=width:100px><div class=bar style="width:${f.draft_to_reviewed_rate}%"></div></div> ${f.draft_to_reviewed_rate}%</td></tr>
   <tr><td>Reviewed → Approved</td><td>${f.drafts_approved}</td><td><div class=barwrap style=width:100px><div class=bar style="width:${f.reviewed_to_approved_rate}%"></div></div> ${f.reviewed_to_approved_rate}%</td></tr>
   <tr><td>Approved → Published</td><td>${f.blogs_published}</td><td><div class=barwrap style=width:100px><div class=bar style="width:${f.approved_to_published_rate}%"></div></div> ${f.approved_to_published_rate}%</td></tr>
   <tr><td>Overall Conversion</td><td>${f.blogs_published}/${f.drafts_created}</td><td><div class=barwrap style=width:100px><div class=bar style="width:${f.overall_conversion_rate}%"></div></div> ${f.overall_conversion_rate}%</td></tr>
  </table>
  </div>

  <div class=card><h2>📣 Social Publishing${data.platform_filter?' — '+data.platform_filter:''}</h2><div class=kpi>
   <div class=kpi-box><b>${s.total_social_drafts}</b><span>Total Drafts</span></div>
   <div class=kpi-box><b>${s.total_published}</b><span>Published</span></div>
   <div class=kpi-box><b>${s.total_failed}</b><span>Failed</span></div>
   <div class=kpi-box><b>${s.success_rate}%</b><span>Success Rate</span></div>
  </div>
  ${Object.keys(s.by_platform||{}).length?`
  <table><tr><th>Platform</th><th>Created</th><th>Approved</th><th>Scheduled</th><th>Published</th><th>Failed</th></tr>`+
   Object.entries(s.by_platform).map(([p,c])=>`<tr><td>${p}</td><td>${c.created}</td><td>${c.approved}</td><td>${c.scheduled}</td><td>${c.published}</td><td>${c.failed}</td></tr>`).join('')+
  `</table>`:''}
  </div>

  <div class=card><h2>⏱ Timing (minutes)</h2><div class=kpi>
   <div class=kpi-box><b>${fmt(t.opportunity_to_draft_minutes)}</b><span>Opp → Draft</span></div>
   <div class=kpi-box><b>${fmt(t.draft_to_approval_minutes)}</b><span>Draft → Approval</span></div>
   <div class=kpi-box><b>${fmt(t.approval_to_publish_minutes)}</b><span>Approval → Blog Publish</span></div>
   <div class=kpi-box><b>${t.scheduled_vs_immediate.scheduled} / ${t.scheduled_vs_immediate.immediate}</b><span>Scheduled / Immediate</span></div>
  </div>
  </div>

  <div class=card><h2>📈 External Performance</h2>
   <div class=notice>${p.message}</div>
  </div>

  <div class=card><h2>🔔 Recent Publishing Activity</h2>
   ${(data.recent_activity||[]).length?`
   <table><tr><th>Type</th><th>Platform</th><th>Title</th><th>When</th></tr>`+
    data.recent_activity.map(a=>`<tr><td>${a.type}</td><td>${a.platform}</td><td><a href="${a.url}" target=_blank>${a.title||'(untitled)'}</a></td><td>${a.published_at.slice(0,16)}</td></tr>`).join('')+
   `</table>`:''}
  </div>
 `;
}
async function syncAnalytics(){
 const data=await (await fetch('/api/analytics/sync',{method:'POST'})).json();
 alert(data.ok?`Synced ${data.synced} blog posts`:`Failed: ${data.error||'unknown'}`);
}
async function saveSnapshot(){
 const data=await (await fetch('/api/analytics/save',{method:'POST'})).json();
 alert(data.ok?'Snapshot saved':'Failed');
}
function exportCSV(){
 window.open('/api/analytics/export?format=csv','_blank');
}
function exportJSON(){
 window.open('/api/analytics/export?format=json','_blank');
}
loadAnalytics();
</script></body></html>"""


def handle_analytics_page() -> tuple[bytes, str]:
    return ANALYTICS_PAGE.encode("utf-8"), "text/html; charset=utf-8"


def handle_analytics_api(query: dict[str, list[str]]) -> dict[str, Any]:
    days_str = (query.get("days") or [""])[0]
    days = int(days_str) if days_str.isdigit() else None
    platform = (query.get("platform") or [""])[0] or None
    return compute_analytics(days=days, platform_filter=platform).to_dict()


def handle_export(query: dict[str, list[str]]) -> tuple[bytes, str]:
    fmt = (query.get("format") or ["json"])[0]
    days_str = (query.get("days") or [""])[0]
    days = int(days_str) if days_str.isdigit() else None
    platform = (query.get("platform") or [""])[0] or None
    snapshot = compute_analytics(days=days, platform_filter=platform)
    if fmt == "csv":
        data = export_csv(snapshot).encode("utf-8")
        return data, "text/csv; charset=utf-8"
    data = export_json(snapshot).encode("utf-8")
    return data, "application/json; charset=utf-8"


def handle_save() -> dict[str, Any]:
    snapshot = compute_analytics()
    path = save_analytics(snapshot)
    return {"ok": True, "path": str(path)}


def handle_sync() -> dict[str, Any]:
    from .analytics_connectors.blog import sync_blog_analytics
    return sync_blog_analytics()
