#!/usr/bin/env python3
"""Build With Abdallah news-analysis publisher.

This is a separate lane from the evergreen tutorial publisher. It picks a
current developer-news item from web results, writes a grounded analysis with
sources, publishes it on the site, then posts Facebook + LinkedIn with the
website article URL.
"""
import datetime
import json
import os
import re
import sys
import tempfile
import urllib.request

import requests

KIT = os.path.expanduser("~/social-media-kit")
sys.path.insert(0, KIT)
from agent.config import load_env

load_env()
sys.path.insert(0, os.path.join(KIT, "scripts"))

import blog_publisher as BP
import content_formats as CF
from agent import llm_ops as LLM
import content_research as CR
import fb_poster
import image_generator as IG
import linkedin_org_poster as LI
import social_copy

BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
DRAFTS = os.path.join(KIT, "content", "drafts")
SITE = "https://buildwithabdallah.com"

NEWS_QUERIES = [
    # --- existing developer-news coverage (kept) ---
    "developer tools official release news",
    "OpenAI developers API release official blog",
    "Laravel PHP release official news",
    "Python release developer news official",
    "React Next.js release official blog",
    ".NET C# developer release official blog",
    "GitHub developer tools release official blog",
    "Docker Kubernetes developer release official blog",
    # --- expanded AI / tech coverage ---
    "AI news this week latest models",
    "new AI tools for developers release",
    "Anthropic Claude release official blog",
    "Google Gemini AI release official blog",
    "open source LLM release news",
    "AI agents developer tools news",
    # --- preferred AI sources: Matt Wolfe / Forward Future ---
    "forwardfuture.ai AI news",
    "site:forwardfuture.ai latest AI",
    "Matt Wolfe AI news tools",
    "Future Tools AI news Matt Wolfe",
    # --- curated newsletter / aggregator sources ---
    "TLDR newsletter web version developer news",
    "site:a.tldrnewsletter.com web version developer news",
]

LOW_VALUE_DOMAINS = (
    "reddit.com", "quora.com", "medium.com", "dev.to", "hashnode.dev",
    "youtube.com", "youtu.be", "tiktok.com", "facebook.com", "x.com",
)

# Section skeletons live in the format registry (scripts/content_formats.py) so
# each news format is gated against its own shape. Every format ends on
# "What I'll Be Watching" and carries "## Sources".
DEFAULT_NEWS_FORMAT = "whats_new"

FORBIDDEN_NEWS_PHRASES = CF.FORBIDDEN_PHRASES
FORBIDDEN_REPLACEMENTS = dict(
    CF.FORBIDDEN_REPLACEMENTS,
    **{"developers should stay tuned": "developers should watch the next release notes"},
)


def _h():
    return {"Authorization": f"Bearer {os.environ.get('BLOG_API_TOKEN','')}", "Accept": "application/json"}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80].strip("-")


def slug_in_sitemap(slug):
    try:
        return bool(slug) and slug in requests.get(f"{SITE}/sitemap.xml", timeout=15).text
    except Exception:
        return False


def recent_titles(n=40):
    try:
        r = requests.get(f"{BASE}/posts", params={"per_page": n}, headers=_h(), timeout=20)
        return [p.get("title", "") for p in r.json().get("data", [])]
    except Exception:
        return []


