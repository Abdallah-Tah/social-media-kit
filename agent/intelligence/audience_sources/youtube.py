"""YouTube comment collector for Layer 2."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from ..models import AudienceSignal


def _get_api_key() -> str | None:
    return os.getenv("YOUTUBE_API_KEY")


def _get_channel_id() -> str | None:
    return os.getenv("YOUTUBE_CHANNEL_ID")


def _fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def _parse_iso_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return value


def fetch_recent_video_ids(api_key: str, channel_id: str, max_results: int = 10) -> list[str]:
    """Return recent video IDs from a YouTube channel."""
    data = _fetch_json(
        "https://www.googleapis.com/youtube/v3/search",
        {
            "key": api_key,
            "channelId": channel_id,
            "part": "id",
            "order": "date",
            "maxResults": max_results,
            "type": "video",
        },
    )
    if "error" in data:
        return []
    return [item["id"]["videoId"] for item in data.get("items", []) if "videoId" in item.get("id", {})]


def fetch_video_comments(
    api_key: str,
    video_id: str,
    max_results: int = 50,
) -> list[AudienceSignal]:
    """Return top-level comments for a single video."""
    signals: list[AudienceSignal] = []
    data = _fetch_json(
        "https://www.googleapis.com/youtube/v3/commentThreads",
        {
            "key": api_key,
            "videoId": video_id,
            "part": "snippet",
            "maxResults": max_results,
            "order": "relevance",
        },
    )
    if "error" in data:
        return signals

    for thread in data.get("items", []):
        snippet = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        text = snippet.get("textDisplay", "").strip()
        if not text or len(text) < 8:
            continue
        signals.append(
            AudienceSignal(
                platform="youtube",
                text=text,
                author=snippet.get("authorDisplayName", ""),
                url=f"https://www.youtube.com/watch?v={video_id}",
                published_at=_parse_iso_timestamp(snippet.get("publishedAt")),
                source_id=snippet.get("commentId", thread.get("id", "")),
                engagement_count=thread.get("snippet", {}).get("totalReplyCount", 0),
                metadata={"video_id": video_id, "like_count": snippet.get("likeCount", 0)},
            )
        )
    return signals


def collect_youtube_signals(
    api_key: str | None = None,
    channel_id: str | None = None,
    max_videos: int = 10,
    max_comments_per_video: int = 50,
) -> list[AudienceSignal]:
    """Collect YouTube audience signals if credentials are available."""
    api_key = api_key or _get_api_key()
    channel_id = channel_id or _get_channel_id()
    if not api_key or not channel_id:
        return []

    signals: list[AudienceSignal] = []
    video_ids = fetch_recent_video_ids(api_key, channel_id, max_videos)
    for video_id in video_ids:
        signals.extend(
            fetch_video_comments(api_key, video_id, max_comments_per_video)
        )
    return signals
