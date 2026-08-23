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
import social_formatters as SF

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


X_LABELS = {"ai": "AI", "devtools": "developer tool", "all": "open-source"}

# A thread is billed per post. Capping it keeps a freak 30-repo week from
# turning one roundup into a thirty-post charge.
MAX_THREAD_POSTS = int(os.environ.get("ROUNDUP_X_MAX_THREAD_POSTS", "8"))


def build_content(items: list[dict], url: str, topic: str, use_llm: bool = True):
    """Platform-neutral content — ranks, totals and prose, before rendering."""
    return SF.build_roundup_content(
        items, article_url=url, topic=topic,
        label=X_LABELS.get(topic, "open-source"), use_llm=use_llm,
    )


def build_social(items: list[dict], url: str, topic: str, use_llm: bool = True) -> str:
    """The LinkedIn/Facebook post: hook, ranked entries, observations, CTA."""
    return SF.LinkedInRoundupFormatter().render(build_content(items, url, topic, use_llm))


def build_x_social(items: list[dict], url: str, topic: str, use_llm: bool = True) -> str:
    """The single-post X form, for when a thread isn't wanted.

    Kept because one post is one charge; `build_x_thread` is the richer form.
    """
    content = build_content(items, url, topic, use_llm)
    return SF.XRoundupFormatter().render_single(content)


def build_x_thread(items: list[dict], url: str, topic: str, use_llm: bool = True) -> list[str]:
    """The X thread, already validated against the weighted character limit."""
    content = build_content(items, url, topic, use_llm)
    return SF.XRoundupFormatter().render_thread(content)


def x_already_posted(slug: str) -> bool:
    """Has this roundup already gone to X? Every X post is billed."""
    for run in (_load_ledger().get("runs") or []):
        if run.get("slug") == slug and run.get("x_posted"):
            return True
    return False


def mark_x_posted(slug: str, tweet_url: str) -> None:
    data = _load_ledger()
    runs = data.get("runs") or []
    for run in reversed(runs):
        if run.get("slug") == slug:
            run["x_posted"] = tweet_url or True
            break
    data["runs"] = runs
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, LEDGER)


def publish_to_x(items: list[dict], live_url: str, topic: str, slug: str,
                 thread: bool = False) -> None:
    """Post the roundup to X exactly once.

    X is the only billed channel, so it carries this weekly roundup and nothing
    else — the news lane deliberately does not touch it. The ledger guard means
    re-running the script for the same slug will not pay twice.

    A thread is billed PER POST, so one costs as much as a week of single posts.
    Threading is therefore opt-in (`--thread`), not the default, and is capped at
    MAX_THREAD_POSTS so a freak week cannot quietly multiply the bill.
    """
    if x_already_posted(slug):
        print(f"X: already posted for {slug} — skipping (billed channel, once only)")
        return
    try:
        import x_poster

        posts = []
        if thread:
            try:
                posts = build_x_thread(items, live_url, topic)
            except SF.XPostTooLong as exc:
                print(f"X: thread rejected by the length check ({exc}); using one post")
            if len(posts) > MAX_THREAD_POSTS:
                print(f"X: thread would be {len(posts)} billed posts "
                      f"(cap {MAX_THREAD_POSTS}); using one post")
                posts = []

        if len(posts) > 1:
            result = x_poster.post_thread(posts)
            if result and result.get("ids"):
                tweet_url = f"https://x.com/i/web/status/{result['ids'][0]}"
                # Recorded even on a partial thread: the first post is public,
                # so a re-run must not pay for it a second time.
                mark_x_posted(slug, tweet_url)
                print(f"X: posted {result['posted']}/{len(posts)} → {tweet_url}")
                if result.get("error"):
                    print(f"X: thread incomplete — {result['error']}")
            else:
                print(f"X: failed — {result}")
            return

        text = posts[0] if posts else build_x_social(items, live_url, topic)
        result = x_poster.post_tweet(text)
        if result and result.get("id"):
            tweet_url = f"https://x.com/i/web/status/{result['id']}"
            mark_x_posted(slug, tweet_url)
            print(f"X: posted {tweet_url}")
        else:
            print(f"X: failed — {result}")
    except Exception as exc:
        print(f"x post failed (non-fatal): {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="ai", choices=["ai", "devtools", "all"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="Publish live to the blog + Facebook + LinkedIn")
    ap.add_argument("--no-llm", action="store_true",
                    help="Render deterministically, without the prose model")
    ap.add_argument("--thread", action="store_true",
                    help="Post X as a thread (billed PER POST; default is one post)")
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
        content = build_content(items, url, topic, use_llm=not args.no_llm)

        print("\n--- LinkedIn preview " + "-" * 40)
        print(SF.LinkedInRoundupFormatter().render(content))

        # Preview exactly what a live run would post, so the rehearsal shows the
        # real bill: one post unless --thread was asked for.
        xf = SF.XRoundupFormatter()
        try:
            posts = xf.render_thread(content) if args.thread else [xf.render_single(content)]
        except SF.XPostTooLong as exc:
            print(f"\n--- X preview: cannot fit ({exc}) ---")
            return 1
        if args.thread and len(posts) > MAX_THREAD_POSTS:
            print(f"\n⚠️  thread would be {len(posts)} posts, over the "
                  f"{MAX_THREAD_POSTS} cap — a live run would post one instead.")
            posts = [xf.render_single(content)]

        charge = "1 charge" if len(posts) == 1 else f"{len(posts)} charges"
        print(f"\n--- X preview ({len(posts)} post(s), {charge}) " + "-" * 20)
        for i, total, width, limit in xf.char_counts(posts):
            print(f"\nPost {i}/{total}   {width} / {limit}")
            print(posts[i - 1])
        if not args.thread:
            print("\n(single post is the default; --thread renders the full "
                  "thread and is billed per post)")
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

    content = build_content(items, live_url, topic, use_llm=not args.no_llm)
    text = SF.LinkedInRoundupFormatter().render(content)
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
                # article_url pins the link card to buildwithabdallah.com rather
                # than the first GitHub repo in the body.
                res = LI.post_org(text, token=token, post_kind="roundup",
                                  title=title, article_url=live_url)
                print(f"LinkedIn: {'ok' if res else 'failed'}")
    except Exception as exc:
        print(f"linkedin post failed (non-fatal): {exc}")

    publish_to_x(items, live_url, topic, post.get("slug", slug), thread=args.thread)
    return 0


if __name__ == "__main__":
    sys.exit(main())
