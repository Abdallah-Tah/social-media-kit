"""Feed API route handlers — browse and act on Google News / HN / Reddit items."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FEED_DIR = ROOT / "content" / "feed"
SCRIPTS_DIR = ROOT / "scripts"


def _ensure_scripts_path() -> None:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))


def _load_latest_feed() -> dict[str, Any]:
    if not FEED_DIR.exists():
        return {"generated_at": None, "count": 0, "items": []}
    snapshots = sorted(FEED_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    # Skip seen.json
    snapshots = [p for p in snapshots if p.name != "seen.json"]
    if not snapshots:
        return {"generated_at": None, "count": 0, "items": []}
    try:
        data = json.loads(snapshots[0].read_text(encoding="utf-8"))
        data["snapshot_file"] = snapshots[0].name
        return data
    except (json.JSONDecodeError, OSError):
        return {"generated_at": None, "count": 0, "items": []}


def _list_snapshots() -> list[dict[str, Any]]:
    if not FEED_DIR.exists():
        return []
    snapshots = sorted(FEED_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in snapshots:
        if p.name == "seen.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": p.name, "generated_at": data.get("generated_at"), "count": data.get("count", 0)})
        except (json.JSONDecodeError, OSError):
            continue
    return out[:10]


def register_routes(
    path: str,
    query: dict[str, list[str]],
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if path == "/api/feed":
        snapshot = (query.get("snapshot") or [None])[0]
        if snapshot:
            p = FEED_DIR / snapshot
            if not p.exists() or not p.name.endswith(".json") or p.name == "seen.json":
                return {"error": "not found"}
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data["snapshot_file"] = p.name
                return {"ok": True, **data}
            except (json.JSONDecodeError, OSError):
                return {"error": "not found"}
        data = _load_latest_feed()
        return {"ok": True, **data, "snapshots": _list_snapshots()}

    if path == "/api/feed/run":
        _ensure_scripts_path()
        try:
            from .feed import build_feed, save_feed
            dry_run = (body or {}).get("dry_run", True)
            limit = int((body or {}).get("limit", 20))
            # Browse mode: include previously-seen stories. The seen-dedupe
            # exists for notifications; a browsing UI should always show the
            # current top stories (a repeat refresh must not go blank).
            include_seen = (body or {}).get("include_seen", True)
            items = build_feed(limit=limit, use_llm=not dry_run, include_seen=include_seen)
            saved_name = None
            # Never overwrite a good snapshot with an empty run.
            if not dry_run and items:
                saved = save_feed(items)
                saved_name = Path(saved).name if saved else None
            return {
                "ok": True,
                "count": len(items),
                "items": [i.to_dict() for i in items],
                "saved": saved_name,
                "dry_run": dry_run,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if path == "/api/feed/generate":
        # Generate a cover image or a YouTube Short script from a feed item.
        item = (body or {}).get("item", {})
        what = (body or {}).get("what", "")
        if not item or what not in ("cover", "short"):
            return {"ok": False, "error": "item and what=cover|short are required"}
        if what == "cover":
            return _generate_feed_cover(item)
        return _generate_feed_short(item)

    if path == "/api/feed/pipeline":
        # Full smkit pipeline: research story → write article → publish to
        # the blog → per-platform social posts that link the blog URL.
        item = (body or {}).get("item", {})
        dry_run = (body or {}).get("dry_run", True)
        profile = (body or {}).get("profile", "default")
        if not item.get("title"):
            return {"ok": False, "error": "item with a title is required"}
        from .feed import FeedItem, post_feed
        feed_item = FeedItem(
            title=item.get("title", ""),
            url=item.get("url", ""),
            source=item.get("source", ""),
            summary=item.get("summary", ""),
        )
        return post_feed([feed_item], profile_name=profile, dry_run=dry_run)

    if path == "/api/feed/youtube":
        # Render the story's Short plan into a video and upload to YouTube.
        # mode "short" keeps #Shorts metadata; "video" strips it for a
        # regular upload. dry_run renders only (no upload).
        item = (body or {}).get("item", {})
        mode = (body or {}).get("mode", "short")
        dry_run = (body or {}).get("dry_run", True)
        force = bool((body or {}).get("force", False))
        if not item.get("title") or mode not in ("short", "video"):
            return {"ok": False, "error": "item with title and mode=short|video are required"}
        return _post_feed_youtube(item, mode, dry_run, force=force)

    if path == "/api/feed/publish":
        # Create social drafts from a feed item and optionally publish immediately.
        item = (body or {}).get("item", {})
        platforms = (body or {}).get("platforms", [])
        dry_run = (body or {}).get("dry_run", True)
        if not item or not platforms:
            return {"ok": False, "error": "item and platforms are required"}
        return _publish_feed_item(item, platforms, dry_run)

    return {"error": "not found"}


def _generate_feed_cover(item: dict[str, Any]) -> dict[str, Any]:
    """Generate a branded cover image for a feed story."""
    _ensure_scripts_path()
    try:
        import datetime as dt
        from image_generator import generate_cover

        title = item.get("title", "Untitled")
        assets_dir = ROOT / "content" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:50].strip("-")
        out_path = assets_dir / f"{dt.date.today().isoformat()}_feed-{slug or 'story'}.png"
        result = generate_cover(
            title,
            out_path=str(out_path),
            branding={"accent_color": "#2563eb"},
        )
        if not result:
            return {"ok": False, "error": "cover generation failed"}
        url = result.get("url") or ""
        rel_path = str(Path(result["path"]).relative_to(ROOT)) if result.get("path") else ""
        return {
            "ok": True,
            "cover_url": url or (f"/api/file?path={rel_path}&inline=1" if rel_path else ""),
            "path": rel_path,
            "provider": result.get("provider", ""),
        }
    except Exception as exc:
        return {"ok": False, "error": f"cover generation failed: {exc}"}


def _resolve_google_news_url(url: str) -> str:
    """Resolve a news.google.com/rss/articles/<id> link to the publisher URL
    via Google's batchexecute endpoint. Returns the input URL on failure."""
    if "news.google.com" not in url or "/articles/" not in url:
        return url
    try:
        import json as _json
        import re
        import urllib.parse
        import urllib.request

        gid = url.split("/articles/")[1].split("?")[0]
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        sg = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sg and ts):
            return url
        payload = [
            "Fbv4je",
            f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
            f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{ts.group(1)},"{sg.group(1)}"]',
        ]
        body = "f.req=" + urllib.parse.quote(_json.dumps([[payload]]))
        req2 = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=body.encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": "Mozilla/5.0"},
        )
        resp = urllib.request.urlopen(req2, timeout=20).read().decode("utf-8", "replace")
        m = re.search(r'https?://(?!news\.google)[^"\\]+', resp)
        return m.group(0) if m else url
    except Exception:
        return url