# Topic-stem blocklist: derive normalized product/framework names from recent
# post titles and reject any candidate whose title is anchored on the same
# subject, even when the new headline is worded differently. This is what kills
# the "Docker Desktop's Latest Update" loop — once a topic is in the blocklist,
# any new candidate whose leading tokens match is filtered out before the
# picker sees it.
_BLOCKLIST_LOOKBACK_DAYS = int(os.environ.get("NEWS_TOPIC_BLOCK_DAYS", "14"))
# Leading lowercase cue words ("how", "what", "why", "behind") that begin a
# headline but aren't the subject. These are SKIPPED, not stop-the-stem.
_LEADING_CUES = {
    "how", "what", "why", "behind", "inside", "with", "the", "a", "an",
    "first", "next", "new", "deep", "deep-dive", "hands-on", "untangling",
    "decoding", "unbundling", "unpacking",
}
# Lowercase glue words that appear between proper-noun tokens in a product name
# ("GPT and Agents", "Berkshire of Software"). These are SKIPPED while we have
# a stem, but still stop the stem if seen before any subject token.
_GLUE = {"and", "of", "the", "at", "on", "in"}
# Generic shape/article verbs that mark "the subject phrase has ended" — these
# stop the stem. They include action verbs, shape nouns
# ("release", "update", "hands-on"), and article-framing words ("latest",
# "new", "critical", "official"). Case-insensitive comparison via lower().
_SHAPE_VERBS = {
    # action / verbs
    "is", "are", "was", "were", "be", "gets", "drops", "brings", "adds",
    "unveils", "debuts", "rolls", "lands", "ships", "shipped", "promises",
    "forces", "rethink", "sunset", "moves", "transforms", "introduces",
    "announces", "announced", "releases", "released", "launches", "updates",
    "patches", "enhances", "improves", "boosts", "cuts", "raises", "lowers",
    "hits", "vulnerability", "evolution", "evolving", "evolves", "pivots",
    "leap", "leaps", "transition", "behind", "review", "walkthrough", "dive",
    # shape nouns / framing words
    "release", "release:", "update", "update:", "patch", "security", "launch",
    "beta", "rc", "ga", "rtm", "preview", "alpha", "official", "video",
    "hands-on", "deep-dive", "deep", "first", "look", "toward", "towards",
    "latest", "new", "next", "now", "here", "needs", "before", "after",
    "checks", "tested", "measured", "critical", "irrelevant", "others",
    "decade", "official", "hands-on", "tested", "guide", "explainer", "deeper",
    # generic connective/word forms that often appear capitalized in titles
    "your", "their", "its", "with", "without", "for", "from", "into",
    "year", "month", "week", "today", "tomorrow", "yesterday",
    # vendor names that aren't themselves the *line* (e.g. "Microsoft Build")
    "build", "io", "ignite", "wwdc", "aws", "summit", "keynote",
}


def _stem(title):
    """Extract a normalized leading-product-phrase stem from a title.

    Reads the initial proper-noun run of a headline (capitalized or version-
    like tokens, optionally preceded by cue words like "How"/"Inside"), and
    stops at the first lowercase shape/article verb. Product names typically
    start with a capital; descriptions of the article itself ("release",
    "hands-on", "review", "gets", "drops") are lowercase and start the tail.

      "Docker Desktop's Latest Update Enhances Developer Experience" → "docker desktop"
      "Laravel's Managed Queues and Scale-to-Zero" → "laravel managed queues"
      "Kubernetes v1.36 Release: …" → "kubernetes"
      "Next.js Security Patch" → "next.js"
      "GPT-5.5 and Agents SDK" → "gpt-5.5 agents sdk"
      "How Claude Code Transforms from CLI to …" → "claude code"
      "Workday's New AI Agent Tools" → "workday"
      "Seven Enhancements Your Nuxt 4 App Needs…" → "seven enhancements"
    """
    if not title:
        return ""
    # Strip possessives, keep hyphens/periods/plus for things like "next.js".
    t = re.sub(r"'s\b|'(?=\s|$)", " ", title)
    t = re.sub(r"[^A-Za-z0-9 .\-+]", " ", t)
    parts = [p for p in t.split() if p]
    stem = []
    seen_subject = False
    for p in parts:
        pl = p.lower().strip(".,")
        if not pl:
            continue
        # First tokens may be lowercase cue words ("How", "What") — skip until
        # we hit the actual subject, but don't keep skipping past it.
        if not seen_subject and pl in _LEADING_CUES:
            continue
        # Stop at a lowercase shape verb ("Transforms", "Gets", "Release")
        # — the headline is now describing the article, not the subject.
        if pl in _SHAPE_VERBS:
            break
        # A lowercase word that isn't a known acronym/extension ends the subject.
        if p[0].islower() and pl not in {"js", "ts", "cs", "ui", "sdk", "api", "cli", "ai"}:
            if not seen_subject:
                continue
            # Glue between proper nouns ("GPT and Agents SDK") — skip, don't stop.
            if stem and pl in _GLUE:
                continue
            break
        seen_subject = True
        # Stop at a STANDALONE version/DOT-number that follows a product
        # ("kubernetes v1.36 release" → "kubernetes"). Don't fire on a
        # dotted-tail product token like "gpt-5.5" — that's part of the name.
        if re.fullmatch(r"v\d+(\.\d+)*", pl) and stem:
            break
        stem.append(pl.rstrip(":"))
        if len(stem) >= 4:
            break
    return " ".join(stem)


