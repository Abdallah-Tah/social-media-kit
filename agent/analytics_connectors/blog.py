"""Build With Abdallah blog analytics connector.

Fetches post-level analytics from the Laravel REST API and maps them back to
content drafts, intelligence cards, and social drafts in the local workspace.

Read-only. Caches API responses to avoid repeated calls.

Supported metrics:
- page_views
- unique_visitors
- clicks
- average_read_time_seconds
- referrers
- publication_date

If the API endpoint returns 404, status is recorded as "not_connected" and no
values are invented.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

KIT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = KIT_ROOT / "content" / "analytics" / "connector_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ANALYTICS_API_SUFFIX = "analytics"


@dataclass
class BlogAnalytics:
    blog_url: str
    page_views: int | None = None
    unique_visitors: int | None = None
    clicks: int | None = None
    average_read_time_seconds: float | None = None
    referrers: dict[str, int] = field(default_factory=dict)
    publication_date: str | None = None
    last_sync_at: str | None = None
    status: str = "unknown"  # ok, not_connected, error
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "blog_url": self.blog_url,
            "page_views": self.page_views,
            "unique_visitors": self.unique_visitors,
            "clicks": self.clicks,
            "average_read_time_seconds": self.average_read_time_seconds,
            "referrers": self.referrers,
            "publication_date": self.publication_date,
            "last_sync_at": self.last_sync_at,
            "status": self.status,
            "error": self.error,
        }


def _load_credentials() -> tuple[str, str]:
    """Load credentials from environment, matching blog_publisher behavior."""
    import os
    from agent.config import load_env
    load_env()
    api_url = os.environ.get("BLOG_API_URL", "").rstrip("/")
    api_token = os.environ.get("BLOG_API_TOKEN", "")
    if not api_url or not api_token:
        from scripts.blog_publisher import load_credentials
        api_url, api_token = load_credentials()
    return api_url, api_token


def _cache_path(blog_url: str) -> Path:
    from urllib.parse import urlparse
    slug = Path(urlparse(blog_url).path).name or "unknown"
    safe = "".join(c if c.isalnum() else "_" for c in slug)
    return CACHE_DIR / f"{safe}.json"


def _read_cache(blog_url: str) -> BlogAnalytics | None:
    p = _cache_path(blog_url)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return BlogAnalytics(**{k: data.get(k) for k in BlogAnalytics.__dataclass_fields__})


def _write_cache(blog_url: str, analytics: BlogAnalytics) -> None:
    p = _cache_path(blog_url)
    p.write_text(json.dumps(analytics.to_dict(), indent=2), encoding="utf-8")


def _api_url_for_post(blog_url: str, base_api_url: str) -> str | None:
    """Map public URL to the site's post analytics endpoint.

    Public pattern: https://buildwithabdallah.com/tutorials/<slug>
    We assume the API exposes /api/v1/posts/<slug>/analytics.
    """
    from urllib.parse import urlparse
    path = Path(urlparse(blog_url).path)
    slug = path.name
    if not slug:
        return None
    # Some blog URLs may include /tutorials/ or similar prefix; strip it.
    return f"{base_api_url}/posts/{slug}/{ANALYTICS_API_SUFFIX}"


def _fetch_from_api(blog_url: str, base_api_url: str, token: str) -> BlogAnalytics:
    endpoint = _api_url_for_post(blog_url, base_api_url)
    if not endpoint:
        return BlogAnalytics(
            blog_url=blog_url,
            status="error",
            error="Could not derive API endpoint from blog_url",
        )

    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(endpoint, headers=headers, timeout=20)
    except Exception as exc:
        return BlogAnalytics(blog_url=blog_url, status="error", error=str(exc))

    if resp.status_code == 404:
        return BlogAnalytics(
            blog_url=blog_url,
            status="not_connected",
            error="Analytics endpoint not available for this post",
        )

    if resp.status_code != 200:
        return BlogAnalytics(
            blog_url=blog_url,
            status="error",
            error=f"HTTP {resp.status_code}: {resp.text[:200]}",
        )

    try:
        payload = resp.json()
    except json.JSONDecodeError:
        return BlogAnalytics(
            blog_url=blog_url, status="error", error="Non-JSON response"
        )

    data = payload.get("data", payload)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return BlogAnalytics(
        blog_url=blog_url,
        page_views=_to_int(data.get("page_views", data.get("views"))),
        unique_visitors=_to_int(data.get("unique_visitors", data.get("uniqueUsers", data.get("unique_visitors")))),
        clicks=_to_int(data.get("clicks")),
        average_read_time_seconds=_to_float(data.get("average_read_time_seconds", data.get("avg_read_time"))),
        referrers=data.get("referrers", data.get("sources", {})),
        publication_date=data.get("published_at", data.get("publication_date")),
        last_sync_at=now,
        status="ok",
    )


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_blog_analytics(
    blog_url: str,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> BlogAnalytics:
    """Fetch blog analytics for a single published URL.

    Caches locally unless force_refresh=True.
    """
    if use_cache and not force_refresh:
        cached = _read_cache(blog_url)
        if cached:
            return cached

    base_api_url, token = _load_credentials()
    analytics = _fetch_from_api(blog_url, base_api_url, token)
    _write_cache(blog_url, analytics)
    return analytics


def fetch_all_blog_analytics(
    draft_dir: Path | None = None,
    force_refresh: bool = False,
) -> list[BlogAnalytics]:
    """Fetch analytics for every published draft with a blog_url."""
    from agent.drafts import DRAFTS_DIR as DEFAULT_DRAFTS_DIR, load_draft
    directory = draft_dir or DEFAULT_DRAFTS_DIR
    results = []
    for p in directory.glob("*.json"):
        try:
            draft = load_draft(p.stem)
        except Exception:
            continue
        if draft and draft.blog_url and draft.status == "published":
            results.append(fetch_blog_analytics(draft.blog_url, force_refresh=force_refresh))
    return results


def sync_blog_analytics(
    draft_dir: Path | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Sync blog analytics for all published drafts.

    Returns a summary dict with per-URL results and last sync time.
    """
    results = fetch_all_blog_analytics(draft_dir=draft_dir, force_refresh=force_refresh)
    ok = sum(1 for r in results if r.status == "ok")
    not_connected = sum(1 for r in results if r.status == "not_connected")
    errors = sum(1 for r in results if r.status == "error")
    return {
        "ok": True,
        "source": "blog",
        "synced": len(results),
        "ok_count": ok,
        "not_connected_count": not_connected,
        "error_count": errors,
        "last_sync_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "results": [r.to_dict() for r in results],
    }
