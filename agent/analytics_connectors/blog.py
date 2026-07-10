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

The connector supports the documented nested response shape
(payload["metrics"]["page_views"] ...) plus the legacy flat shape for backward
compatibility.

Status values:
- connected
- not_connected
- not_found
- unauthorized
- error
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


def _slug_from_url(blog_url: str) -> str:
    from urllib.parse import urlparse
    return Path(urlparse(blog_url).path).name or "unknown"


@dataclass
class BlogAnalytics:
    blog_url: str
    page_views: int | None = None
    unique_visitors: int | None = None
    clicks: int | None = None
    average_read_time_seconds: float | None = None
    referrers: list[dict[str, Any]] = field(default_factory=list)
    publication_date: str | None = None
    period: dict[str, str | None] = field(default_factory=dict)
    last_sync_at: str | None = None
    status: str = "unknown"  # connected, not_connected, not_found, unauthorized, error
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
            "period": self.period,
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


def _cache_path(blog_url: str, from_date: str | None = None, to_date: str | None = None) -> Path:
    slug = _slug_from_url(blog_url)
    safe = "".join(c if c.isalnum() else "_" for c in slug)
    parts = [safe]
    if from_date:
        parts.append(f"from_{from_date}")
    if to_date:
        parts.append(f"to_{to_date}")
    return CACHE_DIR / f"{'__'.join(parts)}.json"


def _read_cache(blog_url: str, from_date: str | None = None, to_date: str | None = None) -> BlogAnalytics | None:
    p = _cache_path(blog_url, from_date, to_date)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    # Period must be reconstructed from dict keys (dataclass as_dict keeps it as dict)
    return BlogAnalytics(**{k: data.get(k) for k in BlogAnalytics.__dataclass_fields__})


def _write_cache(blog_url: str, analytics: BlogAnalytics, from_date: str | None = None, to_date: str | None = None) -> None:
    p = _cache_path(blog_url, from_date, to_date)
    p.write_text(json.dumps(analytics.to_dict(), indent=2), encoding="utf-8")


def _api_url_for_post(blog_url: str, base_api_url: str) -> str | None:
    """Map public URL to the site's post analytics endpoint.

    Public pattern: https://buildwithabdallah.com/tutorials/<slug>
    We assume the API exposes /api/v1/posts/<slug>/analytics.
    """
    slug = _slug_from_url(blog_url)
    if not slug or slug == "unknown":
        return None
    return f"{base_api_url}/posts/{slug}/{ANALYTICS_API_SUFFIX}"


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


def _normalize_referrers(raw: Any) -> list[dict[str, Any]]:
    """Normalize referrer data to list of {source, visits}."""
    if isinstance(raw, list):
        return [
            {"source": str(item.get("source", item.get("name", "unknown"))).lower(),
             "visits": _to_int(item.get("visits", item.get("count", 0)))}
            for item in raw
            if isinstance(item, dict)
        ]
    if isinstance(raw, dict):
        return [{"source": str(k).lower(), "visits": _to_int(v)} for k, v in raw.items()]
    return []


def _extract_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Support both documented nested metrics and legacy flat metrics."""
    if isinstance(data.get("metrics"), dict):
        return data["metrics"]
    return data


def _fetch_from_api(
    blog_url: str,
    base_api_url: str,
    token: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> BlogAnalytics:
    endpoint = _api_url_for_post(blog_url, base_api_url)
    if not endpoint:
        return BlogAnalytics(
            blog_url=blog_url,
            status="error",
            error="Could not derive API endpoint from blog_url",
        )

    params = {}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date

    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=20)
    except Exception as exc:
        return BlogAnalytics(blog_url=blog_url, status="error", error=str(exc))

    if resp.status_code == 404:
        return BlogAnalytics(
            blog_url=blog_url,
            status="not_found",
            error="Post not found",
        )

    if resp.status_code == 401:
        return BlogAnalytics(
            blog_url=blog_url,
            status="unauthorized",
            error="Invalid or missing API token",
        )

    if resp.status_code == 403:
        return BlogAnalytics(
            blog_url=blog_url,
            status="unauthorized",
            error="Forbidden: insufficient permissions",
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
    metrics = _extract_metrics(data)
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    api_status = data.get("status", "connected")
    if api_status == "not_connected":
        return BlogAnalytics(
            blog_url=blog_url,
            status="not_connected",
            publication_date=data.get("published_at", data.get("publication_date")),
            period=data.get("period", {"from": from_date, "to": to_date}),
            last_sync_at=now,
        )

    return BlogAnalytics(
        blog_url=blog_url,
        page_views=_to_int(metrics.get("page_views", metrics.get("views"))),
        unique_visitors=_to_int(metrics.get("unique_visitors", metrics.get("unique_users", metrics.get("uniqueUsers")))),
        clicks=_to_int(metrics.get("clicks")),
        average_read_time_seconds=_to_float(metrics.get("average_read_time_seconds", metrics.get("avg_read_time", metrics.get("average_read_time")))),
        referrers=_normalize_referrers(metrics.get("referrers", metrics.get("sources", []))),
        publication_date=data.get("published_at", data.get("publication_date")),
        period=data.get("period", {"from": from_date, "to": to_date}),
        last_sync_at=now,
        status="connected",
    )


def fetch_blog_analytics(
    blog_url: str,
    use_cache: bool = True,
    force_refresh: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
) -> BlogAnalytics:
    """Fetch blog analytics for a single published URL.

    Caches locally unless force_refresh=True. Date range is part of the cache key.
    """
    if use_cache and not force_refresh:
        cached = _read_cache(blog_url, from_date, to_date)
        if cached:
            return cached

    base_api_url, token = _load_credentials()
    analytics = _fetch_from_api(blog_url, base_api_url, token, from_date, to_date)
    _write_cache(blog_url, analytics, from_date, to_date)
    return analytics


def fetch_all_blog_analytics(
    draft_dir: Path | None = None,
    force_refresh: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
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
            results.append(
                fetch_blog_analytics(draft.blog_url, force_refresh=force_refresh, from_date=from_date, to_date=to_date)
            )
    return results


def sync_blog_analytics(
    draft_dir: Path | None = None,
    force_refresh: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    """Sync blog analytics for all published drafts.

    Returns a summary dict with per-URL results and last sync time.
    """
    results = fetch_all_blog_analytics(
        draft_dir=draft_dir,
        force_refresh=force_refresh,
        from_date=from_date,
        to_date=to_date,
    )
    connected = sum(1 for r in results if r.status == "connected")
    not_connected = sum(1 for r in results if r.status == "not_connected")
    not_found = sum(1 for r in results if r.status == "not_found")
    unauthorized = sum(1 for r in results if r.status == "unauthorized")
    errors = sum(1 for r in results if r.status == "error")
    return {
        "ok": True,
        "source": "blog",
        "synced": len(results),
        "connected_count": connected,
        "not_connected_count": not_connected,
        "not_found_count": not_found,
        "unauthorized_count": unauthorized,
        "error_count": errors,
        "period": {"from": from_date, "to": to_date},
        "last_sync_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "results": [r.to_dict() for r in results],
    }