def recent_topic_blocklist(titles):
    """Return a set of normalized topic stems to exclude from candidate choice."""
    return {s for t in titles if (s := _stem(t))}


def _candidate_blocked(title, blocklist):
    s = _stem(title)
    if not s:
        return False
    # Exact stem match, or the candidate's stem starts with a blocked one
    # ("docker desktop" blocks "docker desktop update" without the reverse hit).
    for b in blocklist:
        if s == b or s.startswith(b + " ") or b.startswith(s + " "):
            return True
    return False


def _feed_candidates(blocklist, seen_urls, limit):
    """Pull ranked items from the in-process feed (agent.feed.build_feed).

    The feed is already being fetched + ranked 8×/day by the dashboard's
    scheduler. When the live search providers go down (which they did for a
    week straight — every news run opened with "Search returned no results
    from any provider"), reusing the feed means the picker still has real,
    current, interest-matched stories instead of falling back to whatever the
    model remembers about "Docker Desktop".

    Opt-in: NEWS_FEED_AS_SOURCE=1. Uses use_llm=False so this adds zero cost
    beyond the (already-scheduled) feed fetch — enrichment has its own budget.
    """
    if os.environ.get("NEWS_FEED_AS_SOURCE", "0").lower() not in ("1", "true", "yes"):
        return []
    try:
        from agent.feed import build_feed
        items = build_feed(use_llm=False, include_seen=False, limit=limit * 2)
    except Exception as e:
        print(f"⚠️ feed-as-source disabled: {e}")
        return []
    out = []
    for it in items:
        url = (it.url or "").strip()
        title = (it.title or "").strip()
        if not url or not title or url in seen_urls:
            continue
        if blocklist and _candidate_blocked(title, blocklist):
            continue
        seen_urls.add(url)
        out.append({
            "title": title,
            "url": url,
            "description": it.summary or it.reason or "",
            "source": it.source or "",
        })
        if len(out) >= limit:
            break
    if out:
        print(f"feed-as-source: {len(out)} ranked items injected ahead of live search")
    return out


def collect_candidates(blocklist=None):
    seen = set()
    year = datetime.date.today().year
    blocklist = blocklist or set()
    # Feed items first — they are the highest-signal, lowest-cost source we
    # already pay for. Live web search fills out the rest of the pool.
    candidates = _feed_candidates(blocklist, seen, limit=18)
    # Collect per-query so we can interleave round-robin. Otherwise the first
    # queries fill the pool and later queries (AI / Forward Future) get
    # truncated out before the story picker ever sees them.
    per_query = []
    for query in NEWS_QUERIES:
        try:
            results = CR.web_search(f"{query} {year}", count=6)
        except Exception:
            results = []
        bucket = []
        for item in results:
            url = item.get("url", "")
            title = item.get("title", "").strip()
            if not url or not title or url in seen:
                continue
            if blocklist and _candidate_blocked(title, blocklist):
                continue
            host = re.sub(r"^www\.", "", requests.utils.urlparse(url).netloc.lower())
            if any(bad in host for bad in LOW_VALUE_DOMAINS):
                continue
            seen.add(url)
            bucket.append({
                "title": title,
                "url": url,
                "description": item.get("description", ""),
                "source": item.get("source", ""),
            })
        per_query.append(bucket)

    # Round-robin interleave so every query is represented in the final pool.
    interleaved = []
    for rank in range(max((len(b) for b in per_query), default=0)):
        for bucket in per_query:
            if rank < len(bucket):
                interleaved.append(bucket[rank])
    candidates.extend(interleaved)
    return candidates[:48]


