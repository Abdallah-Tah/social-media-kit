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
import content_formats as CF
from agent import llm_ops as LLM
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
    """Instrumented via agent.llm_ops; raises on failure as it always has."""
    result = LLM.chat(messages, model="gpt-4o", temperature=temperature,
                      max_tokens=max_tokens, timeout=120, job_id="auto_publish")
    result.raise_for_status()
    return result.text


def find_topic(cluster, titles, spec):
    """Pick a topic that fits the chosen FORMAT, not just the cluster.

    The format's angle is what stops this returning yet another "build a CRUD
    app with X" — a debugging post-mortem needs a failure mode, a benchmark
    needs an unanswered performance question, and so on.
    """
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
        f"You are choosing ONE developer article topic in the '{cluster}' area for the "
        "Build With Abdallah blog. Use the current web signals to stay relevant.\n\n"
        f"ARTICLE FORMAT: {spec['label']}\n"
        f"Find a topic that fits this format specifically — {spec['angle']}.\n\n"
        f"{CF.title_rules(spec)}\n\n"
        f"CURRENT WEB SIGNALS:\n{search_block}\n\n"
        f"ALREADY PUBLISHED (do NOT duplicate the subject of any of these, even reworded):\n{avoid}\n\n"
        "Pick ONE specific subject (one library, feature, failure mode, or decision) that is NOT a "
        "duplicate and that a working developer would actually search for. Return STRICT JSON: "
        '{"title":"<specific title following the style rules above>","slug":"<kebab-case-slug>"}.'
    )
    try:
        obj = json.loads(re.search(r"\{.*\}", _chat([{"role": "user", "content": prompt}],
                                                    max_tokens=200), re.S).group(0))
        title = obj["title"].strip()
        slug = re.sub(r"[^a-z0-9-]", "", obj.get("slug", "").lower().replace(" ", "-")).strip("-")
        return title, (slug or re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:70].strip("-"))
    except Exception as e:
        print(f"topic pick failed ({e}); falling back.")
        return f"{cluster} in practice: {spec['label'].lower()}", None


def slug_in_sitemap(slug):
    try:
        return slug in requests.get("https://buildwithabdallah.com/sitemap.xml", timeout=15).text
    except Exception:
        return False


def main():
    titles = recent_titles()
    cluster = pick_cluster(titles)
    fmt = CF.pick_format("tutorial")
    spec = CF.get("tutorial", fmt)
    print(f"cluster: {cluster}\nformat: {fmt} ({spec['label']})")

    # A slug already in the sitemap means the TOPIC is a duplicate. Suffixing it
    # with a date (the old behaviour) just published the same article twice under
    # a different URL — retry the pick instead.
    title = slug = None
    seen = list(titles)
    for attempt in range(3):
        title, slug = find_topic(cluster, seen, spec)
        if not slug:
            slug = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:70].strip("-")
        if not slug_in_sitemap(slug):
            break
        print(f"  duplicate slug '{slug}' already on the site — repicking ({attempt + 1}/3)")
        seen.append(title)
        title = slug = None
    if not slug:
        print("topic pick kept returning duplicates — aborting (no publish)")
        return 1
    print(f"topic: {title}\n  slug: {slug}")

    body = write_article(title, fmt)
    wc = len(body.split())
    print(f"article: {wc} words, {body.count('```')//2} code blocks")
    if wc < 700:
        print("article too short — aborting (no publish)")
        return 1
    issues = CF.quality_issues("tutorial", body, fmt)
    if issues:
        # Non-fatal here: the cron runs enforce_published_quality.py next, which
        # regenerates against this same format. Surface it so the log explains why.
        print("format gate issues (enforcement pass will retry): " + "; ".join(issues[:6]))

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

    # Record the format so the rotation moves on and the enforcement pass gates
    # this post against the right skeleton.
    CF.record("tutorial", fmt, post.get("slug", slug), title)

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
