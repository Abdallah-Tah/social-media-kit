"""Lightweight safety checks for generated Pitch Agent content.

The Pitch Agent may publish educational/data-based prediction language, but it
must never drift into betting, odds, certainty, or financial-advice language.
These checks are dependency-free so they can run on Raspberry Pi/server jobs.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pitch_agent import (
    PITCH_AGENT_CAPTION_DISCLAIMER,
    PITCH_AGENT_CARD_FOOTER,
    PITCH_AGENT_ESTIMATE_FOOTER,
)

PLACEHOLDER_TERMS = (
    "[add setup steps here]",
    "[first step]",
    "[add content here",
    "[add your analysis here]",
    "[feature]",
    "[value]",
)

# Do not include generic "prediction" / "predicted" here. Public educational
# prediction wording is allowed when paired with the required disclaimers.
FORBIDDEN_PUBLIC_TERMS = (
    "betting",
    "betting advice",
    "odds",
    "gamble",
    "gambling",
    "sportsbook",
    "wager",
    "bet on",
    "risk-free",
    "profit from betting",
    "profit from predictions",
    "bet",
    "guaranteed win",
    "sure win",
    "lock",
    "betting pick",
    "gambling pick",
    "pick",
)

CERTAINTY_TERMS = (
    "guaranteed",
    "sure win",
    "cannot lose",
    "will definitely",
)

APPROVED_PITCH_AGENT_FOOTERS = (
    PITCH_AGENT_CARD_FOOTER,
    PITCH_AGENT_ESTIMATE_FOOTER,
)

# Required disclaimers contain "Not betting advice". Treat that exact phrase as
# allowed while still blocking betting-advice language without the negation.
ALLOWED_DISCLAIMER_PHRASES = (
    "not betting advice",
    "not guarantees",
    "educational predictions, not betting advice",
    "data-based estimates, not betting advice",
)

SAFE_PREDICTION_PHRASES = (
    "data-based prediction",
    "data-based predictions",
    "educational prediction",
    "educational predictions",
    "model prediction",
    "model predictions",
    "predicted score",
    "ai match prediction",
    "ai match predictions",
)


def _contains_forbidden_term(text: str, term: str) -> bool:
    """Return True when *term* appears as a full word/phrase.

    This avoids noisy substring matches: ``pick`` does not match ``picking`` or
    ``pickle``, while multi-word phrases such as ``bet on`` still match.
    """
    term = term.strip().lower()
    if not term:
        return False
    pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
    return re.search(pattern, text) is not None


def _without_allowed_phrases(text: str) -> str:
    lowered = f" {text.lower()} "
    for phrase in ALLOWED_DISCLAIMER_PHRASES + SAFE_PREDICTION_PHRASES:
        lowered = re.sub(
            r"(?<!\w)" + re.escape(phrase) + r"(?!\w)",
            " ",
            lowered,
        )
    return lowered


def _is_prediction_content(title: str, caption: str) -> bool:
    lowered = f" {title.lower()}\n{caption.lower()} "
    return any(
        _contains_forbidden_term(lowered, word)
        for word in ("prediction", "predictions", "predicted", "model estimate", "data-based estimate")
    )


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
    max_caption_chars: int = 1400,
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
        if _contains_forbidden_term(lowered, term):
            errors.append(f"forbidden public wording: {term.strip()}")
    for term in CERTAINTY_TERMS:
        if _contains_forbidden_term(lowered, term):
            errors.append(f"certainty wording is not allowed: {term}")
    for term in PLACEHOLDER_TERMS:
        if term in combined.lower():
            errors.append(f"placeholder text found: {term}")

    is_pitch_footer = footer and footer != "BuildWithAbdallah.com"
    if is_pitch_footer and footer not in APPROVED_PITCH_AGENT_FOOTERS:
        errors.append("Pitch Agent footer/disclaimer is missing or not the approved wording")

    if _is_prediction_content(title, caption):
        if footer not in APPROVED_PITCH_AGENT_FOOTERS:
            errors.append("Pitch Agent prediction footer/disclaimer is missing")
        if PITCH_AGENT_CAPTION_DISCLAIMER not in caption:
            errors.append("long Pitch Agent prediction disclaimer is missing")

    return errors


def assert_pitch_agent_post(**kwargs: Any) -> None:
    """Raise ValueError when validation fails."""
    errors = validate_pitch_agent_post(**kwargs)
    if errors:
        raise ValueError("Pitch Agent validation failed: " + "; ".join(errors))