def _fetch_story_text(url: str, max_chars: int = 6000) -> str:
    """Best-effort fetch of a story's readable text so the Short planner has
    real content, not just a headline. Returns "" on any failure."""
    if not url:
        return ""
    try:
        import re
        import urllib.request

        url = _resolve_google_news_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (smkit feed)"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html_text = resp.read(500_000).decode("utf-8", errors="replace")
        # Strip scripts/styles/tags; collapse whitespace.
        html_text = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html_text)
        # Prefer <article> or <p> content when present.
        paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html_text)
        text = " ".join(paras) if paras else html_text
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = _html_unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if len(text) > 200 else ""
    except Exception:
        return ""


def _html_unescape(text: str) -> str:
    import html as _html
    return _html.unescape(text)


def _story_body(item: dict[str, Any]) -> str:
    """Build the article body for the Short planner: headline + summary +
    fetched page text (so the script is about the actual story)."""
    title = item.get("title", "Untitled")
    summary = item.get("summary", "") or ""
    url = item.get("url", "")
    page_text = _fetch_story_text(url)
    parts = [f"# {title}", summary, page_text, f"Source: {item.get('source', '')}", url]
    return "\n\n".join(p for p in parts if p)


def _generate_feed_short(item: dict[str, Any]) -> dict[str, Any]:
    """Plan a YouTube Short script from a feed story (script only, no render)."""
    _ensure_scripts_path()
    try:
        from .shorts import Article, plan_short, slugify

        title = item.get("title", "Untitled")
        url = item.get("url", "")
        body = _story_body(item)
        article = Article(slug=slugify(title), title=title, body=body, url=url)
        plans_dir = ROOT / "content" / "shorts_plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / f"{article.slug}.json"
        plan = plan_short(article, out_path=plan_path)
        return {
            "ok": True,
            "plan_path": str(plan_path.relative_to(ROOT)),
            "hook": plan.get("hook", ""),
            "voiceover": plan.get("voiceover", ""),
            "captions": plan.get("captions", []),
            "scenes": [
                {"kind": s.get("kind"), "title": s.get("title"), "caption": s.get("caption")}
                for s in plan.get("scenes", [])
            ],
            "publish_metadata": plan.get("publish_metadata", {}),
            "render_hint": f"/usr/bin/python3 -m agent.cli — or render via: agent.shorts.render_short('{plan_path.relative_to(ROOT)}')",
        }
    except Exception as exc:
        return {"ok": False, "error": f"short planning failed: {exc}"}