def _chat(messages, max_tokens=1200, temperature=0.35, json_mode=False):
    """Instrumented via agent.llm_ops. Still hard-fails without a key."""
    if not os.environ.get("OPENAI_API_KEY", ""):
        raise RuntimeError("OPENAI_API_KEY is required for news publishing")
    result = LLM.chat(messages, model="gpt-4o", temperature=temperature,
                      max_tokens=max_tokens, json_mode=json_mode, timeout=120,
                      job_id="news_publish")
    result.raise_for_status()
    return result.text


def choose_story(candidates, titles, spec, blocklist=None):
    blocklist = blocklist or set()
    avoid_titles = "\n".join(f"- {t}" for t in titles if t)
    avoid_topics = "\n".join(f"- {s}" for s in sorted(blocklist)) if blocklist else ""
    options = "\n".join(
        f"{i+1}. {c['title']}\n   {c['url']}\n   {c.get('description','')[:220]}"
        for i, c in enumerate(candidates)
    )
    avoid_block = (
        f"SUBJECTS ALREADY COVERED IN THE LAST {_BLOCKLIST_LOOKBACK_DAYS} DAYS — do not pick "
        "any candidate whose leading product/framework topic matches one of these stems, even "
        "worded differently:\n" + avoid_topics + "\n\n"
    ) if avoid_topics else ""
    prompt = (
        "Pick ONE developer-news story for Build With Abdallah. Prefer official or primary sources, "
        "recent product/framework/API releases, security updates, or platform changes that developers "
        "can act on. Avoid rumors, generic listicles, and duplicate topics.\n\n"
        f"ANGLE FOR THIS PIECE: {spec['label']}.\n"
        f"Pick the candidate that best supports this angle — {spec['angle']}. If no candidate fits "
        "the angle well, pick the strongest story anyway rather than forcing a bad fit.\n\n"
        f"{CF.title_rules(spec)}\n"
        "The headline must name the actual technologies being discussed. Prefer titles like "
        "'Gemini 3.5 drops function-call latency to 200ms — what changes for agent code' over vague "
        "titles like 'Google I/O 2026: Key Developer Announcements'.\n\n"
        "Weight AI and developer-tooling stories highly (new AI models, AI agents, AI dev tools, "
        "LLM releases). Forward Future (forwardfuture.ai) and Matt Wolfe are trusted AI-roundup "
        "sources: when one of them covers a concrete AI development, you may pick it and cite the "
        "forwardfuture.ai URL in source_urls, but always also include the underlying official/primary "
        "source URL when one is available.\n\n"
        + avoid_block +
        f"ALREADY PUBLISHED — do not repeat any of these subjects, even from a new angle:\n{avoid_titles}\n\n"
        f"CANDIDATES:\n{options}\n\n"
        "Return 2-3 source_urls where the candidates support it: the official/primary source "
        "first, then any independent coverage of the SAME story. Corroboration is what separates "
        "a report from a rumour. Only return one URL if genuinely nothing else covers this.\n\n"
        "Return STRICT JSON: "
        '{"title":"clear news-analysis headline","slug":"kebab-case","source_urls":["https://..."],'
        '"why_it_matters":"one sentence"}'
    )
    obj = json.loads(_chat([{"role": "user", "content": prompt}], max_tokens=500, json_mode=True))
    urls = [u for u in obj.get("source_urls", []) if isinstance(u, str) and u.startswith("http")]
    if not urls:
        raise RuntimeError("story picker returned no source URLs")
    title = obj["title"].strip()
    return {
        "title": title,
        "slug": _slug(obj.get("slug") or title),
        "source_urls": urls[:5],
        "why_it_matters": obj.get("why_it_matters", "").strip(),
    }


# Minimum extracted source text before the writer is allowed to run. The
# prompt instructs the model to use ONLY the provided sources; when extraction
# returns almost nothing it has no choice but to write from memory, which is
# how a 1,170-word article shipped behind a press release that yielded 250
# characters. Raise/lower with NEWS_MIN_SOURCE_CHARS.
MIN_SOURCE_CHARS = int(os.environ.get("NEWS_MIN_SOURCE_CHARS", "800"))


def fetch_sources(urls):
    source_blocks = []
    for url in urls:
        text = CR.extract_article(url, max_chars=3500)
        source_blocks.append(f"URL: {url}\nEXTRACT:\n{text}")
    return "\n\n---\n\n".join(source_blocks)


