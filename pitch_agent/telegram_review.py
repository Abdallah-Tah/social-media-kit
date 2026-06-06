"""Telegram review integration using the existing smkit Telegram poster."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from pitch_agent.config import ROOT, load_env

SAFE_METADATA_KEYS = [
    "mode",
    "pillar",
    "brand",
    "brand_parent",
    "leaderboard_scope",
    "chart_path",
    "provider_name",
    "data_quality_level",
    "status_note",
    "post_key",
]

# Review-only banner shown when the post is built from sample CSV data so the
# reviewer never mistakes it for live tournament data. It stays out of the
# public fan content.
DEMO_DATA_WARNING = "Demo data only — not live tournament data."


def send_review(
    generated: dict[str, Any],
    debug: bool = False,
) -> dict[str, Any]:
    """Send generated pitch-agent content to the smkit Telegram review flow."""
    load_env()
    missing = _missing_credentials()
    metadata = _safe_metadata(generated.get("metadata", {}))
    chart_path = metadata.get("chart_path", "")
    if missing:
        warning = (
            "⚠️ Telegram review skipped: missing "
            f"{', '.join(missing)}. Set Telegram credentials or omit "
            "--send-telegram-review."
        )
        print(warning)
        return {
            "sent": False,
            "message_sent": False,
            "photo_sent": False,
            "skipped": True,
            "strict_failure": True,
            "missing_credentials": missing,
            "warning": warning,
            "chart_path": chart_path,
        }

    poster = _load_telegram_poster()
    message = _build_review_message(generated, metadata, debug=debug)

    message_result = poster.post_message(message)
    photo_result = None
    if message_result and chart_path and Path(chart_path).is_file() and hasattr(poster, "post_photo"):
        photo_result = poster.post_photo(
            chart_path,
            caption=f"The Pitch Agent chart review: {metadata.get('post_key', '')}",
        )

    return {
        "sent": bool(message_result),
        "message_sent": bool(message_result),
        "photo_sent": bool(photo_result),
        "skipped": False,
        "strict_failure": False,
        "chart_path": chart_path,
    }


def _load_telegram_poster() -> Any:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import telegram_poster

    return telegram_poster


def _missing_credentials() -> list[str]:
    missing = []
    if not (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")):
        missing.append("TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN")
    if not (os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID")):
        missing.append("TELEGRAM_CHAT_ID or CHAT_ID")
    return missing


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(metadata.get(key, ""))
        for key in SAFE_METADATA_KEYS
        if metadata.get(key, "") not in (None, "")
    }


def _build_review_message(
    generated: dict[str, Any],
    metadata: dict[str, str],
    debug: bool = False,
) -> str:
    visible_post = str(generated.get("content", "")).strip()
    lines = ["The Pitch Agent review", ""]
    if _is_demo_data(metadata):
        lines.extend([f"⚠️ {DEMO_DATA_WARNING}", ""])
    lines.extend([
        "Visible post:",
        visible_post,
        "",
        "Review metadata:",
    ])
    summary = _review_metadata_summary(metadata, debug=debug)
    for label, value in summary:
        lines.append(f"{label}: {value}")

    if debug:
        lines.extend([
            "",
            "Debug payload:",
            json.dumps(generated, indent=2, sort_keys=True, default=str),
        ])

    return "\n".join(lines)


def _is_demo_data(metadata: dict[str, str]) -> bool:
    """True when the post was built from the sample CSV provider."""
    providers = (metadata.get("provider_name") or "").lower()
    return "csv" in [p.strip() for p in providers.split(",") if p.strip()]


def _review_metadata_summary(
    metadata: dict[str, str],
    debug: bool = False,
) -> list[tuple[str, str]]:
    chart_value = metadata.get("chart_path", "")
    if chart_value and not debug:
        chart_value = Path(chart_value).name
    fields = [
        ("brand", metadata.get("brand", "")),
        ("by", metadata.get("brand_parent", "")),
        ("mode", metadata.get("mode", "")),
        ("pillar", metadata.get("pillar", "")),
        ("scope", metadata.get("leaderboard_scope", "")),
        ("chart", chart_value),
        ("provider", metadata.get("provider_name", "")),
        ("quality", metadata.get("data_quality_level", "")),
        ("status", metadata.get("status_note", "")),
    ]
    return [(label, value) for label, value in fields if value]
