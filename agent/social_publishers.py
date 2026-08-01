"""Social publishing adapters for approved social drafts.

Each adapter takes a SocialDraft dict and returns:
    {"ok": bool, "published_url": str|None, "error": str|None, "dry_run": bool}

No adapter mutates the social draft file. The caller updates status.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_env_from_secrets() -> None:
    """Best-effort load of secrets.env into os.environ for adapters."""
    secrets = Path("~/.config/social-media-kit/secrets.env").expanduser()
    if secrets.exists():
        with open(secrets, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = value.strip()


def _noop(text: str) -> str:
    return text


def _strip_markdown(text: str) -> str:
    """Remove simple markdown for platforms that don't render it."""
    import re
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", text)
    return text


def _result(ok: bool, published_url: str | None = None, error: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    return {"ok": ok, "published_url": published_url, "error": error, "dry_run": dry_run}


def _publish_linkedin(draft: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return _result(True, published_url="https://linkedin.com/dry-run", dry_run=True)
    try:
        import linkedin_poster
        import linkedin_policy
        # smkit social posts count as dev-news for the daily LinkedIn policy.
        ok, reason = linkedin_policy.allowed("news")
        if not ok:
            return _result(False, error=reason)
        text = _strip_markdown(draft.get("text", ""))
        result = linkedin_poster.post_text(text, post_kind="news")
        if result and result.get("id"):
            urn = result.get("id")
            return _result(True, published_url=f"https://www.linkedin.com/feed/update/{urn}")
        return _result(False, error="LinkedIn post failed — check LINKEDIN_ACCESS_TOKEN (expired?) in Sources → Connections")
    except Exception as exc:
        return _result(False, error=f"LinkedIn error: {exc}")


def _publish_facebook(draft: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return _result(True, published_url="https://facebook.com/dry-run", dry_run=True)
    try:
        from fb_poster import post_text
        text = _strip_markdown(draft.get("text", ""))
        result = post_text(text, link=draft.get("blog_url"))
        if result and result.get("id"):
            post_id = result["id"]
            return _result(True, published_url=f"https://facebook.com/{post_id}")
        return _result(False, error="Facebook post returned no id")
    except Exception as exc:
        return _result(False, error=f"Facebook error: {exc}")


def _publish_threads(draft: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return _result(True, published_url="https://threads.net/dry-run", dry_run=True)
    try:
        from threads_poster import post
        text = draft.get("text", "")[:500]
        result = post(text)
        if result and result.get("id"):
            return _result(True, published_url=f"https://threads.net/t/{result['id']}")
        return _result(False, error="Threads post returned no id")
    except Exception as exc:
        return _result(False, error=f"Threads error: {exc}")


def _fit_tweet(text: str, limit: int = 280) -> str:
    """Trim a post to X's limit without destroying the trailing link.

    A blind ``text[:280]`` cut the URL mid-string whenever the copy ran long,
    publishing a dead link. The link is the point of the post, so the prose
    gives way instead — trimmed at a word boundary.
    """
    import re
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    urls = re.findall(r"https?://\S+", text)
    if not urls:
        return text[:limit].rsplit(" ", 1)[0]
    tail = urls[-1]
    body = text[: text.rindex(tail)].rstrip()
    budget = limit - len(tail) - 2  # room for the separating blank line
    if budget <= 0:
        return tail[:limit]
    trimmed = body[:budget].rsplit(" ", 1)[0].rstrip(" .,;:—-")
    return f"{trimmed}\n\n{tail}"


def _publish_x(draft: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return _result(True, published_url="https://x.com/dry-run", dry_run=True)
    try:
        from x_poster import post_tweet
        text = _fit_tweet(draft.get("text", ""))
        result = post_tweet(text)
        if result and result.get("id"):
            return _result(True, published_url=f"https://x.com/i/web/status/{result['id']}")
        return _result(False, error="X post returned no id")
    except Exception as exc:
        return _result(False, error=f"X error: {exc}")


def _publish_reddit(draft: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return _result(True, published_url="https://reddit.com/dry-run", dry_run=True)
    try:
        from reddit_poster import post as reddit_post
        title = draft.get("title", "")[:300]
        text = _strip_markdown(draft.get("text", ""))
        result = reddit_post(title=title, text=text, url=draft.get("blog_url"))
        if result:
            data = result.get("json", {}).get("data", {})
            link = data.get("url") or data.get("permalink", "")
            if link:
                return _result(True, published_url=link if link.startswith("http") else f"https://reddit.com{link}")
        return _result(False, error="Reddit post returned no data")
    except Exception as exc:
        return _result(False, error=f"Reddit error: {exc}")


def _publish_newsletter(draft: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """Newsletter is treated as a local draft file/email-ready export.

    We do not send email here. Instead we write a newsletter file and
    return its path as published_url for the user to review/send manually.
    """
    try:
        from agent.drafts import ROOT as DRAFT_ROOT
        newsletter_dir = DRAFT_ROOT / "content" / "newsletter_drafts"
        newsletter_dir.mkdir(parents=True, exist_ok=True)
        path = newsletter_dir / f"{draft.get('draft_id')}.md"
        body = f"# {draft.get('title', 'Newsletter')}\n\n{draft.get('text', '')}\n\nRead online: {draft.get('blog_url', '')}\n"
        path.write_text(body, encoding="utf-8")
        if dry_run:
            return _result(True, published_url=f"file://{path}", dry_run=True)
        return _result(True, published_url=f"file://{path}")
    except Exception as exc:
        return _result(False, error=f"Newsletter error: {exc}")


def _publish_youtube(draft: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """YouTube live publishing stays disabled."""
    return _result(False, error="YouTube live publishing is disabled in this phase")


_PLATFORM_HANDLERS: dict[str, Callable[[dict[str, Any], bool], dict[str, Any]]] = {
    "linkedin": _publish_linkedin,
    "facebook": _publish_facebook,
    "threads": _publish_threads,
    "x": _publish_x,
    "reddit": _publish_reddit,
    "newsletter": _publish_newsletter,
    "youtube": _publish_youtube,
}

SUPPORTED_PLATFORMS = set(_PLATFORM_HANDLERS.keys())


def publish(platform: str, draft: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """Publish a single social draft to the given platform."""
    _load_env_from_secrets()
    platform = platform.lower().strip()
    handler = _PLATFORM_HANDLERS.get(platform)
    if handler is None:
        return _result(False, error=f"unsupported platform: {platform}")
    result = handler(draft, dry_run=dry_run)
    # Telegram heads-up on every LIVE post (never on dry runs; best-effort).
    if result.get("ok") and not result.get("dry_run"):
        try:
            from .notify import notify_publish
            title = (draft.get("title") or draft.get("text") or "")[:80]
            url = result.get("published_url") or ""
            notify_publish(f"✅ Posted to {platform}: {title}\n{url}".strip())
        except Exception:
            pass
    return result
