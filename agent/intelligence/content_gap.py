"""Content gap detection for the Content Intelligence Engine."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from .. import history
from .config import IntelligenceConfig
from .models import ContentGapResult, ExistingContentItem


def _fetch_sitemap(url: str) -> str:
    """Fetch sitemap XML with safe failure handling."""
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return ""


def _parse_sitemap_xml(xml_text: str, base_url: str) -> list[ExistingContentItem]:
    """Parse sitemap.xml into ExistingContentItem objects."""
    items: list[ExistingContentItem] = []
    if not xml_text:
        return items
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return items

    # Handle default namespace.
    ns = {"ns": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    url_tag = "ns:url" if ns else "url"
    loc_tag = "ns:loc" if ns else "loc"
    lastmod_tag = "ns:lastmod" if ns else "lastmod"

    for url_el in root.findall(url_tag, ns):
        loc = url_el.findtext(loc_tag, "", ns).strip()
        if not loc:
            continue
        lastmod = url_el.findtext(lastmod_tag, "", ns) or None
        slug = loc.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ").replace("_", " ").title()
        items.append(
            ExistingContentItem(
                title=title,
                url=loc,
                slug=slug,
                category="",
                published_at=lastmod,
                source="sitemap",
                topics=[],
                summary="",
            )
        )
    return items


def load_sitemap_content(
    sitemap_url: str = "https://buildwithabdallah.com/sitemap.xml",
) -> list[ExistingContentItem]:
    """Load existing content from the website sitemap."""
    xml = _fetch_sitemap(sitemap_url)
    return _parse_sitemap_xml(xml, sitemap_url)


def _load_smkit_history_content() -> list[ExistingContentItem]:
    """Load previously published topics from smkit history."""
    items: list[ExistingContentItem] = []
    try:
        hist = history.load()
    except Exception:
        return items
    for entry in hist:
        topic = entry.get("topic", "")
        if not topic:
            continue
        slug = entry.get("slug", topic.lower().replace(" ", "-"))
        url = f"https://buildwithabdallah.com/tutorials/{slug}"
        items.append(
            ExistingContentItem(
                title=topic,
                url=url,
                slug=slug,
                category=entry.get("category", ""),
                published_at=entry.get("published_at"),
                source="smkit-history",
                topics=[],
                summary="",
            )
        )
    return items


def load_local_content_index(path: str | Path | None = None) -> list[ExistingContentItem]:
    """Load existing content from a local JSON file."""
    if path is None:
        path = Path.home() / ".openclaw" / "workspace" / "content" / "existing_content.json"
    path = Path(path)
    if not path.exists():
        return []
    items: list[ExistingContentItem] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return items
    if not isinstance(raw, list):
        return items
    for item in raw:
        if isinstance(item, dict):
            items.append(ExistingContentItem(**item))
    return items


def _normalize(text: str) -> str:
    """Normalize text for comparison."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _token_set(text: str) -> set[str]:
    """Return a set of meaningful tokens."""
    normalized = _normalize(text)
    # Drop common filler words.
    stopwords = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by",
        "and", "or", "is", "are", "was", "were", "be", "been", "being",
        "how", "what", "why", "when", "where", "can", "do", "does", "did",
        "you", "i", "we", "it", "this", "that", "my", "your", "tutorial",
        "guide", "build", "using", "use", "make", "best", "way", "top", "vs",
    }
    return {t for t in normalized.split() if t not in stopwords and len(t) > 1}


def _days_since(value: str | None) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
        return delta.days
    except Exception:
        return None


def detect_content_gap(
    opportunity_title: str,
    opportunity_summary: str,
    existing_items: list[ExistingContentItem],
) -> ContentGapResult:
    """Compare an opportunity to existing content and return a gap analysis."""
    if not existing_items:
        return ContentGapResult(
            gap_score=100,
            duplicate_risk="none",
            action="create",
            reason="No existing content found — true gap.",
        )

    opp_tokens = _token_set(f"{opportunity_title} {opportunity_summary}")
    if not opp_tokens:
        return ContentGapResult(
            gap_score=50,
            duplicate_risk="unknown",
            action="create",
            reason="Could not extract comparison tokens from opportunity.",
        )

    scored_items: list[tuple[ExistingContentItem, float]] = []
    for item in existing_items:
        item_tokens = _token_set(f"{item.title} {item.summary} {' '.join(item.topics)}")
        if not item_tokens:
            continue
        overlap = opp_tokens & item_tokens
        union = opp_tokens | item_tokens
        jaccard = len(overlap) / len(union) if union else 0.0
        scored_items.append((item, jaccard))

    if not scored_items:
        return ContentGapResult(
            gap_score=100,
            duplicate_risk="none",
            action="create",
            reason="No comparable existing content found.",
        )

    scored_items.sort(key=lambda x: x[1], reverse=True)
    best_match, best_score = scored_items[0]
    related = [item for item, score in scored_items[:3] if score > 0.05]

    if best_score >= 0.65:
        age_days = _days_since(best_match.published_at)
        if age_days is not None and age_days <= 14:
            return ContentGapResult(
                gap_score=10,
                duplicate_risk="high",
                action="skip",
                related_items=related,
                reason=f"Very similar recent content exists ({best_match.url}).",
            )
        return ContentGapResult(
            gap_score=35,
            duplicate_risk="medium",
            action="update",
            related_items=related,
            reason=f"Similar content exists but may be outdated ({best_match.url}).",
        )

    if best_score >= 0.25:
        return ContentGapResult(
            gap_score=65,
            duplicate_risk="low",
            action="create-short",
            related_items=related,
            reason=f"Related content exists but this is a distinct angle ({best_match.url}).",
        )

    return ContentGapResult(
        gap_score=100,
        duplicate_risk="none",
        action="create",
        related_items=related,
        reason="True gap — no close existing coverage.",
    )


def load_existing_content(config: IntelligenceConfig) -> list[ExistingContentItem]:
    """Load all existing content sources configured for gap detection."""
    items: list[ExistingContentItem] = []

    sitemap_url = getattr(config, "sitemap_url", None) or "https://buildwithabdallah.com/sitemap.xml"
    try:
        items.extend(load_sitemap_content(sitemap_url))
    except Exception:
        pass

    try:
        items.extend(_load_smkit_history_content())
    except Exception:
        pass

    local_path = getattr(config, "existing_content_file", None)
    try:
        items.extend(load_local_content_index(local_path))
    except Exception:
        pass

    return items
