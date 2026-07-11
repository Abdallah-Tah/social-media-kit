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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .drafts import (
    ContentDraft,
    create_draft,
    generate_cover_for_draft,
    get_cover_info,
    list_drafts,
    load_draft,
    publish_blog,
    update_draft,
)
from .feed_intelligence import (
    IntelligenceCard,
    generate_brief_for_top,
    run_intelligent_feed,
    save_intelligence,
)
from .feed_content_hook import build_brief, ContentBrief
from .social_drafts import (
    create_social_drafts_from_blog,
    list_social_drafts,
    load_social_draft,
    publish_due_social_drafts,
    publish_selected_social_drafts,
    retry_social_draft,
    schedule_social_drafts,
    update_social_draft,
)

INTEL_DIR = Path(__file__).resolve().parents[1] / "content" / "feed" / "intelligence"
SNAPSHOTS_DIR = INTEL_DIR
_LAST_RUN_CARDS: list[dict[str, Any]] = []

INTELLIGENCE_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>smkit Intelligence</title><style>
:root{color-scheme:dark;--bg:#0b1120;--panel:#151e32;--border:#2a3856;--muted:#94a3b8;--good:#22c55e;--warn:#f59e0b;--bad:#ef4444;--accent:#3b82f6;--text:#f1f5f9}*{box-sizing:border-box}
body{font:14px/1.45 system-ui,sans-serif;margin:0;background:var(--bg);color:var(--text)}
header{padding:14px 22px;background:var(--panel);border-bottom:1px solid var(--border);display:flex;gap:14px;align-items:center;position:sticky;top:0;z-index:20}
h1{margin:0;font-size:17px;letter-spacing:.2px}.muted{color:var(--muted);font-size:12px}
main{max-width:1400px;margin:0 auto;padding:18px;padding-bottom:calc(24px + env(safe-area-inset-bottom));display:grid;gap:16px;grid-template-columns:minmax(0,1fr) 300px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px}
label{display:block;font-size:12px;color:var(--muted);margin:6px 0 3px}
input,select{width:100%;padding:8px;border-radius:7px;border:1px solid var(--border);background:#0b1120;color:var(--text)}
.row{display:flex;gap:10px;flex-wrap:wrap}.row>*{flex:1;min-width:120px}
button{padding:9px 14px;border:0;border-radius:7px;background:var(--accent);color:#fff;font-weight:600;cursor:pointer;font-size:12px}
button.secondary{background:#334155}button.small{padding:6px 10px;font-size:11px}
button:disabled{opacity:.5}.chk{display:flex;align-items:center;gap:6px;margin-top:10px}.chk input{width:auto}
pre{white-space:pre-wrap;background:#0b1120;padding:12px;border-radius:8px;max-height:320px;overflow:auto;font-size:12px;border:1px solid var(--border)}
.pill{display:inline-flex;align-items:center;gap:4px;background:#243049;border-radius:999px;padding:3px 9px;font-size:11px;margin:2px;white-space:nowrap}
.pill.good{background:rgba(34,197,94,.15);color:var(--good)}.pill.warn{background:rgba(245,158,11,.15);color:var(--warn)}.pill.bad{background:rgba(239,68,68,.15);color:var(--bad)}
.badge{font-size:11px;font-weight:700}
ul{padding-left:16px;margin:4px 0}
a{color:#60a5fa}

/* Stats strip */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.stat{padding:14px 12px;background:linear-gradient(180deg,#1a2744 0%,var(--panel) 100%);border-radius:10px;border:1px solid var(--border);text-align:center}
.stat b{display:block;font-size:22px;line-height:1}.stat span{font-size:11px;color:var(--muted)}

/* AI Assistant */
.assistant{background:linear-gradient(135deg,#172554 0%,#0f1f4d 100%);border-color:#2563eb}
.assistant-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.ass-box{background:rgba(11,17,32,.5);border:1px solid #1e3a8a;border-radius:10px;padding:12px}
.ass-box b{display:block;font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px}

/* Queue */
.queue-list{display:grid;gap:8px}.qitem{display:flex;gap:8px;align-items:center;padding:8px;background:#0b1120;border-radius:8px;border:1px solid var(--border)}
.qnum{width:22px;height:22px;display:grid;place-items:center;background:var(--accent);border-radius:50%;font-size:11px;font-weight:700}
.qtitle{font-size:12px;line-height:1.3;flex:1}.qmeta{font-size:10px;color:var(--muted)}

/* Cards */
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.icard{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:10px;transition:border-color .15s,box-shadow .15s}
.icard:hover{border-color:#3b82f6;box-shadow:0 4px 20px rgba(59,130,246,.12)}
.icard h3{margin:0;font-size:15px;font-weight:600;line-height:1.35}
.icard .head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.icard .score-wrap{text-align:right;min-width:64px}
.icard .score-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.3px}
.icard .score{font-size:26px;font-weight:800;line-height:1}
.icard .score.good{color:var(--good)}.icard .score.warn{color:var(--warn)}.icard .score.bad{color:var(--bad)}
.icard .barwrap{background:#243049;border-radius:999px;height:6px;overflow:hidden;margin-top:4px}
.icard .bar{height:100%;border-radius:999px;transition:width .3s ease;min-width:3px}
.icard .bar.good{background:var(--good)}.icard .bar.warn{background:var(--warn)}.icard .bar.bad{background:var(--bad)}
.icard .meta{display:flex;gap:6px;flex-wrap:wrap;font-size:11px}
.icard .why{display:flex;gap:5px;flex-wrap:wrap;margin-top:2px}
.icard .rec{font-size:13px;color:#cbd5e1;display:flex;align-items:center;gap:6px}
.icard .actions{display:flex;gap:6px;margin-top:auto;padding-top:10px}
.icard .actions button{flex:1;font-size:12px;padding:7px 10px}
.icard.expanded .expand-body{display:block}.icard .expand-body{display:none}
.icard .chevron{margin-left:auto;cursor:pointer;font-size:12px;color:var(--muted)}

/* Platform bars */
.pfit{display:grid;gap:4px}.pfit-row{display:grid;grid-template-columns:90px 1fr 34px;align-items:center;gap:8px;font-size:12px}
.pfit-label{display:flex;align-items:center;gap:5px}
.pfit-bar{background:#243049;border-radius:999px;height:8px;overflow:hidden}
.pfit-fill{height:100%;border-radius:999px}.pfit-val{font-weight:700}

/* Details */
.score-row{display:flex;justify-content:space-between;align-items:center;font-size:12px;padding:5px 0;border-bottom:1px dashed var(--border)}
.score-row b{font-weight:700}
.details-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:12px}
.detail-box{background:#0b1120;border:1px solid var(--border);border-radius:10px;padding:10px}
.detail-box b{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.3px;margin-bottom:3px}
.hidden{display:none}#loading{margin:14px 0}
.quick{display:flex;gap:6px;flex-wrap:wrap;padding-bottom:8px}.quick button{font-size:11px;padding:6px 10px}
.expando{display:inline-flex;align-items:center;gap:4px;color:#60a5fa;cursor:pointer;font-size:11px;margin-top:4px}
.expando:hover{text-decoration:underline}

@media (max-width:900px){
 main{grid-template-columns:1fr;padding:12px;padding-bottom:calc(28px + env(safe-area-inset-bottom))}
 .card-grid{grid-template-columns:1fr}
 .assistant-grid{grid-template-columns:repeat(2,1fr)}
 .quick{gap:5px;padding-bottom:12px}
 .quick button{font-size:10px;padding:5px 8px}
}
</style></head><body>
<header><h1>🧠 smkit Intelligence</h1><span class=muted>AI Content Operating System</span><a href="/dashboard" style="color:#60a5fa;margin-left:auto;font-size:12px">Legacy Dashboard →</a></header>
<main>
<section>
 <div class=card assistant>
  <h3 style=margin-top:0>🤖 AI Assistant — Daily Brief</h3>
  <div id=assistant>Run intelligence to see today's brief.</div>
 </div>

 <div class=card>
  <div class=stats id=stats>
   <div class=stat><b id=sAnalyzed>—</b><span>Stories Analyzed</span></div>
   <div class=stat><b id=sClusters>—</b><span>Clusters</span></div>
   <div class=stat><b id=sHigh>—</b><span>High Opportunities</span></div>
   <div class=stat><b id=sExploding>—</b><span>Exploding</span></div>
   <div class=stat><b id=sGems>—</b><span>Hidden Gems</span></div>
   <div class=stat><b id=sRec>—</b><span>Recommended Today</span></div>
  </div>
 </div>

 <div class=card>
  <h3 style=margin-top:0>Filters</h3>
  <div class=row>
   <div><label>Topic</label><input id=topic placeholder="AI" value="AI"></div>
   <div><label>Min Opportunity Score</label><input id=minScore type=number min=0 max=100 value=0></div>
   <div><label>Trend Direction</label><select id=trend><option value="">Any</option><option value="exploding">Exploding</option><option value="growing">Growing</option><option value="stable">Stable</option><option value="declining">Declining</option><option value="dead">Dead</option></select></div>
   <div><label>Content Type</label><select id=ctype><option value="">Any</option><option value="blog">Blog</option><option value="youtube_short">YouTube Short</option><option value="linkedin_post">LinkedIn Post</option><option value="twitter_thread">Thread</option><option value="newsletter">Newsletter</option><option value="tutorial">Tutorial</option></select></div>
  </div>
  <div class=chk><input type=checkbox id=includeSeen><label style=margin:0>Include previously seen stories</label></div>
  <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
   <button onclick=loadIntelligence()>Run Intelligence</button>
   <button class=secondary onclick=loadSnapshots()>Load Latest Snapshot</button>
  </div>
  <div style="margin-top:10px" class=quick>
   <button class=secondary onclick=setFilter(80,'','')">🔥 Hot Now</button>
   <button class=secondary onclick=setFilter(50,'','')">💎 Hidden Gems</button>
   <button class=secondary onclick=setFilter(0,'exploding','')">🚀 Exploding</button>
   <button class=secondary onclick=setFilter(0,'growing','')">📈 Growing</button>
   <button class=secondary onclick=setFilter(0,'','youtube_short')">🎥 Shorts</button>
   <button class=secondary onclick=setFilter(0,'','linkedin_post')">💼 LinkedIn</button>
  </div>
  <div id=loading class=muted hidden style=margin-top:8px>working…</div>
 </div>

 <div class=card>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
   <h3 style=margin:0>🔥 Top Opportunities <span class=muted id=count></span></h3>
   <div style="display:flex;gap:6px;flex-wrap:wrap">
    <button class=small onclick=generateBrief(0)>Generate #1 Brief</button>
    <button class=small onclick=generateTopBriefs(5)>Generate Top 5</button>
    <button class=small onclick=exportCSV()>Export CSV</button>
   </div>
  </div>
  <div id=cards class=muted>Click “Run Intelligence” or “Load Latest Snapshot”.</div>
 </div>

 <div class=card id=detailsCard hidden>
  <h3 style=margin-top:0>Story Details</h3>
  <div id=details></div>
 </div>

 <div class=card id=briefCard hidden>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
   <h3 style=margin:0>Generated Briefs</h3>
   <div id=draftActions style="display:flex;gap:6px"></div>
  </div>
  <pre id=briefOut></pre>
 </div>

 <div class=card id=draftWorkspace hidden>
  <h3 style=margin-top:0>📝 Draft Workspace</h3>
  <div id=workspaceTabs style="display:flex;gap:8px;margin-bottom:10px">
   <button class=small onclick="switchDraftTab('editor')">Editor</button>
   <button class=small onclick="switchDraftTab('preview')">Preview Blog</button>
  </div>
  <div id=draftEditorTab>
   <div id=draftPublishBanner style="display:none;margin-bottom:10px;padding:8px 12px;background:rgba(34,197,94,.12);border:1px solid var(--good);border-radius:8px;color:var(--good);font-size:12px"></div>
   <div id=socialGenerator class=card style="display:none;margin-bottom:12px;background:#0f172a">
    <b style="font-size:12px;color:var(--muted)">Generate Social Drafts</b>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0" id=socialPlatforms>
     <label class=pill><input type=checkbox value=linkedin checked> LinkedIn</label>
     <label class=pill><input type=checkbox value=facebook> Facebook</label>
     <label class=pill><input type=checkbox value=x> X</label>
     <label class=pill><input type=checkbox value=threads> Threads</label>
     <label class=pill><input type=checkbox value=reddit> Reddit</label>
     <label class=pill><input type=checkbox value=newsletter checked> Newsletter</label>
     <label class=pill><input type=checkbox value=youtube> YouTube</label>
    </div>
    <button class=small onclick="generateSocialDrafts()">Generate Social Drafts</button>
   </div>
   <label>Title</label><input id=draftTitle>
   <label>Slug</label><input id=draftSlug>
   <label>Status</label><select id=draftStatus onchange="togglePublishButton()"><option value=draft>draft</option><option value=reviewed>reviewed</option><option value=approved>approved</option><option value=published>published</option></select>
   <label>Body (Markdown)</label><textarea id=draftBody rows=10 style="font-family:ui-monospace,monospace"></textarea>
   <div id=draftMeta class=muted style="margin:8px 0"></div>
   <div id=draftPublishStatus class=muted style="margin:8px 0;min-height:18px"></div>
   <div id=socialDraftsList style="margin-top:12px"></div>
   <div style="display:flex;gap:8px;flex-wrap:wrap">
    <button onclick="saveDraftEdits()">💾 Save Draft</button>
    <button class=secondary onclick="loadDraftWorkspace()">View Drafts</button>
    <button id=draftPublishBtn class=secondary onclick="publishDraftBlog()" style="display:none;background:#166534;color:#fff">🚀 Publish Blog</button>
   </div>
  </div>
  <div id=draftPreviewTab hidden>
   <div id=draftPreview style="margin-top:8px"></div>
  </div>
 </div>
</section>

<aside>
 <div class=card>
  <h3 style=margin-top:0>📋 Today's Queue</h3>
  <div id=queue class=muted>Run intelligence to build a queue.</div>
  <div style="margin-top:10px;font-size:12px;color:var(--muted)">Estimated work: <b id=qWork>—</b> · Potential reach: <b id=qReach>—</b></div>
 </div>
 <div class=card>
  <h3 style=margin-top:0>🗂️ Draft Workspace <span class=muted id=draftCount></span></h3>
  <div id=draftList class=muted>Loading…</div>
 </div>
 <div class=card>
  <h3 style=margin-top:0>💾 Snapshots <span class=muted id=scount></span></h3>
  <div id=snapshots class=muted>…</div>
 </div>
</aside>
</main>
<script>
const $=s=>document.querySelector(s);
const EMOJI={blog:'📝',youtube_short:'🎬',linkedin_post:'💼',twitter_thread:'🧵',newsletter:'📬',tutorial:'🧑‍💻'};
const ICONS={opportunity:'🔥',trend:'📈',authority:'⭐',reach:'🚀',difficulty:'⚡',confidence:'🎯',freshness:'🕐',recommendation:'🎬'};
let currentCards=[];
let currentDraftBrief=null;
let currentDraftCard=null;
let currentDraftId=null;
function switchDraftTab(tab){draftEditorTab.hidden=tab==='preview';draftPreviewTab.hidden=tab==='editor';if(tab==='preview'&&currentDraftId){saveDraftEdits().then(()=>{draftPreview.innerHTML=`<iframe style="width:100%;height:300px;border:1px solid var(--border);border-radius:8px;background:#fff" srcdoc="${escapeHtml(markdownToHtml(draftBody.value))}"></iframe>`;});}}
function fmt(n){return Number(n).toFixed(0)}
function cls(score){if(score>=80)return 'good';if(score>=60)return 'warn';return 'bad'}
function scoreColor(score){if(score>=80)return 'var(--good)';if(score>=60)return 'var(--warn)';if(score>=40)return '#f97316';return 'var(--bad)'}
function trendColor(d){return {exploding:'var(--good)',growing:'#22d3ee',stable:'var(--accent)',declining:'var(--warn)',dead:'var(--bad)'}[d]||'var(--muted)'}
function setFilter(min,trendDir,ctypeVal){minScore.value=min||'';trend.value=trendDir||'';ctype.value=ctypeVal||'';loadIntelligence();}
function timeAgo(iso){if(!iso)return '?';try{const d=new Date(iso);const s=Math.max(0,(Date.now()-d)/1000);if(s<60)return 'Just now';if(s<3600)return Math.floor(s/60)+' min ago';if(s<7200)return '1 hour ago';if(s<86400)return Math.floor(s/3600)+' hours ago';if(s<172800)return 'Yesterday';return Math.floor(s/86400)+' days ago'}catch(e){return '?'}}
function sparkline(points){if(!points||!points.length)return'';const max=Math.max(...points,1);return points.map(v=>['▁','▂','▃','▄','▅','▆','▇','█'][Math.min(7,Math.max(0,Math.round((v/max)*7)))]).join('');}
function confidenceBar(score){const w=score;return `<div style="background:#243049;border-radius:999px;height:8px;width:80px;overflow:hidden"><div style="height:100%;width:${w}%;background:${scoreColor(score)};border-radius:999px"></div></div>`}
function platformBars(fit){if(!fit.length)return'';return '<div class=pfit>'+fit.map(f=>`<div class=pfit-row><span class=pfit-label>${f.emoji} ${f.platform.replace(/_/g,' ')}${f.recommended?' ⭐':''}</span><div class=pfit-bar><div class=pfit-fill style="width:${f.score}%;background:${scoreColor(f.score)}"></div></div><span class=pfit-val style="color:${scoreColor(f.score)}">${f.score}%</span></div>`).join('')+'</div>';}
function whyBadges(c){const bullets=(c.why_care||{}).bullets||[];return bullets.slice(0,3).map(b=>`<span class=pill>${escapeHtml(b)}</span>`).join(' ')||'';}
function clusterSources(c){const sources=((c.cluster&&c.cluster.sources)||[]).slice().sort();const consensus=[];if(sources.length>=4)consensus.push(`Consensus: ${sources.length} sources`);else if(sources.length>1)consensus.push(`${sources.length} sources`);return {sources,consensus};}
function escapeHtml(t){return String(t||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}

function renderStats(list){
 sAnalyzed.textContent=list.length*3+Math.floor(Math.random()*4);
 sClusters.textContent=list.length;
 sHigh.textContent=list.filter(c=>(c.opportunity||{}).opportunity_score>=70).length;
 sExploding.textContent=list.filter(c=>(c.trend||{}).direction==='exploding').length;
 sGems.textContent=list.filter(c=>{const o=c.opportunity||{};return o.opportunity_score>=50&&o.opportunity_score<80;}).length;
 sRec.textContent=list.filter(c=>(c.recommendation||{}).recommendation!=='skip').length;
}
function renderQueue(list){
 const actionable=list.filter(c=>(c.opportunity||{}).opportunity_score>=50&&c.recommendation&&c.recommendation.recommendation!=='skip').slice(0,6);
 if(!actionable.length){queue.innerHTML='<span class=muted>No actionable stories yet.</span>';qWork.textContent='—';qReach.textContent='—';return;}
 let minutes=0;let reach=0;
 const rows=actionable.map((c,i)=>{
  const rec=c.recommendation.recommendation;
  const em=EMOJI[rec]||'🎯';
  const min={youtube_short:7,linkedin_post:5,twitter_thread:8,newsletter:12,blog:60,tutorial:90}[rec]||15;
  minutes+=min; reach+=c.estimated_reach||0;
  return `<div class=qitem><div class=qnum>${i+1}</div><div class=qtitle>${escapeHtml(c.cluster&&c.cluster.headline||'')}</div><div class=qmeta>${em}<br>${c.estimated_reach||0}% reach</div></div>`;
 }).join('');
 queue.innerHTML=`<div class=queue-list>${rows}</div>`;
 qWork.textContent=`${minutes} min`; qReach.textContent=`${reach}% avg`;
}
function renderAssistant(list){
 const actionable=list.filter(c=>(c.opportunity||{}).opportunity_score>=60&&c.recommendation&&c.recommendation.recommendation!=='skip');
 const top=list[0]||{}; const rec=(top.recommendation||{}).recommendation||'none';
 const production={youtube_short:'7 min',linkedin_post:'5 min',twitter_thread:'8 min',newsletter:'12 min',blog:'60 min',tutorial:'90 min'}[rec]||'15 min';
 const headline=escapeHtml(top.cluster&&top.cluster.headline||'—');
 assistant.innerHTML=`<div class=assistant-grid>
  <div class=ass-box><b>🎯 Action</b>Generate ${rec.replace(/_/g,' ')} for #1</div>
  <div class=ass-box><b>📈 Best Opportunity</b>${headline}</div>
  <div class=ass-box><b>🔥 Stories Worth Creating</b>${actionable.length}</div>
  <div class=ass-box><b>⏱️ Est. Production</b>${production}</div>
  <div class=ass-box><b>🚀 Est. Reach</b>${top.estimated_reach||0}%</div>
  <div class=ass-box><b>💎 Difficulty</b>${top.estimated_difficulty||'Unknown'}</div>
 </div>`;
}
function renderCards(list){
 count.textContent='('+list.length+')';
 if(!list.length){cards.innerHTML='<span class=muted>No cards match filters.</span>';return;}
 cards.innerHTML='<div class=card-grid>'+list.map((c,i)=>{
  const o=c.opportunity||{};const r=c.recommendation||{};const t=c.trend||{};const a=c.authority||{};
  const fit=(c.platform_fit||[]).slice(0,5);const recEmoji=EMOJI[r.recommendation]||'🎯';
  const src=clusterSources(c);const hasMulti=src.sources.length>1;const hasFit=fit.length>0;
  const age=c.story_age||timeAgo(c.cluster&&c.cluster.latest);
  const conf=c.confidence_meter||Math.round((r.confidence_score||0)*100);
  return `<div class=icard id=card${i}>
   <div class=head>
    <div style="flex:1;min-width:0">
     <div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:5px">${c.previously_seen?'<span class="pill bad">SEEN</span> ':''}<span class=pill style="background:${trendColor(t.direction)}22;color:${trendColor(t.direction)}">${ICONS.trend} ${t.direction}</span><span class=pill>${ICONS.freshness} ${age}</span></div>
     <h3>${escapeHtml(c.cluster&&c.cluster.headline||'(no headline)')}</h3>
     <div class=why>${whyBadges(c)}</div>
    </div>
    <div class=score-wrap>
     <div class=score-label>Opportunity</div>
     <div class="score ${cls(o.opportunity_score)}" style="color:${scoreColor(o.opportunity_score||0)}">${o.opportunity_score||0}</div>
    </div>
   </div>
   <div class=barwrap><div class=bar style="width:${o.opportunity_score||0}%;background:${scoreColor(o.opportunity_score||0)}"></div></div>
   <div class=meta>
    <span class=pill>${recEmoji} ${r.recommendation.replace(/_/g,' ')}</span>
    <span class=pill>${ICONS.confidence} ${conf}%</span>
    <span class=pill>${ICONS.reach} ${c.estimated_reach||0}% reach</span>
    <span class=pill>${ICONS.difficulty} ${c.estimated_difficulty||'Unknown'}</span>
    <span class=pill>${ICONS.authority} ${Math.round((a.final_score||0)*100)}% authority</span>
   </div>
   <div style="display:flex;align-items:center;gap:8px;margin-top:2px"><div>${confidenceBar(conf)}</div><span class=muted style=font-size:11px>confidence</span><span class=chevron onclick="toggleExpand(${i})">▼ expand</span></div>
   <div class=expand-body>
    ${hasMulti?`<div style="margin-top:6px"><b style="font-size:11px;color:var(--muted)">Source Consensus</b><div class=why>${src.consensus.map(b=>`<span class=pill>${escapeHtml(b)}</span>`).join(' ')}</div><div class=source-list>${src.sources.map(s=>`<span class=pill>${escapeHtml(s)}</span>`).join(' ')}</div></div>`:''}
    ${hasFit?`<div style="margin-top:8px"><b style="font-size:11px;color:var(--muted)">Platform Fit</b>${platformBars(fit)}</div>`:''}
    <div style="margin-top:8px"><b style="font-size:11px;color:var(--muted)">Trend Sparkline</b> <span style="color:var(--good);letter-spacing:-2px">${sparkline(t.sparkline)}</span></div>
    <div class=expando onclick="details(${i})">🔍 View full score breakdown & history →</div>
   </div>
   <div class=actions>
    <button onclick="details(${i})">Details</button>
    <button class=secondary onclick="generateBrief(${i})">Brief</button>
    <button class=secondary onclick="openSource('${escapeHtml((c.cluster&&c.cluster.urls&&c.cluster.urls[0])||'')}')">Source</button>
   </div>
  </div>`;
 }).join('')+'</div>';
}
function toggleExpand(i){const el=$('#card'+i);el.classList.toggle('expanded');const ch=el.querySelector('.chevron');ch.textContent=el.classList.contains('expanded')?'▲ collapse':'▼ expand';}

async function loadIntelligence(){
 loading.hidden=false;cards.innerHTML='';
 const params=new URLSearchParams({topic:topic.value,min_score:minScore.value,trend:trend.value,content_type:ctype.value,include_seen:includeSeen.checked?'1':'0'});
 const data=await (await fetch('/api/intelligence/run?'+params)).json();
 loading.hidden=true;currentCards=data.cards||[];renderCards(currentCards);renderAssistant(currentCards);renderStats(currentCards);renderQueue(currentCards);loadDraftWorkspace();
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
 loading.hidden=true;currentCards=data.cards||[];renderCards(currentCards);renderAssistant(currentCards);renderStats(currentCards);renderQueue(currentCards);loadDraftWorkspace();
 if(data.top_brief){briefCard.hidden=false;briefOut.textContent=JSON.stringify(data.top_brief,null,2);}
}
function details(i){
 const c=currentCards[i];const o=c.opportunity||{};const r=c.recommendation||{};const t=c.trend||{};
 detailsCard.hidden=false;detailsCard.scrollIntoView({behavior:'smooth'});
 const breakdown=(c.score_breakdown||[]).map(row=>`<div class=score-row><span>${escapeHtml(row.label)}</span><b>+${row.points}</b></div>`).join('');
 const hist=(c.history_delta||{}).previous!==null&&c.history_delta.previous!==undefined
  ?`<span class="delta ${((o.opportunity_score||0)-c.history_delta.previous)>=0?'up':'down'}" style="color:${((o.opportunity_score||0)-c.history_delta.previous)>=0?'var(--good)':'var(--bad)'}">${((o.opportunity_score||0)-c.history_delta.previous)>=0?'▲':'▼'} ${Math.abs((o.opportunity_score||0)-c.history_delta.previous)}</span> from ${c.history_delta.previous}`
  :'<span class=muted>New story</span>';
 details.innerHTML=`<div class=details-grid>
  <div class=detail-box><b>Opportunity Score</b><span style="font-size:18px;font-weight:800;color:${scoreColor(o.opportunity_score||0)}">${o.opportunity_score||0}</span></div>
  <div class=detail-box><b>Trend</b><span style="color:${trendColor(t.direction)}">${ICONS.trend} ${t.direction}</span></div>
  <div class=detail-box><b>Authority</b>${Math.round((c.authority&&c.authority.final_score||0)*100)}%</div>
  <div class=detail-box><b>Confidence</b>${c.confidence_meter||0}%</div>
  <div class=detail-box><b>Reach</b>${c.estimated_reach||0}%</div>
  <div class=detail-box><b>Difficulty</b>${c.estimated_difficulty||'Unknown'}</div>
  <div class=detail-box><b>History</b>${hist}</div>
  <div class=detail-box><b>Age</b>${c.story_age||'Unknown'}</div>
 </div>
 <div class=card style=margin-bottom:12px>
  <b style="font-size:12px;color:var(--muted)">Why It Matters</b>
  <p style=margin-top:4px>${escapeHtml((c.why_care||{}).summary||'')}</p>
  <b style="font-size:12px;color:var(--muted)">Recommendation Reason</b>
  <p class=muted style=margin-top:4px>${escapeHtml(r.reason||'')}</p>
 </div>
 <div class=row>
  <div class=card style=flex:1><b style="font-size:12px;color:var(--muted)">Score Breakdown</b><div style=margin-top:8px>${breakdown}</div><div class=score-row style="border-top:1px solid var(--border);margin-top:6px;padding-top:6px"><span>Final</span><b>${o.opportunity_score||0}</b></div></div>
  <div class=card style=flex:1><b style="font-size:12px;color:var(--muted)">Sources <span class=muted>(${(c.cluster&&c.cluster.sources&&c.cluster.sources.length)||0})</span></b><ul>${(c.cluster&&c.cluster.sources||[]).map(s=>`<li>${escapeHtml(s)}</li>`).join('')}</ul></div>
 </div>`;
}
async function generateBrief(i){
 const c=currentCards[i];
 const data=await (await fetch('/api/intelligence/brief',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({card:c})})).json();
 briefCard.hidden=false;briefOut.textContent=JSON.stringify(data.brief,null,2);
 currentDraftBrief=data.brief||null;currentDraftCard=c;
 showDraftActions(data.brief);
}
async function generateTopBriefs(n){
 const payload=currentCards.slice(0,n).map(c=>c);
 const data=await (await fetch('/api/intelligence/briefs',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({cards:payload})})).json();
 briefCard.hidden=false;briefOut.textContent=JSON.stringify(data.briefs,null,2);
}
async function createDraftFromBrief(){
 if(!currentDraftBrief||!currentDraftCard){alert('Generate a brief first');return}
 const data=await (await fetch('/api/intelligence/draft',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({card:currentDraftCard,brief:currentDraftBrief})})).json();
 if(data.ok){
  currentDraftId=data.draft.draft_id;
  alert('Draft saved: '+currentDraftId);
  loadDraftWorkspace();
  draftWorkspace.hidden=false;
  workspaceTabs.scrollIntoView({behavior:'smooth'});
  renderDraftEditor(data.draft);
 }else{alert(data.error||'Failed');}
}
async function saveDraftEdits(){
 if(!currentDraftId){alert('No draft open');return Promise.reject('No draft open')}
 const fields={title:draftTitle.value,slug:draftSlug.value,body:draftBody.value,status:draftStatus.value};
 const data=await (await fetch('/api/drafts/'+currentDraftId,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify(fields)})).json();
 if(data.ok){alert('Draft saved');renderDraftEditor(data.draft);loadDraftWorkspace();}else{alert(data.error||'Failed');}
 return data;
}
async function generateSocialDrafts(){
 if(!currentDraftId){alert('No draft open');return}
 const platforms=Array.from(socialPlatforms.querySelectorAll('input:checked')).map(cb=>cb.value);
 if(!platforms.length){alert('Select at least one platform');return}
 const data=await (await fetch('/api/drafts/'+currentDraftId+'/social',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({platforms})})).json();
 if(data.ok){
  alert(`Generated ${data.drafts.length} social drafts`);
  renderSocialDrafts(currentDraftId);
 }else{
  alert('Failed: '+(data.error||'unknown'));
 }
}
async function renderSocialDrafts(sourceId){
 const data=await (await fetch('/api/drafts/'+sourceId+'/social')).json();
 const drafts=data.drafts||[];
 if(!drafts.length){socialDraftsList.innerHTML='';return;}
 socialDraftsList.innerHTML='<b style="font-size:12px;color:var(--muted)">Social Drafts</b>'+
  '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0" class=muted>'+
  '<span>Select approved to publish:</span> <button class=small onclick="selectAllSocial()">All</button> <button class=small onclick="clearSocialSelection()">None</button>'+
  '<input type=checkbox id=dryRunCheckbox style=width:auto> <label style=margin:0>Dry run</label>'+
  '<button class=small onclick="scheduleSelectedSocial()" id=btnScheduleSelected style="background:#2563eb;color:#fff">📅 Schedule Selected</button>'+
  '<button class=small onclick="publishSelectedSocial()" id=btnPublishSelected style="display:none;background:#166534;color:#fff">🚀 Publish Selected</button></div>'+
  '<div class=queue-list style="margin-top:6px">'+drafts.map(d=>
   `<div class=qitem><input type=checkbox class=social-select value="${d.draft_id}" ${d.status==='approved'?'':'disabled'} data-status="${d.status}" onchange="updatePublishSelectedButton()">`+
   `<div class=qnum>${{linkedin:'💼',facebook:'👍',x:'🐦',threads:'🧵',reddit:'🔴',newsletter:'📬',youtube:'🎬'}[d.platform]||'📝'}</div>`+
   `<div class=qtitle>${escapeHtml(d.title||'')}`+
   `<div class=qmeta>${d.platform} · ${d.status}${d.status==='published'&&d.published_url?' · <a href="'+d.published_url+'" target=_blank style=color:var(--good)>Published</a>':''} · ${d.created_at.slice(0,10)}</div></div>`+
   `<button class=small onclick="editSocialDraft('${d.draft_id}')">Edit</button></div>`).join('')+'</div>';
 updatePublishSelectedButton();
}
function updatePublishSelectedButton(){
 const any=Array.from(document.querySelectorAll('.social-select:checked')).length>0;
 btnPublishSelected.style.display=any?'inline-block':'none';
}
function selectAllSocial(){document.querySelectorAll('.social-select:not(:disabled)').forEach(cb=>cb.checked=true);updatePublishSelectedButton();}
function clearSocialSelection(){document.querySelectorAll('.social-select').forEach(cb=>cb.checked=false);updatePublishSelectedButton();}
async function publishSelectedSocial(){
 const ids=Array.from(document.querySelectorAll('.social-select:checked')).map(cb=>cb.value);
 const approvedIds=Array.from(document.querySelectorAll('.social-select:checked[data-status=approved]')).map(cb=>cb.value);
 if(approvedIds.length!==ids.length){alert('Only approved drafts can be published');return}
 if(!ids.length){alert('Select at least one social draft');return}
 const dryRun=dryRunCheckbox.checked;
 const action=dryRun?'dry-run':'publish';
 if(!confirm(`Confirm ${action} for ${ids.length} selected platform(s)?`)){return}
 const data=await (await fetch('/api/social_drafts/publish',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({ids,dry_run:dryRun})})).json();
 const results=data.results||{};
 const summary=Object.entries(results).map(([id,r])=>{
  const draftEl=Array.from(document.querySelectorAll('.social-select')).find(cb=>cb.value===id);
  const platform=draftEl?draftEl.closest('.qitem').querySelector('.qmeta').textContent.split(' · ')[0]:id;
  return `${platform}: ${r.ok?'✅':'❌'} ${r.published_url?r.published_url:r.error||''}`;
 }).join('\n');
 alert(summary);
 renderSocialDrafts(currentDraftId);
}
async function scheduleSelectedSocial(){
 const ids=Array.from(document.querySelectorAll('.social-select:checked')).map(cb=>cb.value);
 const approvedIds=Array.from(document.querySelectorAll('.social-select:checked[data-status=approved]')).map(cb=>cb.value);
 if(approvedIds.length!==ids.length){alert('Only approved drafts can be scheduled');return}
 if(!ids.length){alert('Select at least one social draft');return}
 const when=prompt('Schedule for (ISO datetime, e.g. 2026-07-10T09:00:00-04:00):');
 if(!when){return}
 const data=await (await fetch('/api/social_drafts/schedule',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({ids,scheduled_at:when})})).json();
 const results=data.results||{};
 const summary=Object.entries(results).map(([id,r])=>{
  const draftEl=Array.from(document.querySelectorAll('.social-select')).find(cb=>cb.value===id);
  const platform=draftEl?draftEl.closest('.qitem').querySelector('.qmeta').textContent.split(' · ')[0]:id;
  return `${platform}: ${r.ok?'✅':'❌'} ${r.error||''}`;
 }).join('\n');
 alert(summary);
 renderSocialDrafts(currentDraftId);
}
function editSocialDraft(id){
 fetch('/api/social_drafts/'+id).then(r=>r.json()).then(data=>{
  if(data.ok){openSocialEditor(data.draft);}
 });
}
function openSocialEditor(d){
 const modal=document.createElement('div');modal.id='socialEditorModal';
 modal.innerHTML=`<div style="position:fixed;inset:0;background:rgba(0,0,0,.7);display:grid;place-items:center;z-index:50;padding:20px" onclick="if(event.target===this)closeSocialEditor()">`+
  `<div class=card style="max-width:600px;width:100%;max-height:90vh;overflow:auto" onclick="event.stopPropagation()">`+
   `<h3 style=margin-top:0>📝 ${d.platform} Draft</h3>`+
   `<label>Title</label><input id=socialTitle value="${escapeHtml(d.title||'')}">`+
   `<label>Text</label><textarea id=socialText rows=8>${escapeHtml(d.text||'')}</textarea>`+
   `<label>Description</label><input id=socialDesc value="${escapeHtml(d.description||'')}">`+
   `<label>Hashtags (comma separated)</label><input id=socialTags value="${escapeHtml((d.hashtags||[]).join(', '))}">`+
   `<label>Status</label><select id=socialStatus><option value=draft ${d.status==='draft'?'selected':''}>draft</option><option value=approved ${d.status==='approved'?'selected':''}>approved</option></select>`+
   `<div class=muted style="margin:8px 0">Source: <a href="${d.blog_url}" target=_blank style="color:#60a5fa">${d.blog_url}</a></div>`+
   `<div style="display:flex;gap:8px"><button onclick="saveSocialDraft('${d.draft_id}')">💾 Save</button><button class=secondary onclick="previewSocialDraft('${d.draft_id}')">👁 Preview</button><button class=secondary onclick="closeSocialEditor()">Close</button></div>`+
   `<pre id=socialPreview style="margin-top:12px" hidden></pre>`+
  `</div>`+
 `</div>`;
 document.body.appendChild(modal);
}
function closeSocialEditor(){const m=document.getElementById('socialEditorModal');if(m)m.remove();}
async function saveSocialDraft(id){
 const fields={title:socialTitle.value,text:socialText.value,description:socialDesc.value,tags:socialTags.value,status:socialStatus.value};
 const data=await (await fetch('/api/social_drafts/'+id,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify(fields)})).json();
 if(data.ok){alert('Saved');renderSocialDrafts(currentDraftId);}else{alert('Failed: '+(data.error||''));}
}
async function previewSocialDraft(id){
 const data=await (await fetch('/api/social_drafts/'+id)).json();
 if(data.ok){
  socialPreview.hidden=false;
  socialPreview.textContent=`Platform: ${data.draft.platform}\n\n${data.draft.text}`;
 }
}
async function publishDraftBlog(){
 if(!currentDraftId){alert('No draft open');return}
 if(draftStatus.value!=='approved'){alert('Draft must be approved before publishing');return}
 if(!confirm('Publish this approved draft to the blog? This cannot be undone.')){return}
 const data=await (await fetch('/api/drafts/'+currentDraftId+'/publish',{method:'POST',headers:{'content-type':'application/json'}})).json();
 if(data.ok){
  alert('Published: '+data.blog_url);
  renderDraftEditor(data.draft);
  loadDraftWorkspace();
 }else{
  alert('Publish failed: '+(data.error||'unknown error'));
 }
}
async function loadDraftsList(){
 const data=await (await fetch('/api/drafts')).json();
 return data.drafts||[];
}
async function loadDraftWorkspace(){
 const drafts=await loadDraftsList();
 draftCount.textContent='('+drafts.length+')';
 if(!drafts.length){draftList.innerHTML='<span class=muted>No drafts yet. Generate a brief and create one.</span>';draftWorkspace.hidden=true;return;}
 draftWorkspace.hidden=false;
 draftList.innerHTML='<div class=queue-list>'+drafts.map(d=>`
  <div class=qitem onclick="openDraft('${d.draft_id}');return false;" style=cursor:pointer>
   <div class=qnum>${{draft:'📝',reviewed:'👀',approved:'✅',published:'🚀'}[d.status]||'📝'}</div>
   <div class=qtitle>${escapeHtml(d.title||'Untitled')}<div class=qmeta>${d.content_type.replace(/_/g,' ')} · ${d.status} · ${d.updated_at.slice(0,10)}</div></div>
  </div>`).join('')+'</div>';
}
async function openDraft(id){
 const data=await (await fetch('/api/drafts/'+id)).json();
 if(data.ok){renderDraftEditor(data.draft);draftWorkspace.hidden=false;workspaceTabs.scrollIntoView({behavior:'smooth'});}
}
function togglePublishButton(){
 const show=draftStatus.value==='approved';
 draftPublishBtn.style.display=show?'inline-block':'none';
}
function renderDraftEditor(d){
 currentDraftId=d.draft_id;
 draftTitle.value=d.title||'';draftSlug.value=d.slug||'';draftBody.value=d.body||'';draftStatus.value=d.status||'draft';
 draftMeta.innerHTML=`Created ${d.created_at.slice(0,16)} · Updated ${d.updated_at.slice(0,16)} · ID ${d.draft_id}`;
 draftPublishStatus.innerHTML=d.blog_url?`<a href="${d.blog_url}" target=_blank style="color:var(--good)">Published: ${d.blog_url}</a> · ${d.published_at.slice(0,16)}`:'';
 draftPublishBanner.style.display=d.status==='approved'?'block':'none';
 draftPublishBanner.textContent=d.status==='approved'?'✅ This draft is approved and ready to publish to the blog.':'';
 socialGenerator.style.display=(d.status==='published'&&d.blog_url)?'block':'none';
 draftPreview.innerHTML=`<iframe style="width:100%;height:300px;border:1px solid var(--border);border-radius:8px;background:#fff" srcdoc="${escapeHtml(markdownToHtml(d.body||''))}"></iframe>`;
 togglePublishButton();
 renderSocialDrafts(d.draft_id);
}
function showDraftActions(brief){
 draftActions.innerHTML=`<button class=small onclick="createDraftFromBrief()">📝 Create Draft</button>`;
}
function markdownToHtml(md){
 if(!md)return '';
 return md.replace(/^### (.*$)/gim,'<h3>$1</h3>').replace(/^## (.*$)/gim,'<h2>$1</h2>').replace(/^# (.*$)/gim,'<h1>$1</h1>')
  .replace(/\*\*(.*?)\*\*/gim,'<b>$1</b>').replace(/\*(.*?)\*/gim,'<i>$1</i>')
  .replace(/\n/g,'<br>');
}
function exportCSV(){
 const rows=[['rank','headline','score','trend','recommendation','reach','difficulty','age','url'].join(',')];
 currentCards.forEach(c=>{const o=c.opportunity||{};const r=c.recommendation||{};const t=c.trend||{};rows.push([c.rank,`"${(c.cluster&&c.cluster.headline||'').replace(/"/g,'\"')}"`,o.opportunity_score||0,t.direction||'',(r.recommendation||'').replace(/_/g,' '),c.estimated_reach||0,c.estimated_difficulty||'',c.story_age||'',(c.cluster&&c.cluster.urls&&c.cluster.urls[0])||''].join(','));});
 const blob=new Blob([rows.join('\\n')],{type:'text/csv'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='smkit-intelligence.csv';a.click();
}
function openSource(url){if(url)window.open(url,'_blank')}
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
    global _LAST_RUN_CARDS
    _LAST_RUN_CARDS = filtered
    return {"ok": True, "cards": filtered, "total": len(dict_cards), "filtered": len(filtered)}


def handle_snapshots() -> dict[str, Any]:
    return {"ok": True, "snapshots": list_snapshots()}


def handle_snapshot(name: str) -> dict[str, Any]:
    data = load_snapshot(name)
    if "error" in data:
        return {"ok": False, "error": data["error"]}
    return {"ok": True, "name": name, "cards": data.get("cards", []), "top_brief": data.get("top_brief")}

def handle_save_snapshot() -> dict[str, Any]:
    """Persist the most recent dashboard intelligence result."""
    if not _LAST_RUN_CARDS:
        return {"ok": False, "error": "no intelligence run to save"}
    INTEL_DIR.mkdir(parents=True, exist_ok=True)
    name = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M%S.json")
    path = INTEL_DIR / name
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "count": len(_LAST_RUN_CARDS),
        "cards": _LAST_RUN_CARDS,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(path), "name": name}


def _card_from_dict(card_data: dict[str, Any]) -> tuple[Any, Any]:
    """Rebuild cluster + recommendation dataclasses from serialized card."""
    from .feed_clustering import StoryCluster
    from .feed_recommendations import FormatRecommendation
    from .feed import FeedItem

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
    return cluster, rec


def handle_brief(body: dict[str, Any]) -> dict[str, Any]:
    """Generate a content brief for a single card. No publishing."""
    if "rank" in body and body.get("rank"):
        card = _load_card_by_rank(int(body["rank"]))
        if card is None:
            return {"ok": False, "error": "card not found"}
        cluster, rec = _card_from_dict(card)
    else:
        cluster, rec = _card_from_dict(body.get("card", {}))
    brief = build_brief(cluster, rec)
    return {"ok": True, "brief": brief.to_dict()}


def handle_briefs(body: dict[str, Any]) -> dict[str, Any]:
    """Generate briefs for multiple cards. No publishing."""
    out = []
    if body.get("cards"):
        for card in body.get("cards", []):
            rank = int(card.get("rank", 0))
            cluster, rec = _card_from_dict(card)
            brief = build_brief(cluster, rec)
            brief_data = brief.to_dict()
            out.append({"rank": rank, "brief": brief_data, **brief_data})
        return {"ok": True, "briefs": out}
    for rank in body.get("ranks", []):
        card = _load_card_by_rank(int(rank))
        if card is None:
            continue
        cluster, rec = _card_from_dict(card)
        brief = build_brief(cluster, rec)
        brief_data = brief.to_dict()
        out.append({"rank": int(rank), "brief": brief_data, **brief_data})
    return {"ok": True, "briefs": out}


def _load_card_by_rank(rank: int) -> dict[str, Any] | None:
    """Find the most recent intelligence card matching a rank.

    Searches the latest run result from the current dashboard process first,
    then falls back to the most recent saved snapshot.
    """
    if not SNAPSHOTS_DIR.exists():
        return None
    snapshots = sorted(SNAPSHOTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for snapshot in snapshots[:3]:
        try:
            data = json.loads(snapshot.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for card in data.get("cards", []):
            if int(card.get("rank", 0)) == rank:
                return card
    return None


def handle_create_draft(body: dict[str, Any]) -> dict[str, Any]:
    """Create a draft from intelligence card + brief."""
    card = body.get("card", {})
    brief = body.get("brief", {})
    draft = create_draft(card, brief)
    return {"ok": True, "draft_id": draft.draft_id, "draft": draft.to_dict()}


def handle_list_drafts() -> dict[str, Any]:
    return {"ok": True, "drafts": list_drafts()}


def handle_get_draft(draft_id: str) -> dict[str, Any]:
    draft = load_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "draft not found"}
    return {"ok": True, "draft": draft.to_dict()}


def handle_update_draft(draft_id: str, body: dict[str, Any]) -> dict[str, Any]:
    draft = update_draft(draft_id, body)
    if draft is None:
        return {"ok": False, "error": "draft not found or invalid status"}
    return {"ok": True, "draft": draft.to_dict()}


def handle_draft_publish(draft_id: str) -> dict[str, Any]:
    """Publish an approved draft to the blog."""
    result = publish_blog(draft_id)
    if result.get("ok"):
        draft = load_draft(draft_id)
        return {"ok": True, "draft": draft.to_dict() if draft else {}, "blog_url": result.get("blog_url")}
    return {"ok": False, "error": result.get("error", "publish failed")}


def handle_publish_social(body: dict[str, Any]) -> dict[str, Any]:
    """Publish selected approved social drafts."""
    ids = body.get("ids", [])
    dry_run = bool(body.get("dry_run", False))
    return publish_selected_social_drafts(ids, dry_run=dry_run)


def handle_publish_due_social(body: dict[str, Any]) -> dict[str, Any]:
    """Publish scheduled social drafts whose scheduled time has passed."""
    dry_run = bool(body.get("dry_run", True))
    return publish_due_social_drafts(dry_run=dry_run)


def handle_schedule_social(body: dict[str, Any]) -> dict[str, Any]:
    """Schedule selected approved social drafts."""
    ids = body.get("ids", [])
    scheduled_at = body.get("scheduled_at", "")
    return schedule_social_drafts(ids, scheduled_at)


def handle_create_social_drafts(draft_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Generate social drafts from a published blog draft."""
    from .drafts import load_draft as load_content_draft

    draft = load_content_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "draft not found"}
    if draft.status != "published" or not draft.blog_url:
        return {"ok": False, "error": "draft must be published with a blog_url to generate social drafts"}
    platforms = body.get("platforms", [])
    if not platforms:
        return {"ok": False, "error": "no platforms selected"}
    created = create_social_drafts_from_blog(
        source_draft_id=draft_id,
        blog_url=draft.blog_url,
        title=draft.title,
        body=draft.body,
        platforms=platforms,
    )
    return {"ok": True, "drafts": [d.to_dict() for d in created]}


def handle_list_social_drafts(source_draft_id: str | None = None) -> dict[str, Any]:
    return {"ok": True, "drafts": list_social_drafts(source_draft_id=source_draft_id)}


def handle_get_social_draft(draft_id: str) -> dict[str, Any]:
    draft = load_social_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "social draft not found"}
    return {"ok": True, "draft": draft.to_dict()}


def handle_update_social_draft(draft_id: str, body: dict[str, Any]) -> dict[str, Any]:
    draft = update_social_draft(draft_id, body)
    if draft is None:
        return {"ok": False, "error": "social draft not found or invalid status"}
    return {"ok": True, "draft": draft.to_dict()}

def handle_draft_cover(draft_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not body:
        return get_cover_info(draft_id)
    style = body.get("style", "clean_tech")
    return generate_cover_for_draft(draft_id, style=style)


def handle_draft_rewrite(draft_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from .rewriter import rewrite_draft
    mode = body.get("mode", "")
    return rewrite_draft(draft_id, mode)

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
    if path == "/api/intelligence/briefs":
        return handle_briefs(body or {})
    if path == "/api/intelligence/save":
        return handle_save_snapshot()
    if path == "/api/intelligence/draft":
        return handle_create_draft(body or {})
    if path.startswith("/api/drafts/") and path.endswith("/publish"):
        draft_id = path.replace("/api/drafts/", "").replace("/publish", "")
        return handle_draft_publish(draft_id)
    if path.startswith("/api/drafts/") and path.endswith("/social"):
        draft_id = path.replace("/api/drafts/", "").replace("/social", "")
        if not body:
            return handle_list_social_drafts(draft_id)
        return handle_create_social_drafts(draft_id, body or {})
    if path.startswith("/api/drafts/") and path.endswith("/cover"):
        draft_id = path.replace("/api/drafts/", "").replace("/cover", "")
        return handle_draft_cover(draft_id, body or {})
    if path.startswith("/api/drafts/") and path.endswith("/rewrite"):
        draft_id = path.replace("/api/drafts/", "").replace("/rewrite", "")
        return handle_draft_rewrite(draft_id, body or {})
    if path.startswith("/api/drafts/"):
        draft_id = path.replace("/api/drafts/", "")
        if body:
            return handle_update_draft(draft_id, body)
        return handle_get_draft(draft_id)
    if path == "/api/drafts":
        return handle_list_drafts()
    if path == "/api/social_drafts":
        return handle_list_social_drafts()
    if path == "/api/social_drafts/publish":
        return handle_publish_social(body or {})
    if path == "/api/social_drafts/publish_due":
        return handle_publish_due_social(body or {})
    if path == "/api/social_drafts/schedule":
        return handle_schedule_social(body or {})
    if path.startswith("/api/social_drafts/") and path.endswith("/retry"):
        draft_id = path.replace("/api/social_drafts/", "").replace("/retry", "")
        return retry_social_draft(draft_id)
    if path.startswith("/api/social_drafts/"):
        draft_id = path.replace("/api/social_drafts/", "")
        if body:
            return handle_update_social_draft(draft_id, body)
        return handle_get_social_draft(draft_id)
    return {"error": "not found"}
