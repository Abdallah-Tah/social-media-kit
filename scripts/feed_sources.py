"""Multi-source feed fetcher for smkit feed.

Supported sources:
    google_news   – Google News RSS (topic and default tech/AI feeds)
    hackernews    – Hacker News front page + best stories via API
    reddit        – r/technology, r/programming, r/artificial via .json
    rss           – User-supplied RSS feed URLs
    youtube_rss   – YouTube channel RSS feeds

Each source returns a list of FeedItem objects.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.feed import FeedItem, canonical_url

# ── Default feed endpoints ────────────────────────────────────────────────────

GOOGLE_NEWS_TOPICS: dict[str, str] = {
    "ai": "https://news.google.com/rss/search?q=artificial+intelligence+LLM&hl=en-US&gl=US&ceid=US:en",
    "ai_agents": "https://news.google.com/rss/search?q=AI+agents+autonomous+coding&hl=en-US&gl=US&ceid=US:en",
    "software_engineering": "https://news.google.com/rss/search?q=software+engineering+development&hl=en-US&gl=US&ceid=US:en",
    "open_source": "https://news.google.com/rss/search?q=open+source+software+release&hl=en-US&gl=US&ceid=US:en",
    "languages": "https://news.google.com/rss/search?q=programming+language+Python+TypeScript+Rust&hl=en-US&gl=US&ceid=US:en",
    "frameworks": "https://news.google.com/rss/search?q=web+framework+Laravel+React+developer&hl=en-US&gl=US&ceid=US:en",
    "dev_tools": "https://news.google.com/rss/search?q=developer+tools+GitHub+API&hl=en-US&gl=US&ceid=US:en",
}

HACKERNEWS_URLS = [
    "https://hacker-news.firebaseio.com/v0/topstories.json",
    "https://hacker-news.firebaseio.com/v0/beststories.json",
]

REDDIT_SUBREDDITS = [
    "programming",
    "MachineLearning",
    "LocalLLaMA",
    "opensource",
    "ExperiencedDevs",
    "webdev",
    "artificial",
]

YOUTUBE_CHANNEL_HANDLES: list[str] = []

DEFAULT_RSS_FEEDS: list[str] = [
    "https://news.ycombinator.com/rss",
]

# ── Source authority map (0-1). Higher = more trusted. ────────────────────────

SOURCE_AUTHORITY: dict[str, float] = {
    "google_news": 0.75,
    "hackernews": 0.85,
    "reddit": 0.55,
    "rss": 0.60,
    "youtube_rss": 0.50,
}


def source_authority(source: str) -> float:
    return SOURCE_AUTHORITY.get(source, 0.50)


# ── Dispatch ─────────────────────────────────────────────────────────────────

def fetch_all(sources: list[str], topic: str | None = None) -> list[FeedItem]:
    items: list[FeedItem] = []
    for name in sources:
        try:
            items.extend(_FETCHERS[name](topic=topic))
        except Exception as exc:
            print(f"⚠️  feed source {name} failed: {exc}")
    return items


def source_status() -> dict[str, Any]:
    """Quick health check for each configured source."""
    status: dict[str, Any] = {}
    for name, fn in _FETCHERS.items():
        try:
            sample = fn(limit=1)
            status[name] = {"ok": True, "sample": len(sample)}
        except Exception as exc:
            status[name] = {"ok": False, "error": str(exc)}
    return status


# ── Google News RSS ───────────────────────────────────────────────────────────

def fetch_google_news(topic: str | None = None, limit: int = 20) -> list[FeedItem]:
    if topic:
        query = urllib.parse.quote_plus(topic)
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        return _parse_rss_feed(url, "google_news", limit=limit)
    # No explicit topic: sweep every configured topic feed so the feed
    # covers AI, agents, software engineering, open source, languages, etc.
    per_topic = max(3, limit // max(1, len(GOOGLE_NEWS_TOPICS)))
    items: list[FeedItem] = []
    for name, url in GOOGLE_NEWS_TOPICS.items():
        try:
            items.extend(_parse_rss_feed(url, "google_news", limit=per_topic))
        except Exception as exc:
            print(f"⚠️  google news topic {name} failed: {exc}")
    return items


# ── Hacker News ─────────────────────────────────────────────────────────────

def fetch_hackernews(topic: str | None = None, limit: int = 20) -> list[FeedItem]:
    items: list[FeedItem] = []
    seen_ids: set[int] = set()
    for endpoint in HACKERNEWS_URLS:
        try:
            data = _http_json(endpoint)
            if not isinstance(data, list):
                continue
            ids = data[:limit]
            for story_id in ids:
                if story_id in seen_ids:
                    continue
                seen_ids.add(story_id)
                story = _http_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
                if not story or story.get("deleted") or story.get("type") != "story":
                    continue
                title = story.get("title", "")
                url = story.get("url", "")
                if not url:
                    url = f"https://news.ycombinator.com/item?id={story_id}"
                if topic and not _topic_match(title, topic):
                    continue
                items.append(
                    FeedItem(
                        title=title,
                        url=url,
                        source="hackernews",
                        published_at=_ts_to_iso(story.get("time")),
                    )
                )
                if len(items) >= limit:
                    break
        except Exception as exc:
            print(f"⚠️  hackernews endpoint {endpoint} failed: {exc}")
    return items


# ── Reddit ────────────────────────────────────────────────────────────────────

def fetch_reddit(topic: str | None = None, limit: int = 20) -> list[FeedItem]:
    items: list[FeedItem] = []
    headers = {
        "User-Agent": "smkit:feed:v1 (by /u/buildwithabdallah)",
    }
    for sub in REDDIT_SUBREDDITS:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit={min(limit, 10)}"
            data = _http_json(url, headers=headers)
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                title = post.get("title", "")
                url = post.get("url_overridden_by_dest") or post.get("url", "")
                # Skip self-only posts without an external link.
                if not url or url.startswith("/r/") or "reddit.com" in url:
                    continue
                if topic and not _topic_match(title, topic):
                    continue
                items.append(
                    FeedItem(
                        title=title,
                        url=canonical_url(url),
                        source=f"reddit/r/{sub}",
                        published_at=_ts_to_iso(post.get("created_utc")),
                    )
                )
            if len(items) >= limit:
                break
        except Exception as exc:
            print(f"⚠️  reddit r/{sub} failed: {exc}")
    return items[:limit]


# ── Generic RSS ─────────────────────────────────────────────────────────────

def fetch_rss(topic: str | None = None, limit: int = 20) -> list[FeedItem]:
    """Fetch configured RSS feeds. Topic filtering is applied client-side."""
    from agent.config import _read_yaml, CONFIG_DIR

    cfg = _read_yaml(CONFIG_DIR / "feed.yaml")
    feeds = cfg.get("rss_feeds", DEFAULT_RSS_FEEDS)
    items: list[FeedItem] = []
    for feed_url in feeds:
        try:
            for item in _parse_rss_feed(feed_url, "rss", limit=limit):
                if topic and not _topic_match(item.title, topic):
                    continue
                items.append(item)
        except Exception as exc:
            print(f"⚠️  rss feed {feed_url} failed: {exc}")
    return items[:limit]


# ── YouTube channel RSS ─────────────────────────────────────────────────────

def fetch_youtube_rss(topic: str | None = None, limit: int = 20) -> list[FeedItem]:
    from agent.config import _read_yaml, CONFIG_DIR

    cfg = _read_yaml(CONFIG_DIR / "feed.yaml")
    handles = cfg.get("youtube_handles", YOUTUBE_CHANNEL_HANDLES)
    items: list[FeedItem] = []
    for handle in handles:
        url = f"https://www.youtube.com/feeds/videos.xml?user={handle}"
        if handle.startswith("@"):
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={handle}"
        try:
            for item in _parse_rss_feed(url, "youtube_rss", limit=limit):
                if topic and not _topic_match(item.title, topic):
                    continue
                items.append(item)
        except Exception as exc:
            print(f"⚠️  youtube rss {handle} failed: {exc}")
    return items[:limit]


_FETCHERS = {
    "google_news": fetch_google_news,
    "hackernews": fetch_hackernews,
    "reddit": fetch_reddit,
    "rss": fetch_rss,
    "youtube_rss": fetch_youtube_rss,
}


# ── Shared helpers ──────────────────────────────────────────────────────────

def _http_json(url: str, headers: dict[str, str] | None = None) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_text(url: str, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "smkit-feed/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_rss_feed(url: str, source: str, limit: int = 20) -> list[FeedItem]:
    text = _http_text(url)
    root = ET.fromstring(text)
    ns = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}
    items: list[FeedItem] = []
    for channel in root.findall(".//channel") or [root]:
        for elem in channel.findall("item"):
            title = _safe_text(elem, "title")
            link = _safe_text(elem, "link")
            if not link:
                # atom link
                link_elem = elem.find("atom:link", ns)
                if link_elem is not None:
                    link = link_elem.get("href", "")
            if not title or not link:
                continue
            pub = _safe_text(elem, "pubDate") or _safe_text(elem, "published", ns)
            items.append(
                FeedItem(
                    title=title,
                    url=canonical_url(link),
                    source=source,
                    published_at=_normalize_date(pub),
                )
            )
            if len(items) >= limit:
                return items
    return items


def _safe_text(parent, tag: str, ns: dict[str, str] | None = None) -> str:
    if ns:
        el = parent.find(tag, ns)
    else:
        el = parent.find(tag)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _normalize_date(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    # RSS date formats: RFC 2822, ISO 8601.
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).astimezone(dt.timezone.utc).isoformat()
        except ValueError:
            continue
    return value


def _ts_to_iso(ts: Any) -> str:
    if not ts:
        return ""
    try:
        return dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).isoformat()
    except (ValueError, TypeError):
        return ""


def _topic_match(text: str, topic: str) -> bool:
    """Case-insensitive word/phrase match for topic filtering."""
    text = text.lower()
    topic = topic.lower()
    return topic in text or any(word in text for word in topic.split())


import urllib.parse
import urllib.request
