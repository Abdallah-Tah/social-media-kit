"""Deprecated Pitch Agent card renderer compatibility wrapper.

Canonical renderer: ``pitch_agent/templates/list_card.html`` driven by
``pitch_agent/html_render.py`` via ``pitch_agent.brand_template.generate_list_card_html``.
This wrapper keeps old imports working without maintaining a second competing
Pillow layout.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pitch_agent import PITCH_AGENT_CARD_FOOTER
from pitch_agent.brand_template import generate_list_card_html
from pitch_agent.charts import _fixtures_to_card_rows

SIZES = {
    "landscape": (1600, 1000),
    "square": (1080, 1080),
    "portrait": (1080, 1920),
}


class BrandedCardRenderer:
    """Backward-compatible wrapper around the canonical HTML card renderer."""

    def __init__(self, mode: str = "fan_mode", size: str = "landscape"):
        self.mode = mode
        self.size = size
        self.W, self.H = SIZES.get(size, SIZES["landscape"])

    def render(self, matches: list[dict[str, Any]], out_path: str, title: str = "Upcoming World Cup Matches"):
        """Render a branded fixture card using the canonical HTML template."""
        rows = _fixtures_to_card_rows(matches[:12])
        subtitle = "World Cup 2026 • Fixture data • football-data.org"
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        return generate_list_card_html(
            title,
            subtitle,
            rows,
            out_path,
            footer_text=PITCH_AGENT_CARD_FOOTER,
            fourk=self.size == "landscape-4k",
        )
