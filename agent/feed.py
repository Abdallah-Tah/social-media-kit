"""Personalized AI news feed engine for smkit.

Google Discover-style feed that collects articles from multiple sources,
ranks them by user interests + freshness + authority + novelty, summarizes
them, dedupes stories, and optionally notifies or drafts social content.

Public entry points:
    build_feed(...) -> list[FeedItem]
    print_feed(items)
    save_feed(items)
    notify_feed(items, dry_run=True)
    post_feed(items, dry_run=True)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

__all__ = [
    "FEED_DIR",
    "FeedItem",
    "build_feed",
    "canonical_url",
    "doctor_feed",
    "is_seen",
    "load_profile_with_interests",
    "mark_seen",
    "notify_feed",
    "post_feed",
    "print_feed",
    "save_feed",
    "source_authority",
]

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.config import load_env

load_env()

if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

FEED_DIR = KIT / "content" / "feed"
SEEN_PATH = FEED_DIR / "seen.json"
SEEN_DEFAULT_TTL_DAYS = 30

DEFAULT_SOURCES = ["google_news", "hackernews", "reddit"]
DEFAULT_LIMIT = 10
NOTIFY_TOP_N = 3


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass
class FeedItem:
    title: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""
    summary: str = ""
    score: float = 0.0
    matched_interests: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            "score": round(self.score, 2),
            "matched_interests": self.matched_interests,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeedItem":
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            source=data.get("source", ""),
            published_at=data.get("published_at", ""),
            summary=data.get("summary", ""),
            score=float(data.get("score", 0) or 0),
            matched_interests=list(data.get("matched_interests", [])),
            reason=data.get("reason", ""),
        )


# ── Configuration helpers ─────────────────────────────────────────────────────

def load_profile_with_interests(name: str = "default") -> dict[str, Any]:
    from agent.config import load_profile

    profile = load_profile(name)
    profile.setdefault("interests", [])
    # If profile doesn't define interests, fall back to global feed config.
    if not profile.get("interests"):
        feed_cfg = _load_feed_config()
        profile["interests"] = feed_cfg.get("interests", _default_interests())
    return profile


def _default_interests() -> list[str]:
    return [
        "artificial intelligence",
        "software engineering",
        "Laravel",
        "Python",
        "startups",
    ]


def _load_feed_config() -> dict[str, Any]:
    """Load optional config/feed.yaml or the feed block from agent.yaml."""
    from agent.config import _read_yaml, CONFIG_DIR

    feed_yaml = CONFIG_DIR / "feed.yaml"
    if feed_yaml.exists():
        return _read_yaml(feed_yaml)
    settings = _read_yaml(CONFIG_DIR / "agent.yaml")
    return settings.get("feed", {}) if isinstance(settings, dict) else {}


def get_feed_sources(profile: dict[str, Any] | None = None) -> list[str]:
    cfg = _load_feed_config()
    sources = cfg.get("sources", DEFAULT_SOURCES)
    if profile and profile.get("feed", {}).get("sources"):
        sources = profile["feed"]["sources"]
    return list(sources)


def get_notification_channel(profile: dict[str, Any] | None = None) -> str | None:
    cfg = _load_feed_config()
    channel = cfg.get("notification_channel")
    if profile and profile.get("feed", {}).get("notification_channel"):
        channel = profile["feed"]["notification_channel"]
    return channel


# ── Seen URL store (dedupe across runs) ───────────────────────────────────────

def load_seen() -> dict[str, Any]:
    if not SEEN_PATH.exists():
        return {"urls": {}, "ttl_days": SEEN_DEFAULT_TTL_DAYS}
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"urls": {}, "ttl_days": SEEN_DEFAULT_TTL_DAYS}
    data.setdefault("urls", {})
    data.setdefault("ttl_days", SEEN_DEFAULT_TTL_DAYS)
    return data


def save_seen(seen: dict[str, Any]) -> None:
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, indent=2), encoding="utf-8")


def is_seen(url: str, seen: dict[str, Any] | None = None) -> bool:
    if seen is None:
        seen = load_seen()
    canon = canonical_url(url)
    if canon in seen["urls"]:
        return True
    # Also dedupe by netloc + last path segment if redirect/tracking params differ.
    parsed = urlparse(canon)
    fuzzy = f"{parsed.netloc}{parsed.path}"
    for stored in seen["urls"]:
        sp = urlparse(stored)
        if f"{sp.netloc}{sp.path}" == fuzzy:
            return True
    return False


def mark_seen(urls: list[str], seen: dict[str, Any] | None = None) -> None:
    if seen is None:
        seen = load_seen()
    now = _now().isoformat()
    ttl_days = int(seen.get("ttl_days", SEEN_DEFAULT_TTL_DAYS))
    cutoff = (_now() - dt.timedelta(days=ttl_days)).isoformat()
    # Evict old entries.
    seen["urls"] = {
        u: ts for u, ts in seen["urls"].items() if ts >= cutoff
    }
    for url in urls:
        seen["urls"][canonical_url(url)] = now
    save_seen(seen)


# ── URL normalization ─────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    """Strip tracking params and normalize a URL for dedupe keys."""
    url = url.strip()
    parsed = urlparse(url)
    q = parsed.query
    if q:
        stripped = {
            k: v
            for k, v in urllib.parse.parse_qsl(q)
            if k.lower() not in _TRACKING_PARAMS
        }
        q = urlencode(stripped)
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.params, q, "")
    )


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ttclid", "li_fat_id", "mc_cid", "mc_eid",
    "ref", "source", "si", "feature", "ref_src",
}


# ── Fetching pipeline ───────────────────────────────────────────────────────

def build_feed(
    topic: str | None = None,
    profile_name: str = "default",
    limit: int = DEFAULT_LIMIT,
    excluded_sources: list[str] | None = None,
    use_llm: bool = True,
    include_seen: bool = False,
) -> list[FeedItem]:
    """Fetch, dedupe, rank, and summarize a personalized feed.

    Args:
        topic: Optional topic override. If given, sources are queried with it.
        profile_name: Brand profile to pull interests from.
        limit: How many top items to return.
        excluded_sources: Source names to skip this run.
        use_llm: Whether to use the LLM provider for summaries/explanations.
        include_seen: If True, include previously seen URLs (demo/analysis mode).
    """
    profile = load_profile_with_interests(profile_name)
    interests = [i.lower() for i in profile.get("interests", [])]
    sources = get_feed_sources(profile)
    if excluded_sources:
        sources = [s for s in sources if s not in excluded_sources]

    raw: list[FeedItem] = []
    from scripts.feed_sources import fetch_all

    raw = fetch_all(sources, topic=topic)

    seen = load_seen()
    if not include_seen:
        raw = [item for item in raw if not is_seen(item.url, seen)]

    from scripts.feed_ranker import dedupe_items, rank_items

    ranked = rank_items(dedupe_items(raw), interests, topic=topic)

    if use_llm:
        ranked = _summarize_top(ranked, profile, topic=topic)

    # Mark top N as seen so reruns don't surface the same stories.
    # When include_seen is True, do not update the seen store.
    if not include_seen:
        mark_seen([item.url for item in ranked[:limit]], seen)
    return ranked[:limit]


def _summarize_top(items: list[FeedItem], profile: dict[str, Any], topic: str | None = None) -> list[FeedItem]:
    """Use the configured LLM to write concise summaries + reason strings.

    Only the top items are summarized to keep API costs tiny.
    """
    from agent.config import AgentConfig

    config = AgentConfig.load()
    if not config.api_key and config.provider != "ollama":
        # Ollama local needs no key; cloud models need a key.
        return items

    for item in items[: min(5, len(items))]:
        if not item.summary:
            try:
                item.summary = _llm_summary(item, profile, topic=topic, config=config)
                item.reason = _llm_reason(item, topic=topic, config=config)
            except Exception:
                pass
    return items


def _llm_summary(item: FeedItem, profile: dict[str, Any], topic: str | None, config: Any) -> str:
    prompt = (
        f"Summarize this article in 1-2 sentences for a {profile.get('tone', 'practical developer audience')}. "
        f"Be specific, not hypey.\n\nTitle: {item.title}\nSource: {item.source}\nURL: {item.url}"
    )
    return _llm_chat(prompt, config)


def _llm_reason(item: FeedItem, topic: str | None, config: Any) -> str:
    interest_list = ", ".join(item.matched_interests) or "general audience"
    prompt = (
        f"In one short sentence, explain why this article matters to someone interested in {interest_list}. "
        f"Title: {item.title}\nSummary: {item.summary}"
    )
    return _llm_chat(prompt, config)


def _llm_chat(prompt: str, config: Any) -> str:
    """Minimal chat call through the configured provider, via the shared client.

    Instrumented through agent.llm_ops so the call lands in the usage ledger
    (Phase 0.5). Payload is byte-identical to the previous hand-rolled request:
    same model, 256 max_tokens, temperature 0.4, 60s timeout, no json mode.

    NOTE: the previous implementation referenced `requests` without importing
    it, so every call raised NameError and the caller's bare `except Exception:
    pass` swallowed it — feed items silently had no LLM summary or reason. This
    routing fixes that as a side effect.
    """
    from . import llm_ops

    result = llm_ops.chat(
        [{"role": "user", "content": prompt}],
        model=config.model,
        temperature=0.4,
        max_tokens=256,
        timeout=60,
        base_url=(config.base_url or "https://api.openai.com/v1"),
        api_key=(config.api_key or ""),
        job_id="feed_llm",
    )
    result.raise_for_status()
    return result.text


# ── Output / persistence ────────────────────────────────────────────────────

def save_feed(items: list[FeedItem], path: Path | None = None) -> Path:
    if path is None:
        today = _now().strftime("%Y-%m-%d")
        path = FEED_DIR / f"{today}.json"
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _now().isoformat(),
        "count": len(items),
        "items": [item.to_dict() for item in items],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def print_feed(items: list[FeedItem]) -> None:
    if not items:
        print("No new feed items found.")
        return
    print(f"\n📰 smkit feed — {len(items)} items\n")
    for idx, item in enumerate(items, 1):
        print(f"{idx}. {item.title}")
        print(f"   Source: {item.source}  |  Score: {item.score:.2f}")
        print(f"   URL: {item.url}")
        if item.matched_interests:
            print(f"   Interests: {', '.join(item.matched_interests)}")
        if item.summary:
            print(f"   Summary: {item.summary}")
        if item.reason:
            print(f"   Why it matters: {item.reason}")
        print()


# ── Notification ───────────────────────────────────────────────────────────

def notify_feed(items: list[FeedItem], channel: str | None = None, profile_name: str = "default", dry_run: bool = True) -> dict[str, Any]:
    profile = load_profile_with_interests(profile_name)
    channel = channel or get_notification_channel(profile) or "telegram"
    top = items[:NOTIFY_TOP_N]
    if not top:
        return {"ok": True, "channel": channel, "sent": 0, "message": "No items to notify."}
    lines = ["📰 Your personalized smkit feed"]
    for idx, item in enumerate(top, 1):
        lines.append(f"\n{idx}. {item.title}\n   {item.url}\n   Score: {item.score:.2f}")
        if item.summary:
            lines.append(f"   {item.summary}")
    message = "\n".join(lines)
    if dry_run:
        return {"ok": True, "channel": channel, "sent": len(top), "dry_run": True, "message": message}

    if channel.lower() in ("telegram", "tg"):
        from scripts.telegram_poster import post_message

        result = post_message(message)
        return {"ok": bool(result), "channel": channel, "sent": len(top), "message": message[:200]}
    return {"ok": False, "channel": channel, "sent": 0, "error": f"Unsupported channel: {channel}"}


# ── Social post draft ────────────────────────────────────────────────────────

def post_feed(items: list[FeedItem], profile_name: str = "default", dry_run: bool = True) -> dict[str, Any]:
    """Draft a social post from the top feed item using the existing smkit pipeline."""
    if not items:
        return {"ok": True, "dry_run": dry_run, "message": "No feed items to post."}
    top = items[0]
    # Run the existing `smkit run` flow for the top story topic.
    import subprocess

    cmd = [sys.executable, "-m", "agent.cli", "run", "--topic", top.title, "--profile", profile_name]
    if dry_run:
        cmd.append("--dry-run")
    else:
        cmd.append("--yes")
    try:
        result = subprocess.run(cmd, cwd=KIT, capture_output=True, text=True, timeout=300)
        return {
            "ok": result.returncode == 0,
            "dry_run": dry_run,
            "topic": top.title,
            "url": top.url,
            "stdout": result.stdout[-800:],
            "stderr": result.stderr[-400:],
        }
    except Exception as exc:
        return {"ok": False, "dry_run": dry_run, "error": str(exc)}


# ── Doctor checks ───────────────────────────────────────────────────────────

def doctor_feed() -> dict[str, Any]:
    from scripts.feed_sources import source_status

    return {
        "feed_dir": FEED_DIR.exists(),
        "seen_store": SEEN_PATH.exists(),
        "sources": source_status(),
    }
