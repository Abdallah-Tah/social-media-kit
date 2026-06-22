"""Signal collection for Layer 1 (Trend Radar)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

import requests

from .config import IntelligenceConfig
from .models import TrendSignal


def _fetch_json(url: str, timeout: int = 20) -> dict[str, Any] | list[Any]:
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "smkit-intelligence/1.0"})
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def fetch_hacker_news_signals(config: IntelligenceConfig) -> list[TrendSignal]:
    """Collect trending HN stories matching brand queries."""
    signals: list[TrendSignal] = []
    top_ids = _fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not isinstance(top_ids, list):
        return signals

    # Look at top 60 stories; score relevance by query overlap.
    for story_id in top_ids[:60]:
        story = _fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        if not isinstance(story, dict):
            continue
        title = story.get("title", "")
        if not title:
            continue
        text = f"{title} {story.get('text', '')}".lower()
        matched_queries = [q for q in config.hacker_news_queries if q.lower() in text]
        if not matched_queries:
            continue
        signals.append(
            TrendSignal(
                title=title,
                source="hacker-news",
                url=story.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                summary=story.get("text", "")[:300],
                topics=matched_queries,
                published=_unix_to_iso(story.get("time")),
                raw=story,
            )
        )
    return signals


def fetch_reddit_signals(config: IntelligenceConfig) -> list[TrendSignal]:
    """Collect hot posts from configured subreddits."""
    signals: list[TrendSignal] = []
    for sub in config.reddit_subreddits:
        data = _fetch_json(
            f"https://www.reddit.com/r/{sub}/hot.json?limit=15",
            timeout=20,
        )
        if isinstance(data, dict) and "error" in data:
            continue
        if not isinstance(data, dict):
            continue
        for post in data.get("data", {}).get("children", []):
            p = post.get("data", {})
            title = p.get("title", "")
            if not title:
                continue
            signals.append(
                TrendSignal(
                    title=title,
                    source=f"reddit:r/{sub}",
                    url=p.get("url") or f"https://www.reddit.com{p.get('permalink', '')}",
                    summary=p.get("selftext", "")[:300],
                    topics=[sub],
                    published=None,
                    raw=p,
                )
            )
    return signals


def fetch_github_trending_signals(config: IntelligenceConfig) -> list[TrendSignal]:
    """Collect GitHub trending repositories for configured topics."""
    signals: list[TrendSignal] = []
    date_param = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    for topic in config.github_trending_topics:
        # GitHub search API: repos created or pushed recently, sorted by stars.
        url = (
            "https://api.github.com/search/repositories"
            f"?q=topic:{topic}+pushed:>{date_param}"
            "&sort=stars&order=desc&per_page=5"
        )
        data = _fetch_json(url, timeout=20)
        if not isinstance(data, dict):
            continue
        for repo in data.get("items", []):
            signals.append(
                TrendSignal(
                    title=repo.get("full_name", ""),
                    source="github-trending",
                    url=repo.get("html_url", ""),
                    summary=repo.get("description", "")[:300],
                    topics=[topic],
                    published=None,
                    raw=repo,
                )
            )
    return signals


def fetch_newsletter_headlines(config: IntelligenceConfig) -> list[TrendSignal]:
    """Lightweight RSS/headline fetch for configured newsletters.

    Phase 1: simple HTML title extraction. Future improvement: real RSS parsing.
    """
    signals: list[TrendSignal] = []
    for url in config.newsletters:
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "smkit-intelligence/1.0"})
            resp.raise_for_status()
            text = resp.text
            titles = re.findall(r"<title[^>]*>([^<]+)</title>", text, re.IGNORECASE)
            # First title is usually the site name; next few are article titles if RSS.
            for raw_title in titles[1:6]:
                title = raw_title.strip()
                if len(title) < 20:
                    continue
                signals.append(
                    TrendSignal(
                        title=title,
                        source=f"newsletter:{url}",
                        url=url,
                        summary="",
                        topics=[],
                        published=None,
                        raw={},
                    )
                )
        except Exception:
            continue
    return signals


def collect_trend_signals(config: IntelligenceConfig) -> list[TrendSignal]:
    """Run all enabled Layer 1 collectors and dedupe by URL."""
    all_signals: list[TrendSignal] = []
    if config.enable_hacker_news:
        all_signals.extend(fetch_hacker_news_signals(config))
    if config.enable_reddit:
        all_signals.extend(fetch_reddit_signals(config))
    if config.enable_github_trending:
        all_signals.extend(fetch_github_trending_signals(config))
    if config.enable_newsletters:
        all_signals.extend(fetch_newsletter_headlines(config))

    seen: set[str] = set()
    unique: list[TrendSignal] = []
    for sig in all_signals:
        key = sig.url.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(sig)
    return unique


def _unix_to_iso(timestamp: Any) -> str | None:
    try:
        return datetime.utcfromtimestamp(int(timestamp)).isoformat() + "Z"
    except Exception:
        return None
