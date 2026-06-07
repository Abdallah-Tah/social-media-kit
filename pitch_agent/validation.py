"""Lightweight safety checks for generated Pitch Agent content.

These checks are intentionally small and dependency-free. They run before review
or publishing paths so World Cup cards/posts keep the required disclaimer and do
not accidentally use gambling, certainty, or placeholder wording.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pitch_agent import PITCH_AGENT_CARD_FOOTER, PITCH_AGENT_CAPTION_DISCLAIMER

PLACEHOLDER_TERMS = (
    "[add setup steps here]",
    "[first step]",
    "[add content here",
    "[add your analysis here]",
    "[feature]",
    "[value]",
)

FORBIDDEN_PUBLIC_TERMS = (
    " prediction ",
    " predictions ",
    "odds",
    "gambling",
    "sportsbook",
    "wagering",
    "guaranteed prediction",
    "sure win",
    " lock ",
    " pick ",
    " betting pick",
    " gambling pick",
)

CERTAINTY_TERMS = (
    "guaranteed",
    "sure win",
    "cannot lose",
    "will definitely",
)

# Required disclaimer contains "Not betting advice". Treat that exact phrase as
# allowed while still blocking other betting/pick/gambling language.
ALLOWED_DISCLAIMER_PHRASES = (
    "not betting advice",
    "data-based estimates, not betting advice",
)


def _without_allowed_phrases(text: str) -> str:
    lowered = f" {text.lower()} "
    for phrase in ALLOWED_DISCLAIMER_PHRASES:
        lowered = lowered.replace(phrase, "")
    return lowered


def validate_pitch_agent_post(
    *,
    title: str,
    caption: str,
    rows: list[dict[str, Any]] | None = None,
    image_path: str | Path | None = None,
    footer_text: str | None = None,
    source: str | None = None,
    require_image: bool = False,
    require_rows: bool = False,
    require_source: bool = False,
    max_caption_chars: int = 1200,
) -> list[str]:
    """Return a list of validation problems; an empty list means safe to continue."""
    errors: list[str] = []
    title = str(title or "").strip()
    caption = str(caption or "").strip()
    footer = PITCH_AGENT_CARD_FOOTER if footer_text is None else str(footer_text)
    rows = rows or []

    if not title:
        errors.append("title is empty")
    if not caption:
        errors.append("caption is empty")
    if len(caption) > max_caption_chars:
        errors.append(f"caption is too long ({len(caption)} chars > {max_caption_chars})")
    if require_rows and not rows:
        errors.append("card rows are empty")
    if require_source and not str(source or "").strip():
        errors.append("source is missing")
    if require_image:
        if not image_path:
            errors.append("image path is missing")
        elif not Path(image_path).is_file():
            errors.append(f"image path does not exist: {image_path}")

    combined = f"{title}\n{caption}\n{footer}"
    lowered = _without_allowed_phrases(combined)
    for term in FORBIDDEN_PUBLIC_TERMS:
        if term.strip() in lowered:
            errors.append(f"forbidden public wording: {term.strip()}")
    for term in CERTAINTY_TERMS:
        if term in lowered:
            errors.append(f"certainty wording is not allowed: {term}")
    for term in PLACEHOLDER_TERMS:
        if term in combined.lower():
            errors.append(f"placeholder text found: {term}")

    if footer and footer != "BuildWithAbdallah.com" and PITCH_AGENT_CARD_FOOTER not in footer:
        errors.append("Pitch Agent footer/disclaimer is missing or not the approved wording")
    if "Match Estimates" in title or "model estimate" in caption.lower():
        if PITCH_AGENT_CAPTION_DISCLAIMER not in caption:
            errors.append("long Pitch Agent estimate disclaimer is missing")

    return errors


def assert_pitch_agent_post(**kwargs: Any) -> None:
    """Raise ValueError when validation fails."""
    errors = validate_pitch_agent_post(**kwargs)
    if errors:
        raise ValueError("Pitch Agent validation failed: " + "; ".join(errors))