def extracted_chars(source_text):
    """Characters of real source prose, excluding the URL/EXTRACT scaffolding."""
    stripped = re.sub(r"URL: \S+|EXTRACT:|^-+$", "", source_text or "", flags=re.M)
    return len(re.sub(r"\s+", "", stripped))


def write_news_article(story, source_text, spec):
    sections = "\n".join(f"- {s}" for s in spec["sections"])
    prompt = (
        f"Write a Build With Abdallah developer news article in Markdown, in the "
        f"'{spec['label']}' format.\n\n"
        "The goal is NOT to sound like a news wire service, press release, corporate blog, or "
        "AI-generated summary. Write like a real software engineer sharing important industry updates "
        "with Laravel developers, Python developers, AI builders, Raspberry Pi enthusiasts, and "
        "independent software developers.\n\n"
        "Rules:\n"
        "- Use ONLY the provided source material. Do not invent dates, version numbers, claims, quotes, or features.\n"
        "- Any number or benchmark that came from the vendor's own materials must be attributed as vendor-reported.\n"
        "- Use clear, simple English. Avoid buzzwords and marketing language.\n"
        "- Forbidden phrases: revolutionary, game-changing, cutting-edge, transformative, industry-leading, next-generation, groundbreaking, unprecedented, world-class, future-proof.\n"
        f"- {spec['min_words']}-1500 words for major news stories.\n"
        "- Start with '# {title}'.\n"
        f"- Include these exact H2 sections, in this order:\n{sections}\n\n"
        f"Section guidance:\n{spec['brief']}\n\n"
        "- The Sources section must list every source URL used as Markdown links.\n"
        # These mirror content_formats.substance_issues(). Stating them here
        # lets the writer satisfy the gate instead of merely failing it.
        + (f"- Include at least {spec['min_code']} fenced code blocks with language labels: the actual "
           "command, config, diff, or API call a developer runs. Real copy-pasteable code taken from "
           "or directly implied by the sources — never a prose description of code, never invented "
           "API surface.\n" if spec.get("min_code") else "")
        + "- Cite every source you were given, not just the first. Where two sources cover the same "
        "claim, link both — one link is a single unverified voice.\n"
        "- If this is a security story, name the specific CVE identifiers (CVE-YYYY-NNNNN) from "
        "the sources, or link the vendor's security advisory. A security article that names no "
        "vulnerability is not publishable — if the sources do not identify one, say plainly which "
        "advisory is pending rather than padding the section.\n"
        "- If the headline names a version number, discuss that exact version in the body.\n"
        "- Avoid these filler words; they add length without meaning: ever-evolving, landscape, "
        "pivotal, crucial, vital, comprehensive, myriad, plethora, testament, paradigm, delve, "
        "underscore, streamline, compelling, 'it is worth noting', 'significant milestone'.\n"
        "- What I'll Be Watching is the FINAL section.\n"
        "- Never write generic conclusions like 'Time will tell', 'The future looks bright', or 'Developers should stay tuned'. Provide a specific takeaway.\n"
        "- After drafting, review and remove repetitive phrasing, generic AI language, and obvious summary-style sentences.\n\n"
        f"TITLE: {story['title']}\nWHY IT MATTERS: {story.get('why_it_matters','')}\n\n"
        f"SOURCE MATERIAL:\n{source_text}"
    )
    body = _chat([{"role": "user", "content": prompt}], max_tokens=2600, temperature=0.35)
    best = normalize_news_sections(clean_forbidden_phrases(body))
    best = ensure_required_sections(best, story.get("source_urls", []))

    # Expand until comfortably above the 750-word publish gate. The model often
    # under-delivers on a single expand pass (and can even shorten the draft),
    # so retry and keep the longest draft instead of returning the last one.
    for _ in range(3):
        if len(best.split()) >= 800:
            break
        expand_prompt = (
            "Expand this developer news article to 900-1500 words without adding facts that are "
            "not supported by the source material. Keep the same title, the same H2 sections in the "
            "same order, and the Sources section. Deepen the existing sections with practical "
            "developer impact, concrete examples, and specifics — do not add new sections. "
            "The result MUST be at least 900 words.\n\n"
            f"SOURCE MATERIAL:\n{source_text}\n\n"
            f"ARTICLE:\n{best}"
        )
        expanded = normalize_news_sections(clean_forbidden_phrases(
            _chat([{"role": "user", "content": expand_prompt}], max_tokens=3000, temperature=0.3)
        ))
        expanded = ensure_required_sections(expanded, story.get("source_urls", []))
        if len(expanded.split()) > len(best.split()):
            best = expanded
    return best


