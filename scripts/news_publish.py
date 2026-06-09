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
import content_research as CR
import fb_poster
import image_generator as IG
import linkedin_org_poster as LI
import social_copy

BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
DRAFTS = os.path.join(KIT, "content", "drafts")
SITE = "https://buildwithabdallah.com"

NEWS_QUERIES = [
    "developer tools official release news",
    "OpenAI developers API release official blog",
    "Laravel PHP release official news",
    "Python release developer news official",
    "React Next.js release official blog",
    ".NET C# developer release official blog",
    "GitHub developer tools release official blog",
    "Docker Kubernetes developer release official blog",
]

LOW_VALUE_DOMAINS = (
    "reddit.com", "quora.com", "medium.com", "dev.to", "hashnode.dev",
    "youtube.com", "youtu.be", "tiktok.com", "facebook.com", "x.com",
)

REQUIRED_NEWS_SECTIONS = [
    "## What Happened",
    "## Why Developers Should Care",
    "## Real-World Example",
    "## Builder's Take",
    "## Sources",
    "## What I'll Be Watching",
]

FORBIDDEN_NEWS_PHRASES = [
    "revolutionary",
    "game-changing",
    "cutting-edge",
    "transformative",
    "industry-leading",
    "next-generation",
    "groundbreaking",
    "unprecedented",
    "world-class",
    "future-proof",
    "time will tell",
    "stay tuned",
    "developers should stay tuned",
    "the future looks bright",
    "this changes everything",
    "exciting times ahead",
]

FORBIDDEN_REPLACEMENTS = {
    "revolutionary": "important",
    "game-changing": "important",
    "cutting-edge": "new",
    "transformative": "useful",
    "industry-leading": "widely used",
    "next-generation": "new",
    "groundbreaking": "important",
    "unprecedented": "unusual",
    "world-class": "strong",
    "future-proof": "easier to maintain",
    "time will tell": "the practical results still need evidence",
    "stay tuned": "watch the next release notes",
    "developers should stay tuned": "developers should watch the next release notes",
    "the future looks bright": "the useful part depends on real adoption",
    "this changes everything": "this changes the tradeoffs",
    "exciting times ahead": "the next few releases matter",
}


def _h():
    return {"Authorization": f"Bearer {os.environ.get('BLOG_API_TOKEN','')}", "Accept": "application/json"}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80].strip("-")


def recent_titles(n=40):
    try:
        r = requests.get(f"{BASE}/posts", params={"per_page": n}, headers=_h(), timeout=20)
        return [p.get("title", "") for p in r.json().get("data", [])]
    except Exception:
        return []


def collect_candidates():
    seen = set()
    candidates = []
    year = datetime.date.today().year
    for query in NEWS_QUERIES:
        try:
            results = CR.web_search(f"{query} {year}", count=6)
        except Exception:
            results = []
        for item in results:
            url = item.get("url", "")
            title = item.get("title", "").strip()
            if not url or not title or url in seen:
                continue
            host = re.sub(r"^www\.", "", requests.utils.urlparse(url).netloc.lower())
            if any(bad in host for bad in LOW_VALUE_DOMAINS):
                continue
            seen.add(url)
            candidates.append({
                "title": title,
                "url": url,
                "description": item.get("description", ""),
                "source": item.get("source", ""),
            })
    return candidates[:28]


