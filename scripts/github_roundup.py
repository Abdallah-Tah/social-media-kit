#!/usr/bin/env python3
"""Weekly "exploding on GitHub" roundup — blog article + cover + social.

A ranked list of the repos that gained the most stars in the last seven days.
Every number comes from GitHub's own trending page (`?since=weekly`), which
publishes the weekly star delta directly — nothing here is estimated, inferred,
or written from model memory. If a figure can't be scraped, the repo is dropped
rather than guessed (taco rule #0001).

  /usr/bin/python3 scripts/github_roundup.py --dry-run        # rehearse
  /usr/bin/python3 scripts/github_roundup.py --topic ai       # AI/agents only
  /usr/bin/python3 scripts/github_roundup.py --publish        # LIVE
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
import sys

import requests

KIT = os.path.expanduser("~/social-media-kit")
sys.path.insert(0, KIT)
from agent.config import load_env

load_env()
sys.path.insert(0, os.path.join(KIT, "scripts"))

import blog_publisher as BP
import content_formats as CF
import image_generator as IG

SITE = "https://buildwithabdallah.com"
DRAFTS = os.path.join(KIT, "content", "drafts")
LEDGER = os.path.join(KIT, "content", "github_roundups.json")
TRENDING = "https://github.com/trending"
UA = {"User-Agent": "Mozilla/5.0 (compatible; BuildWithAbdallah/1.0)"}

# Topic filters. "all" keeps whatever is trending; the others match against the
# repo name + description so the roundup has a coherent angle.
TOPIC_KEYWORDS = {
    "ai": (
        "ai", "llm", "gpt", "claude", "gemini", "agent", "agents", "rag",
        "prompt", "model", "inference", "embedding", "openai", "anthropic",
        "diffusion", "transformer", "mcp", "copilot", "coding agent", "ml",
        "neural", "chatbot", "fine-tune", "vector",
    ),
    "devtools": (
        "cli", "terminal", "editor", "ide", "debug", "lint", "build", "compiler",
        "framework", "sdk", "devops", "docker", "kubernetes", "ci", "test",
        "database", "api", "server", "runtime", "package manager",
    ),
}


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment))).strip()


def scrape_trending(spoken_language: str = "en") -> list[dict]:
    """Parse GitHub's weekly trending page into structured rows.

    The weekly delta is the whole point — it's the one number GitHub publishes
    that we cannot compute ourselves without a long star-history backfill.
    """
    params = {"since": "weekly"}
    if spoken_language:
        params["spoken_language_code"] = spoken_language
    resp = requests.get(TRENDING, params=params, headers=UA, timeout=30)
    resp.raise_for_status()

    rows = re.findall(r'<article class="Box-row">(.*?)</article>', resp.text, re.S)
    items = []
    for row in rows:
        heading = re.search(r"<h2[^>]*>(.*?)</h2>", row, re.S)
        delta = re.search(r"([\d,]+)\s*stars this week", row)
        if not heading or not delta:
            continue  # no verifiable weekly number → drop it, never estimate
        full_name = _text(heading.group(1)).replace(" / ", "/")
        if "/" not in full_name:
            continue
        desc = re.search(r'<p class="col-9[^"]*">(.*?)</p>', row, re.S)
        lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', row)
        items.append({
            "full_name": full_name,
            "name": full_name.split("/", 1)[1],
            "url": f"https://github.com/{full_name}",
            "description": _text(desc.group(1)) if desc else "",
            "language": lang.group(1).strip() if lang else "",
            "weekly_stars": int(delta.group(1).replace(",", "")),
        })
    return items


def filter_topic(items: list[dict], topic: str) -> list[dict]:
    keywords = TOPIC_KEYWORDS.get(topic)
    if not keywords:
        return items
    out = []
    for it in items:
        blob = f"{it['full_name']} {it['description']}".lower()
        if any(re.search(rf"\b{re.escape(k)}\b", blob) for k in keywords):
            out.append(it)
    return out


MIN_ITEMS = 5


def collect(topic: str = "ai", limit: int = 10) -> tuple[list[dict], str]:
    """Top repos by weekly star gain. Returns (items, effective_topic).

    If the requested filter is thin this week, fall back to the unfiltered list
    and say so via the returned topic — never top up an "AI" list with unrelated
    repos, because the headline would then describe contents that aren't there.
    """
    items = scrape_trending()
    picked = filter_topic(items, topic)
    effective = topic
    if len(picked) < MIN_ITEMS and topic != "all":
        picked, effective = items, "all"
    picked.sort(key=lambda i: i["weekly_stars"], reverse=True)
    return picked[:limit], effective


# ── Ledger (so a repo isn't the headline two weeks running) ─────────────────

def _load_ledger() -> dict:
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_roundup(slug: str, items: list[dict]) -> None:
    data = _load_ledger()
    runs = data.get("runs") or []
    runs.append({
        "slug": slug,
        "date": datetime.date.today().isoformat(),
        "repos": [i["full_name"] for i in items],
    })
    data["runs"] = runs[-30:]
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, LEDGER)


def previously_featured(weeks: int = 2) -> set[str]:
    runs = (_load_ledger().get("runs") or [])[-weeks:]
    return {name for run in runs for name in run.get("repos", [])}


# ── Article ────────────────────────────────────────────────────────────────

def build_article(items: list[dict], topic: str) -> tuple[str, str, str]:
    """Return (title, slug, markdown body). All figures come from the scrape."""
    total = sum(i["weekly_stars"] for i in items)
    week = datetime.date.today().isoformat()
    label = {"ai": "AI", "devtools": "Developer Tool", "all": "Open-Source"}.get(topic, "Open-Source")
    title = f"{len(items)} {label} Projects That Exploded on GitHub This Week"
    slug = f"github-{topic}-roundup-{week}"

    lines = [
        f"# {title}",
        "",
        f"Together, these {len(items)} repositories gained **{total:,} GitHub stars** in the "
        f"last seven days. Star counts are GitHub's own weekly deltas, read from the "
        f"[trending page]({TRENDING}?since=weekly) on {week}.",
        "",
        "## The List",
        "",
    ]
    for rank, it in enumerate(items, 1):
        desc = it["description"] or "No description provided by the repository."
        lang = f" · {it['language']}" if it["language"] else ""
        lines += [
            f"### {rank}. {it['name']} (+{it['weekly_stars']:,} stars){lang}",
            "",
            desc,
            "",
            f"<{it['url']}>",
            "",
        ]

    top = items[0]
    lines += [
        "## What I'd Actually Try",
        "",
        f"{top['name']} is the week's biggest mover at +{top['weekly_stars']:,} stars. "
        "A one-week star spike measures attention, not quality — it usually means a launch "
        "post landed somewhere with reach. The useful signal is what a repo looks like a "
        "month later: open issues getting closed, a real release cadence, and docs that "
        "survive contact with a second user.",
        "",
        "Treat this list as a reading queue, not a dependency list. Starring is free; "
        "adopting is not.",
        "",
        "## Sources",
        "",
        f"- [GitHub Trending — weekly]({TRENDING}?since=weekly)",
    ]
    lines += [f"- [{i['full_name']}]({i['url']})" for i in items]
    lines += ["", "## What I'll Be Watching", "",
              "Which of these still have momentum in four weeks. Weekly star spikes decay "
              "fast; sustained contributor growth is the number that actually predicts "
              "whether a project is worth building on."]
    return title, slug, "\n".join(lines)


def build_social(items: list[dict], url: str, topic: str) -> str:
    """The numbered-list social post, in the shape that performs for this format."""
    total = sum(i["weekly_stars"] for i in items)
    label = {"ai": "AI Open-Source", "devtools": "Developer Tool", "all": "Open-Source"}.get(
        topic, "Open-Source")
    out = [
        f"{len(items)} {label} Projects That Exploded on GitHub This Week",
        "",
        f"Together, these {len(items)} repositories gained {total:,} GitHub stars in just one week.",
        "",
    ]
    for rank, it in enumerate(items, 1):
        desc = it["description"] or ""
        if len(desc) > 160:
            desc = desc[:157].rsplit(" ", 1)[0] + "..."
        out += [f"{rank}. {it['name']} (+{it['weekly_stars']:,} stars)", desc, it["url"], ""]
    out += ["Which repo are you trying first, and which one did I miss?", "",
            f"Full list: {url}", "", "#OpenSource #GitHub #DeveloperTools"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="ai", choices=["ai", "devtools", "all"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="Publish live to the blog + Facebook + LinkedIn")
    args = ap.parse_args()

    items, topic = collect(args.topic, args.limit)
    if len(items) < MIN_ITEMS:
        print(f"roundup: only {len(items)} repos with a verifiable weekly delta — not publishing")
        return 1
    if topic != args.topic:
        print(f"note: too few '{args.topic}' repos trending this week — publishing as '{topic}'")

    repeats = previously_featured() & {i["full_name"] for i in items}
    if repeats:
        print(f"note: featured in a recent roundup and appearing again: {', '.join(sorted(repeats))}")

    title, slug, body = build_article(items, topic)
    total = sum(i["weekly_stars"] for i in items)
    print(f"roundup: {title}\n  slug: {slug}\n  repos: {len(items)}  total weekly stars: {total:,}")
    for it in items:
        print(f"    +{it['weekly_stars']:>7,}  {it['full_name']}")

    os.makedirs(DRAFTS, exist_ok=True)
    draft_path = os.path.join(DRAFTS, f"{datetime.date.today().isoformat()}_{slug}.md")
    with open(draft_path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"Saved draft to {draft_path}")

    url = f"{SITE}/tutorials/{slug}"
    if args.dry_run or not args.publish:
        print("=== DRY RUN — no cover, no site publish, no social ===")
        print("\n--- social post ---\n" + build_social(items, url, topic))
        return 0

    cover = IG.generate_cover(
        title,
        branding={
            "accent_color": "#7c3aed",
            "subtitle": f"{total:,} stars in one week",
            "footer": "Build With Abdallah | open-source roundup",
        },
    )
    cover_url = (cover or {}).get("url") or (cover or {}).get("path") or ""

    post = BP.publish_article(
        title=title, slug=slug, content=body,
        excerpt=f"The {len(items)} repositories that gained the most GitHub stars this week — "
                f"{total:,} between them.",
        publish=True, cover_image_url=cover_url,
    )
    if not post:
        print("roundup publish failed")
        return 1
    live_url = f"{SITE}/tutorials/{post.get('slug', slug)}"
    print(f"Published: Post ID {post.get('id')}, Slug: {post.get('slug')}")
    record_roundup(post.get("slug", slug), items)

    text = build_social(items, live_url, topic)
    local = (cover or {}).get("path")
    try:
        import fb_poster
        if local and os.path.exists(local):
            fb_poster.post_photo(local, caption=text)
        else:
            fb_poster.post_text(text, link=live_url)
        print("Facebook: attempted")
    except Exception as exc:
        print(f"facebook post failed (non-fatal): {exc}")

    try:
        import linkedin_policy as LP
        import linkedin_org_poster as LI
        ok, reason = LP.allowed("roundup")
        if not ok:
            print(reason)
        else:
            token, _ = LI.fetch_org_token()
            if not token:
                print("⚠️ LinkedIn skipped: no token")
            else:
                res = LI.post_org(text, token=token, post_kind="roundup")
                print(f"LinkedIn: {'ok' if res else 'failed'}")
    except Exception as exc:
        print(f"linkedin post failed (non-fatal): {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