def clean_forbidden_phrases(body):
    """Repair hype wording so a good draft isn't binned over one word.

    Longest phrase first — otherwise "stay tuned" rewrites the middle of
    "developers should stay tuned" and leaves a broken sentence.
    """
    cleaned = body or ""
    for phrase in sorted(FORBIDDEN_REPLACEMENTS, key=len, reverse=True):
        cleaned = re.sub(re.escape(phrase), FORBIDDEN_REPLACEMENTS[phrase], cleaned, flags=re.I)
    return cleaned


def normalize_news_sections(body):
    """Keep Sources present but make What I'll Be Watching the final section."""
    text = body or ""
    watch = "## What I'll Be Watching"
    sources = "## Sources"
    if watch not in text or sources not in text:
        return text
    if text.rfind(sources) < text.rfind(watch):
        return text

    start = text.find(watch)
    next_section = re.search(r"\n##\s+", text[start + len(watch):])
    end = start + len(watch) + next_section.start() if next_section else len(text)
    watch_block = text[start:end].strip()
    without_watch = (text[:start] + text[end:]).rstrip()
    return without_watch + "\n\n" + watch_block + "\n"


def ensure_required_sections(body, source_urls):
    """Fallback for LLMs that omit required sections: append a minimal Sources block
    from the verified source URLs so the quality gate doesn't reject a usable draft."""
    text = (body or "").rstrip()
    if "## Sources" not in text:
        links = "\n".join(f"- [{u}]({u})" for u in (source_urls or []) if u)
        if links:
            text += f"\n\n## Sources\n\n{links}\n"
    return text


def news_quality_issues(body, format_id=DEFAULT_NEWS_FORMAT, title=""):
    issues = CF.quality_issues("news", body, format_id)
    if "## Sources" in body and body.rfind("## Sources") > body.rfind("## What I'll Be Watching"):
        issues.append("What I'll Be Watching must be the final section")
    # Shape is not substance: the structural gate passed a security piece that
    # named no CVE and cited only Wikipedia.
    issues.extend(CF.substance_issues(title, body))
    return issues



def publish_social(title, body, url, cover):
    text = social_copy.make_news_social_copy(title, body, url)
    local = (cover or {}).get("path")
    if local and os.path.exists(local):
        fb_poster.post_photo(local, caption=text)
    else:
        fb_poster.post_text(text, link=url)

    # No X here on purpose. Every X post is billed, so X carries the weekly
    # GitHub roundup only (scripts/github_roundup.py) — never the 5×/day news
    # lane, which would spend on 5 posts a day indefinitely.
    token, _ = LI.fetch_org_token()
    if not token:
        print("⚠️ LinkedIn skipped: no token")
        return False
    author = linkedin_person_urn(token)
    image_path = None
    if local and os.path.exists(local):
        image_path = local
    elif (cover or {}).get("url"):
        image_path = os.path.join(tempfile.mkdtemp(prefix="news_li_"), "cover.png")
        try:
            urllib.request.urlretrieve(cover["url"], image_path)
        except Exception:
            image_path = None
    return bool(LI.post_org(
        text,
        image_path=image_path,
        title=title[:90],
        token=token,
        author=author,
        post_kind="news",
    ))


def linkedin_person_urn(token):
    try:
        r = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        sub = r.json().get("sub")
        if sub:
            return f"urn:li:person:{sub}"
    except Exception:
        pass
    return os.environ.get("LINKEDIN_PERSON_URN", "urn:li:person:ABnvUUsgfB")