def _chat(messages, max_tokens=1200, temperature=0.35, json_mode=False):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for news publishing")
    payload = {
        "model": "gpt-4o",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def choose_story(candidates, titles):
    avoid = "\n".join(f"- {t}" for t in titles if t)
    options = "\n".join(
        f"{i+1}. {c['title']}\n   {c['url']}\n   {c.get('description','')[:220]}"
        for i, c in enumerate(candidates)
    )
    prompt = (
        "Pick ONE developer-news story for Build With Abdallah. Prefer official or primary sources, "
        "recent product/framework/API releases, security updates, or platform changes that developers "
        "can act on. Avoid rumors, generic listicles, and duplicate topics.\n\n"
        "The headline must name the actual technologies being discussed. Prefer titles like "
        "'Google I/O 2026: Gemini 3.5, Managed Agents, and AI Studio Explained' over vague titles "
        "like 'Google I/O 2026: Key Developer Announcements'.\n\n"
        f"ALREADY PUBLISHED:\n{avoid}\n\n"
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


def write_news_article(story, source_text):
    prompt = (
        "Write a Build With Abdallah developer news-analysis article in Markdown.\n\n"
        "The goal is NOT to sound like a news wire service, press release, corporate blog, or "
        "AI-generated summary. Write like a real software engineer sharing important industry updates "
        "with Laravel developers, Python developers, AI builders, Raspberry Pi enthusiasts, and "
        "independent software developers.\n\n"
        "Rules:\n"
        "- Use ONLY the provided source material. Do not invent dates, version numbers, claims, quotes, or features.\n"
        "- Use clear, simple English. Avoid buzzwords and marketing language.\n"
        "- Forbidden phrases: revolutionary, game-changing, cutting-edge, transformative, industry-leading, next-generation, groundbreaking, unprecedented, world-class, future-proof.\n"
        "- 800-1500 words for major news stories.\n"
        "- Start with '# {title}'.\n"
        "- Include these exact sections in this order: What Happened, Why Developers Should Care, Real-World Example, Builder's Take, Sources, What I'll Be Watching.\n"
        "- What Happened: brief factual summary.\n"
        "- Why Developers Should Care: practical impact, why the feature exists, what problem it solves, who benefits, and drawbacks.\n"
        "- Real-World Example: at least one concrete Laravel, Python, AI, DevOps, Raspberry Pi, or full-stack example.\n"
        "- Builder's Take: short opinionated section from an independent developer. Include what seems useful, what may be hype, what I would test first, and limitations or unanswered questions.\n"
        "- The Sources section must list every source URL used as Markdown links.\n"
        "- What I'll Be Watching: final section. End the article with 2-4 specific developments, release dates, benchmarks, APIs, SDKs, integrations, or adoption trends worth monitoring.\n"
        "- Never write generic conclusions like 'Time will tell', 'The future looks bright', or 'Developers should stay tuned'. Provide a specific takeaway.\n"
        "- After drafting, review and remove repetitive phrasing, generic AI language, and obvious summary-style sentences.\n\n"
        f"TITLE: {story['title']}\nWHY IT MATTERS: {story.get('why_it_matters','')}\n\n"
        f"SOURCE MATERIAL:\n{source_text}"
    )
    body = _chat([{"role": "user", "content": prompt}], max_tokens=2600, temperature=0.35)
    if len(body.split()) >= 800:
        return normalize_news_sections(clean_forbidden_phrases(body))
    expand_prompt = (
        "Expand this developer news-analysis article to 800-1500 words without adding facts that are "
        "not supported by the source material. Keep the same title and Sources section. Add more practical "
        "developer impact, a concrete real-world example, an opinionated Builder's Take, and specific "
        "items for What I'll Be Watching.\n\n"
        f"SOURCE MATERIAL:\n{source_text}\n\n"
        f"ARTICLE:\n{body}"
    )
    expanded = _chat([{"role": "user", "content": expand_prompt}], max_tokens=3000, temperature=0.3)
    return normalize_news_sections(clean_forbidden_phrases(expanded))


def clean_forbidden_phrases(body):
    cleaned = body or ""
    for phrase, replacement in FORBIDDEN_REPLACEMENTS.items():
        cleaned = re.sub(re.escape(phrase), replacement, cleaned, flags=re.I)
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


def news_quality_issues(body):
    issues = []
    for section in REQUIRED_NEWS_SECTIONS:
        if section.lower() not in body.lower():
            issues.append(f"missing section: {section}")
    low = body.lower()
    for phrase in FORBIDDEN_NEWS_PHRASES:
        if phrase in low:
            issues.append(f"forbidden phrase: {phrase}")
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
    return bool(LI.post_org(text, image_path=image_path, title=title[:90], token=token, author=author))


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

    story = choose_story(candidates, recent_titles())
    print(f"news: {story['title']}\n  slug: {story['slug']}")
    source_text = fetch_sources(story["source_urls"])
    body = write_news_article(story, source_text)
    wc = len(body.split())
    source_hits = sum(1 for u in story["source_urls"] if u in body)
    print(f"article: {wc} words, sources linked: {source_hits}")
    issues = news_quality_issues(body)
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

    url = f"{SITE}/tutorials/{post.get('slug', story['slug'])}"
    li_ok = publish_social(story["title"], body, url, cover)
    print(f"News social: Facebook attempted, LinkedIn={'ok' if li_ok else 'failed/skipped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
