"""Audience pain radar for Layer 2."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audience_sources.telegram import collect_telegram_signals
from .audience_sources.website import collect_website_signals
from .audience_sources.youtube import collect_youtube_signals
from .config import IntelligenceConfig
from .models import AudiencePain, AudienceSignal


# Common question/pain markers across dev channels.
PAIN_PATTERNS = [
    re.compile(r"\bhow (?:do|can|to|would|should) .*\?", re.IGNORECASE),
    re.compile(r"\b(?:what|which) (?:is|are|would|should|will) .*\?", re.IGNORECASE),
    re.compile(r"\bcan you .*\?", re.IGNORECASE),
    re.compile(r"\bcould you .*\?", re.IGNORECASE),
    re.compile(r"\bwhat['\u2019]?s the best .*\?", re.IGNORECASE),
    re.compile(r"\bstuck (?:with|trying|on|in|while|at|getting)", re.IGNORECASE),
    re.compile(r"\b(?:struggling|confused|error|issue|problem) (?:with|in|on|while|trying)", re.IGNORECASE),
    re.compile(r"\b(?:help|advice|tip).*?(?:with|on|for)", re.IGNORECASE),
    re.compile(r"\bi want to (?:build|learn|make|create|set up|deploy|automate)", re.IGNORECASE),
    re.compile(r"\bwhere (?:do|can|should) i (?:start|begin|learn|find)", re.IGNORECASE),
]


def _looks_like_question(text: str) -> bool:
    return any(p.search(text) for p in PAIN_PATTERNS)


def _extract_pain_label(text: str) -> str:
    """Produce a readable label from a question/pain sentence."""
    text = text.strip()
    first_sentence = text.split("?")[0].strip()
    if first_sentence and first_sentence != text:
        return first_sentence + "?"
    # For statements, use the first 12 words without forcing a question mark.
    words = text.split()[:12]
    label = " ".join(words).rstrip(".").strip()
    return label


def _load_text_samples(config: IntelligenceConfig) -> dict[str, list[str]]:
    """Load audience text samples from known workspace locations (fallback/dev mode)."""
    samples: dict[str, list[str]] = {}
    candidates = {
        "telegram": Path.home() / ".openclaw" / "workspace" / "audience" / "telegram_comments.txt",
        "youtube": Path.home() / ".openclaw" / "workspace" / "audience" / "youtube_comments.txt",
        "linkedin": Path.home() / ".openclaw" / "workspace" / "audience" / "linkedin_comments.txt",
        "facebook": Path.home() / ".openclaw" / "workspace" / "audience" / "facebook_comments.txt",
    }
    for channel, path in candidates.items():
        if path.exists():
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            samples[channel] = lines
    return samples


def _collect_text_signals(config: IntelligenceConfig) -> list[AudienceSignal]:
    """Convert fallback text files and website JSON into AudienceSignal objects."""
    samples = _load_text_samples(config)
    signals: list[AudienceSignal] = []
    for platform, lines in samples.items():
        for idx, line in enumerate(lines):
            signals.append(
                AudienceSignal(
                    platform=platform,
                    text=line,
                    author="",
                    url="",
                    published_at=None,
                    source_id=f"{platform}-{idx}",
                    engagement_count=0,
                )
            )
    # Website JSON is also a file-based fallback source.
    signals.extend(collect_website_signals())
    return signals


def _collect_live_signals(config: IntelligenceConfig, sources: list[str] | None = None) -> list[AudienceSignal]:
    """Collect live audience signals from enabled sources."""
    signals: list[AudienceSignal] = []
    if sources is None:
        sources = ["youtube", "telegram", "website"]

    for source in sources:
        try:
            if source == "youtube":
                signals.extend(collect_youtube_signals())
            elif source == "telegram":
                signals.extend(collect_telegram_signals())
            elif source == "website":
                signals.extend(collect_website_signals())
        except Exception as exc:
            # Never fail the full run because one platform fails.
            print(f"   ⚠️ audience source '{source}' failed: {exc}")
    return signals


def collect_audience_signals(
    config: IntelligenceConfig,
    live: bool = False,
    text_fallback: bool = True,
    sources: list[str] | None = None,
) -> list[AudienceSignal]:
    """Collect all audience signals: live first, then text fallback if enabled."""
    signals: list[AudienceSignal] = []
    if live:
        signals.extend(_collect_live_signals(config, sources))
    if text_fallback:
        signals.extend(_collect_text_signals(config))
    return signals


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _days_ago(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    try:
        delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
        return max(0, delta.days)
    except Exception:
        return None


def collect_audience_pain(
    config: IntelligenceConfig,
    live: bool = False,
    text_fallback: bool = True,
    sources: list[str] | None = None,
) -> list[AudiencePain]:
    """Cluster recurring questions/pains from audience signals."""
    if not config.enable_audience_pain:
        return []

    signals = collect_audience_signals(config, live=live, text_fallback=text_fallback, sources=sources)
    if not signals:
        return []

    # Extract candidate pain signals.
    candidates: list[tuple[str, AudienceSignal]] = []
    for signal in signals:
        if _looks_like_question(signal.text):
            label = _extract_pain_label(signal.text)
            candidates.append((label, signal))

    # Cluster by normalized label.
    clusters: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "label": "",
            "signals": [],
            "channels": set(),
            "count": 0,
            "engagement": 0,
            "timestamps": [],
        }
    )
    for label, signal in candidates:
        key = label.lower()
        cluster = clusters[key]
        if not cluster["label"]:
            cluster["label"] = label
        cluster["signals"].append(signal)
        cluster["channels"].add(signal.platform)
        cluster["count"] += 1
        cluster["engagement"] += max(0, signal.engagement_count)
        ts = _parse_timestamp(signal.published_at)
        if ts:
            cluster["timestamps"].append(ts)

    # Convert to AudiencePain objects.
    pains: list[AudiencePain] = []
    for cluster in sorted(clusters.values(), key=lambda c: c["count"], reverse=True):
        evidence_lines: list[str] = []
        for sig in cluster["signals"][:5]:
            line = f"[{sig.platform}] {sig.text}"
            if sig.author:
                line += f" (by {sig.author})"
            evidence_lines.append(line)

        most_recent = max(cluster["timestamps"]) if cluster["timestamps"] else None
        recency_days = _days_ago(most_recent)
        cross_platform = len(cluster["channels"]) > 1

        full_question = evidence_lines[0].split("]", 1)[-1].strip() if evidence_lines else cluster["label"]
        display = full_question.rstrip("?").strip()
        suggested = [
            f"Tutorial: {display}",
            f"Short: {display} in 60s",
            f"LinkedIn/FB: {display} — here's what most developers miss",
        ]

        pains.append(
            AudiencePain(
                label=cluster["label"],
                evidence=evidence_lines,
                channel=", ".join(sorted(cluster["channels"])),
                frequency=cluster["count"],
                suggested_angles=suggested,
                platforms=cluster["channels"],
                recency_days=recency_days,
                cross_platform=cross_platform,
                engagement_total=cluster["engagement"],
            )
        )
    return pains[:20]
