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


def collect_candidates():
    seen = set()
    year = datetime.date.today().year
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
    candidates = []
    for rank in range(max((len(b) for b in per_query), default=0)):
        for bucket in per_query:
            if rank < len(bucket):
                candidates.append(bucket[rank])
    return candidates[:36]


def _chat(messages, max_tokens=1200, temperature=0.35, json_mode=False):
    """Instrumented via agent.llm_ops. Still hard-fails without a key."""
    if not os.environ.get("OPENAI_API_KEY", ""):
        raise RuntimeError("OPENAI_API_KEY is required for news publishing")
    result = LLM.chat(messages, model="gpt-4o", temperature=temperature,
                      max_tokens=max_tokens, json_mode=json_mode, timeout=120,
                      job_id="news_publish")
    result.raise_for_status()
    return result.text


def choose_story(candidates, titles, spec):
    avoid = "\n".join(f"- {t}" for t in titles if t)
    options = "\n".join(
        f"{i+1}. {c['title']}\n   {c['url']}\n   {c.get('description','')[:220]}"
        for i, c in enumerate(candidates)
    )
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
        f"ALREADY PUBLISHED — do not repeat any of these subjects, even from a new angle:\n{avoid}\n\n"
        f"CANDIDATES:\n{options}\n\n"
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


def fetch_sources(urls):
    source_blocks = []
    for url in urls:
        text = CR.extract_article(url, max_chars=3500)
        source_blocks.append(f"URL: {url}\nEXTRACT:\n{text}")
    return "\n\n---\n\n".join(source_blocks)


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


def news_quality_issues(body, format_id=DEFAULT_NEWS_FORMAT):
    issues = CF.quality_issues("news", body, format_id)
    if "## Sources" in body and body.rfind("## Sources") > body.rfind("## What I'll Be Watching"):
        issues.append("What I'll Be Watching must be the final section")
    return issues


def publish_social(title, body, url, cover):
    text = social_copy.make_news_social_copy(title, body, url)
    local = (cover or {}).get("path")
    if local and os.path.exists(local):
        fb_poster.post_photo(local, caption=text)
    else:
        fb_poster.post_text(text, link=url)

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
    candidates = collect_candidates()
    if len(candidates) < 3:
        print("news publish failed: not enough grounded candidates")
        return 1

    fmt = CF.pick_format("news")
    spec = CF.get("news", fmt)
    print(f"news format: {fmt} ({spec['label']})")

    story = choose_story(candidates, recent_titles(), spec)
    print(f"news: {story['title']}\n  slug: {story['slug']}")
    if slug_in_sitemap(story["slug"]):
        # The old code had no slug check at all on this lane, which is how the
        # same Google I/O story shipped twice on consecutive days.
        print("news slug already published — skipping this cycle (no publish)")
        return 0
    source_text = fetch_sources(story["source_urls"])
    body = write_news_article(story, source_text, spec)
    wc = len(body.split())
    source_hits = sum(1 for u in story["source_urls"] if u in body)
    print(f"article: {wc} words, sources linked: {source_hits}")
    issues = news_quality_issues(body, fmt)
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
    print(f"News social: Facebook attempted, LinkedIn={'ok' if li_ok else 'failed/skipped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
