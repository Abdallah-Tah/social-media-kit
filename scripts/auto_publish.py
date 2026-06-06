#!/usr/bin/env python3
"""Deterministic Build With Abdallah publisher (reliable replacement for the
flaky multi-step writing agent).

Pipeline, no autonomy required:
  1. Fetch recent post titles (de-dupe) and pick the least-covered cluster.
  2. Web-search (SearXNG) that cluster for a genuinely current angle.
  3. gpt-4o picks ONE specific, non-duplicate tutorial topic.
  4. Write a complete tutorial (two-halves writer → ~1,500 words, real code).
  5. Generate + host the cover, publish the article, post the Facebook photo.

Prints "Saved draft to <path>" and "Published: Post ID <id>" so the cron's
existing markers/flow keep working. Reels + LinkedIn are done by the cron after.
"""
import os
import re
import sys
import json
import datetime
import requests

KIT = os.path.expanduser("~/social-media-kit")
sys.path.insert(0, KIT)
from agent.config import load_env
load_env()
sys.path.insert(0, os.path.join(KIT, "scripts"))

import image_generator as IG
import blog_publisher as BP
import content_research as CR
from enforce_published_quality import write_article  # the reliable two-halves writer

BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
DRAFTS = os.path.join(KIT, "content", "drafts")

CLUSTERS = {
    "Laravel/PHP": ["laravel", "php", "pennant", "eloquent", "artisan", "symfony", "composer"],
    "Python": ["python", "fastapi", "django", "flask", "pydantic", "pandas", "pip"],
    "React/Next.js": ["react", "next.js", "nextjs", "remix", "jsx"],
    "Vue/Nuxt": ["vue", "nuxt", "pinia", "vite"],
    ".NET/C#": [".net", "c#", "csharp", "asp.net", "blazor", "dotnet"],
    "C++": ["c++", "cpp", "cmake"],
    "AI agents": ["ai agent", "agents", "llm", "mcp", "rag", "claude", "openai", "pydantic ai"],
    "Automation / DevOps": ["automation", "docker", "ci/cd", "github actions", "cron", "devops"],
}


def _h(json_ct=False):
    h = {"Authorization": f"Bearer {os.environ.get('BLOG_API_TOKEN','')}", "Accept": "application/json"}
    if json_ct:
        h["Content-Type"] = "application/json"
    return h


def recent_titles(n=25):
    try:
        r = requests.get(f"{BASE}/posts", params={"per_page": n}, headers=_h(), timeout=20)
        return [p.get("title", "") for p in r.json().get("data", [])]
    except Exception:
        return []


def pick_cluster(titles):
    """Pick the cluster least represented in recent posts (rotate the stack)."""
    blob = " ".join(titles).lower()
    counts = {c: sum(blob.count(k) for k in kws) for c, kws in CLUSTERS.items()}
    return min(counts, key=counts.get)


def _chat(messages, max_tokens=400, temperature=0.6):
    key = os.environ.get("OPENAI_API_KEY", "")
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "gpt-4o", "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def find_topic(cluster, titles):
    # Pull current signal from the web so the topic isn't anchored to old model knowledge.
    search_lines = []
    for q in (f"{cluster} new release features {datetime.date.today().year}",
              f"{cluster} popular library tutorial {datetime.date.today().year}"):
        try:
            for res in CR.web_search(q, count=5):
                t = res.get("title", "")
                if t:
                    search_lines.append("- " + t)
        except Exception:
            pass
    search_block = "\n".join(search_lines[:12]) or "(no search results)"
    avoid = "\n".join("- " + t for t in titles if t)

    prompt = (
        f"You are choosing ONE hands-on developer tutorial topic in the '{cluster}' area for the "
        "Build With Abdallah blog. Use the current web signals to stay relevant.\n\n"
        f"CURRENT WEB SIGNALS:\n{search_block}\n\n"
        f"ALREADY PUBLISHED (do NOT duplicate the subject of any of these, even reworded):\n{avoid}\n\n"
        "Pick ONE specific, practical tutorial subject (one library/feature/use case) that is NOT a "
        "duplicate and is genuinely useful to build. Return STRICT JSON: "
        '{\"title\":\"<clear specific tutorial title, no clickbait>\",\"slug\":\"<kebab-case-slug>\"}.'
    )
    try:
        obj = json.loads(re.search(r"\{.*\}", _chat([{"role": "user", "content": prompt}],
                                                    max_tokens=200), re.S).group(0))
        title = obj["title"].strip()
        slug = re.sub(r"[^a-z0-9-]", "", obj.get("slug", "").lower().replace(" ", "-")).strip("-")
        return title, (slug or re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:70].strip("-"))
    except Exception as e:
        print(f"topic pick failed ({e}); falling back.")
        return f"Getting Started with {cluster}: A Practical Guide", None


def slug_in_sitemap(slug):
    try:
        return slug in requests.get("https://buildwithabdallah.com/sitemap.xml", timeout=15).text
    except Exception:
        return False


def main():
    titles = recent_titles()
    cluster = pick_cluster(titles)
    print(f"cluster: {cluster}")
    title, slug = find_topic(cluster, titles)
    if not slug:
        slug = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:70].strip("-")
    if slug_in_sitemap(slug):
        slug = f"{slug}-{datetime.date.today():%m%d}"
    print(f"topic: {title}\n  slug: {slug}")

    body = write_article(title)
    wc = len(body.split())
    print(f"article: {wc} words, {body.count('```')//2} code blocks")
    if wc < 700:
        print("article too short — aborting (no publish)")
        return 1

    # Save a local draft so the cron's "Saved draft to" marker is satisfied.
    os.makedirs(DRAFTS, exist_ok=True)
    draft_path = os.path.join(DRAFTS, f"{datetime.date.today().isoformat()}_{slug}.md")
    with open(draft_path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"Saved draft to {draft_path}")

    cover = IG.generate_cover(title, branding={"accent_color": "#2563eb"})
    cover_url = (cover or {}).get("url") or (cover or {}).get("path") or ""

    excerpt = " ".join(re.sub(r"[#*`>\-]", "", body.split("\n\n", 2)[1]).split())[:180] if "\n\n" in body else ""
    post = BP.publish_article(title=title, slug=slug, content=body, excerpt=excerpt,
                              publish=True, cover_image_url=cover_url)
    if not post:
        print("publish failed")
        return 1
    print(f"Published: Post ID {post.get('id')}, Slug: {post.get('slug')}")

    # Facebook photo post (website is live; link back).
    try:
        import fb_poster
        url = f"https://buildwithabdallah.com/tutorials/{post.get('slug', slug)}"
        import social_copy
        cap = social_copy.make_social_copy(title, body, url)
        local = (cover or {}).get("path")
        if local and os.path.exists(local):
            fb_poster.post_photo(local, caption=cap)
        else:
            fb_poster.post_text(cap, link=url)
    except Exception as e:
        print(f"facebook post failed (non-fatal): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