def main():
    recent = recent_titles(n=max(40, _BLOCKLIST_LOOKBACK_DAYS * 2 + 6))
    blocklist = recent_topic_blocklist(recent)
    candidates = collect_candidates(blocklist=blocklist)
    if len(candidates) < 3:
        if blocklist:
            print(f"news publish failed: only {len(candidates)} candidates "
                  f"after filtering {len(blocklist)} recent topic stems. "
                  f"Broaden sources or extend blocklist window.")
        else:
            print("news publish failed: not enough grounded candidates")
        return 1

    fmt = CF.pick_format("news")
    spec = CF.get("news", fmt)
    print(f"news format: {fmt} ({spec['label']})")

    # A picked story can still be ungrounded (blocked/paywalled sources), so
    # retry the picker up to 3 times instead of burning the whole run — the
    # 2026-08-26/27 streak of dead news runs was one bad pick per cycle.
    avoid = list(recent)
    story = source_text = None
    grounded = 0
    for _attempt in range(3):
        story = choose_story(candidates, avoid, spec, blocklist=blocklist)
        print(f"news: {story['title']}\n  slug: {story['slug']}")
        if slug_in_sitemap(story["slug"]):
            # The old code had no slug check at all on this lane, which is how the
            # same Google I/O story shipped twice on consecutive days.
            print("news slug already published — skipping this cycle (no publish)")
            return 0
        source_text = fetch_sources(story["source_urls"])
        grounded = extracted_chars(source_text)
        if grounded >= MIN_SOURCE_CHARS:
            break
        print(f"news: source extraction yielded only {grounded} chars "
              f"(need {MIN_SOURCE_CHARS}) — refusing to write an ungrounded article")
        avoid = avoid + [story["title"]]
    if grounded < MIN_SOURCE_CHARS:
        print("news publish failed: 3 story picks in a row lacked extractable sources")
        return 1
    print(f"sources extracted: {grounded} chars")
    body = write_news_article(story, source_text, spec)
    wc = len(body.split())
    source_hits = sum(1 for u in story["source_urls"] if u in body)
    distinct = len({CF._host(u) for u in CF.source_urls(body)})
    fences = body.count("```") // 2
    print(f"article: {wc} words, sources linked: {source_hits}, "
          f"distinct source hosts: {distinct}, code blocks: {fences} "
          f"(min_code={spec.get('min_code', 0)}, NEWS_MIN_SOURCES={CF.MIN_SOURCES})")
    issues = news_quality_issues(body, fmt, title=story["title"])
    if wc < 750 or source_hits < 1 or issues:
        if issues:
            print("quality issues: " + "; ".join(issues))
        print("news article failed quality gate; no publish")
        return 1

    os.makedirs(DRAFTS, exist_ok=True)
    draft_path = os.path.join(DRAFTS, f"{datetime.date.today().isoformat()}_news_{story['slug']}.md")
    with open(draft_path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"Saved news draft to {draft_path}")

    if "--dry-run" in sys.argv:
        print("=== DRY RUN — no cover, no site publish, no social ===")
        print(f"source_urls: {story['source_urls']}")
        print(f"why_it_matters: {story.get('why_it_matters','')}")
        return 0

    cover = IG.generate_cover(
        story["title"],
        branding={
            "accent_color": "#0f766e",
            "subtitle": "Build With Abdallah news analysis",
            "footer": "Build With Abdallah | developer news analysis",
        },
    )
    cover_url = (cover or {}).get("url") or (cover or {}).get("path") or ""
    excerpt = story.get("why_it_matters") or re.sub(r"\s+", " ", body.split("\n\n", 2)[1])[:180]
    post = BP.publish_article(
        title=story["title"],
        slug=story["slug"],
        content=body,
        excerpt=excerpt,
        publish=True,
        featured=False,
        cover_image_url=cover_url,
    )
    if not post:
        print("news publish failed")
        return 1
    print(f"Published news: Post ID {post.get('id')}, Slug: {post.get('slug')}")
    CF.record("news", fmt, post.get("slug", story["slug"]), story["title"])

    url = f"{SITE}/tutorials/{post.get('slug', story['slug'])}"
    li_ok = publish_social(story["title"], body, url, cover)
    print(f"News social: Facebook attempted, LinkedIn={'ok' if li_ok else 'failed/skipped'}, X=off (roundup only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