def _post_feed_youtube(item: dict[str, Any], mode: str, dry_run: bool, force: bool = False) -> dict[str, Any]:
    """Render a story's Short plan to MP4 and (when live) upload to YouTube.

    Reuses an existing plan from content/shorts_plans/ when present so the
    user's edits/preview from "Short Script" carry through. Honors the
    project rule: never claim a live upload without the returned URL.
    """
    _ensure_scripts_path()
    import json as _json
    import subprocess
    try:
        from .shorts import Article, plan_short, render_short, slugify

        title = item.get("title", "Untitled")
        slug = slugify(title)
        plans_dir = ROOT / "content" / "shorts_plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / f"{slug}.json"

        if force or not plan_path.exists():
            # force=True regenerates the script from the story, then re-renders.
            body = _story_body(item)
            plan_short(Article(slug=slug, title=title, body=body, url=item.get("url", "")), out_path=plan_path)

        # Reuse an existing render when it's newer than the plan (so the
        # preview→upload flow doesn't re-render); otherwise render now
        # (Playwright scenes + TTS + ffmpeg — takes a few minutes on the Pi).
        existing = ROOT / "content" / "assets" / "shorts" / slug / f"{slug}.mp4"
        if not force and existing.exists() and existing.stat().st_mtime >= plan_path.stat().st_mtime:
            video = str(existing)
        else:
            meta = render_short(plan_path)
            video = meta.get("video", "")
        if not video or not Path(video).exists():
            return {"ok": False, "error": "render produced no video"}

        # Polish with freecut: word-synced burned subtitles + fades + grade.
        # Best-effort — fall back to the raw render if polishing fails.
        try:
            pol = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "shorts_polish.py"), video]
                + (["--force"] if force else []),
                cwd=str(ROOT), capture_output=True, text=True, timeout=900,
            )
            if pol.returncode == 0:
                for line in pol.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("{"):
                        polished = _json.loads(line).get("video", "")
                        if polished and Path(polished).exists():
                            video = polished
        except Exception:
            pass

        plan = _json.loads(plan_path.read_text(encoding="utf-8"))
        pmeta = plan.get("publish_metadata", {})
        yt_title = str(pmeta.get("title") or title)[:95]
        yt_desc = str(pmeta.get("description") or "")
        tags = [str(t) for t in (pmeta.get("tags") or [])]
        if mode == "video":
            # Regular upload: strip Shorts markers.
            yt_title = yt_title.replace("#Shorts", "").strip()
            yt_desc = yt_desc.replace("#Shorts", "").strip()
            tags = [t for t in tags if t.lower() != "shorts"]

        if dry_run:
            rel = str(Path(video).relative_to(ROOT))
            return {
                "ok": True,
                "dry_run": True,
                "mode": mode,
                "video": rel,
                "video_url": f"/api/file?path={rel}&inline=1",
                "title": yt_title,
                "message": "Rendered — preview below, then click Upload.",
            }

        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "youtube_shorts_publisher.py"),
            "upload",
            "--video", video,
            "--title", yt_title,
            "--description", yt_desc,
            "--privacy", "public",
            "--tags", ",".join(tags) or "BuildWithAbdallah",
            "--category-id", str(pmeta.get("category_id") or "28"),
        ]
        res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=600)
        # Honesty rule: only report success with the returned YouTube URL.
        url = ""
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    url = _json.loads(line).get("url", "")
                except _json.JSONDecodeError:
                    continue
        if res.returncode == 0 and url:
            return {"ok": True, "dry_run": False, "mode": mode, "url": url,
                    "video": str(Path(video).relative_to(ROOT)), "title": yt_title}
        err = (res.stderr or res.stdout)[-400:]
        if "invalid_grant" in err:
            err = "YouTube refresh token expired — re-mint via youtube_shorts_publisher.py auth-url. " + err
        return {"ok": False, "error": f"upload failed: {err}"}
    except Exception as exc:
        return {"ok": False, "error": f"youtube post failed: {exc}"}


def _publish_feed_item(item: dict[str, Any], platforms: list[str], dry_run: bool) -> dict[str, Any]:
    """Create social drafts from a news feed item and optionally publish them."""
    from .social_drafts import generate_social_drafts, save_social_draft
    from .social_publishers import publish

    title = item.get("title", "Untitled")
    url = item.get("url", "")
    summary = item.get("summary", "") or item.get("title", "")
    source = item.get("source", "")

    body_text = (
        f"**{title}**\n\n{summary}\n\n"
        f"Source: {source}\n{url}"
    )

    drafts = generate_social_drafts(
        source_draft_id=f"feed-{url[:20]}",
        blog_url=url,
        title=title,
        body=body_text,
        platforms=platforms,
    )

    results: dict[str, Any] = {}
    for sd in drafts:
        sd.status = "approved"
        save_social_draft(sd)
        if dry_run:
            results[sd.platform] = {"ok": True, "dry_run": True, "draft_id": sd.draft_id}
        else:
            pub = publish(sd.platform, sd.to_dict(), dry_run=False)
            if pub.get("ok"):
                sd.status = "published"
                sd.published_url = pub.get("published_url", "")
            else:
                sd.status = "failed"
                sd.error = pub.get("error", "publish failed")
            save_social_draft(sd)
            results[sd.platform] = {**pub, "draft_id": sd.draft_id}

    return {"ok": True, "results": results, "dry_run": dry_run}
