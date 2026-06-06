"""Trademark and affiliation disclaimers.

The Pitch Agent is an independent analytics project and is not affiliated
with FIFA, FIFA World Cup, or any official tournament organizer.
"""

from pitch_agent import (
    FORM_INDEX_PUBLIC_EXPLANATION,
    MODEL_VERSION,
    MODEL_VERSION_LABEL,
    TRADEMARK_DISCLAIMER,
)


def get_disclaimer() -> str:
    """Return the full trademark and affiliation disclaimer."""
    return TRADEMARK_DISCLAIMER


def get_chart_footer() -> str:
    """Return the chart footer string with the required disclaimer.

    Sourced from the brand config so it carries the parent brand, e.g.
    ``The Pitch Agent by BuildWithAbdallah | Independent analytics | Not
    affiliated with FIFA``.
    """
    from pitch_agent.config import load_brand
    return load_brand().get("footer", "")


def get_methodology() -> str:
    """Return the public Form Index methodology text for the website page.

    This is the source of truth for ``/builds/the-pitch-agent/form-index-methodology``.
    """
    return "\n".join([
        MODEL_VERSION_LABEL,
        "",
        FORM_INDEX_PUBLIC_EXPLANATION,
        "",
        "What it uses: goals, assists, minutes played, cards, clean sheet impact, "
        "and team result.",
        "What it does not do: it is not betting, it is not a prediction, and it is "
        "not affiliated with FIFA.",
        f"Current version: {MODEL_VERSION_LABEL} ({MODEL_VERSION}). This version is "
        "frozen so scores stay comparable day to day.",
        "Planned upgrade: Form Index v2.0 will add richer performance stats once a "
        "live data source is connected.",
        "",
        TRADEMARK_DISCLAIMER,
    ])