"""Reusable chart themes for The Pitch Agent template engine.

A *theme* is a flat dict of colour/watermark values. The default theme,
``buildwithabdallah_light``, is the BuildWithAbdallah brand palette. Themes can
be overridden per-key by a ``theme:`` block in ``config/pitch_agent.yaml``.
"""
from __future__ import annotations

from typing import Any

DEFAULT_THEME_NAME = "buildwithabdallah_light"

# Built-in theme palettes. Config ``theme:`` values override these per key.
_THEMES: dict[str, dict[str, Any]] = {
    "buildwithabdallah_light": {
        "background_color": "#F7F9FC",
        "primary_text": "#0B1F44",
        "secondary_text": "#6B7280",
        "accent_blue": "#1D6CF2",
        "divider_color": "#D9E1EC",
        "watermark_text": "A",
        "watermark_alpha": 0.08,
    },
    # Legacy dark palette, opt-in via brand.chart_theme: "dark".
    "dark": {
        "background_color": "#0f172a",
        "primary_text": "#e2e8f0",
        "secondary_text": "#94a3b8",
        "accent_blue": "#2563eb",
        "divider_color": "#1e293b",
        "watermark_text": "A",
        "watermark_alpha": 0.06,
    },
}


def available_themes() -> tuple[str, ...]:
    """Return the names of the built-in themes."""
    return tuple(_THEMES)


def load_theme(name: str | None = None, config_path: str | None = None) -> dict[str, Any]:
    """Return the resolved theme palette.

    The theme name defaults to ``brand.chart_theme`` (then
    ``buildwithabdallah_light``). The named theme's defaults are then overridden
    by any values in the config ``theme:`` block.
    """
    from pitch_agent.config import load_brand, read_settings

    configured = load_brand(config_path).get("chart_theme") or DEFAULT_THEME_NAME
    if name is None:
        name = configured
    base = dict(_THEMES.get(name, _THEMES[DEFAULT_THEME_NAME]))

    # The config ``theme:`` block customises the *configured* theme. An
    # explicitly requested different theme keeps its built-in palette.
    if name == configured:
        settings = read_settings(config_path)
        overrides = settings.get("theme", {}) if isinstance(settings, dict) else {}
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                if value is not None and value != "":
                    base[key] = value

    try:
        base["watermark_alpha"] = float(base.get("watermark_alpha", 0.08))
    except (TypeError, ValueError):
        base["watermark_alpha"] = 0.08

    base["name"] = name
    return base
