"""Deterministic, reusable chart template engine for The Pitch Agent.

Pitch Agent visuals are template-driven, not AI-designed: an AI may write the
narrative text, but every chart's layout and styling is produced here in code so
all visuals share one BuildWithAbdallah brand system.

The engine draws on a single full-figure axes in fraction coordinates (0..1).
Layout is fully deterministic — fixed margins, a fixed-height header/title block,
a fixed footer position, fixed row spacing, and fixed font sizes — so the same
inputs always produce the same image dimensions. Content is rendered by the
block renderers in :mod:`pitch_agent.chart_blocks`.
"""
from __future__ import annotations

import os
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pitch_agent.chart_themes import load_theme

DEFAULT_CHART_DIR = Path("artifacts") / "pitch_agent" / "charts"

# ── Deterministic layout constants ───────────────────────────────────────────
DPI = 150
FIG_WIDTH_IN = 10.0
HEADER_IN = 2.0        # reserved top band: logo + title + subtitle + divider
FOOTER_IN = 0.8        # reserved bottom band: footer line
ROW_IN = 0.5           # per content row
MARGIN_LEFT = 0.06
MARGIN_RIGHT = 0.94

# Fixed inch offsets (from top) for header elements; converted to a fraction
# using the actual figure height so physical placement is stable.
LOGO_TOP_IN = 0.30
HEADER_TEXT_IN = 0.55
TITLE_IN = 1.10
SUBTITLE_IN = 1.52
DIVIDER_IN = 1.80
FOOTER_FROM_BOTTOM_IN = 0.30

# Fixed font sizes.
FS_HEADER = 13
FS_TITLE = 19
FS_SUBTITLE = 10
FS_FOOTER = 8
FS_ROW = 12
FS_ROW_SECONDARY = 10
FS_RANK = 11
FS_WATERMARK = 330
FS_STAT_NUMBER = 66
FS_STAT_LABEL = 14


@dataclass(frozen=True)
class Layout:
    """Deterministic content geometry derived from the figure height."""

    height_in: float
    n_rows: int
    left: float = MARGIN_LEFT
    right: float = MARGIN_RIGHT

    @property
    def content_top(self) -> float:
        return 1.0 - HEADER_IN / self.height_in

    @property
    def content_bottom(self) -> float:
        return FOOTER_IN / self.height_in

    @property
    def row_step(self) -> float:
        return (self.content_top - self.content_bottom) / max(self.n_rows, 1)

    def row_y(self, index: int) -> float:
        """Vertical centre (axes fraction) of content row ``index`` (0-based)."""
        return self.content_top - (index + 0.5) * self.row_step


def figure_size_for(n_rows: int) -> tuple[float, float]:
    """Return the deterministic ``(width_in, height_in)`` for ``n_rows`` rows."""
    rows = max(int(n_rows), 1)
    height = HEADER_IN + rows * ROW_IN + FOOTER_IN
    return (FIG_WIDTH_IN, round(height, 3))


def load_brand_config(config_path: str | None = None) -> dict[str, str]:
    """Return the brand identity config (name, parent_brand, logo_path, footer)."""
    from pitch_agent.config import load_brand
    return dict(load_brand(config_path))


# ── helpers ──────────────────────────────────────────────────────────────────

def _ensure_matplotlib():
    os.environ.setdefault(
        "MPLCONFIGDIR",
        str(Path(tempfile.gettempdir()) / "pitch_agent_matplotlib"),
    )
    warnings.filterwarnings("ignore", message="Unable to import Axes3D.*")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _height_in(ax: Any) -> float:
    return float(ax.figure.get_size_inches()[1])


def _y_from_top(ax: Any, inches: float) -> float:
    return 1.0 - inches / _height_in(ax)


def _y_from_bottom(ax: Any, inches: float) -> float:
    return inches / _height_in(ax)


def truncate(text: str, max_chars: int) -> str:
    """Deterministically truncate text with an ellipsis when too long."""
    text = str(text or "")
    if max_chars <= 1 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


# ── Template primitives (spec signatures) ────────────────────────────────────

def draw_background(ax: Any, theme: dict[str, Any]) -> None:
    """Fill the figure and axes with the theme background colour."""
    color = theme.get("background_color", "#F7F9FC")
    ax.figure.patch.set_facecolor(color)
    ax.set_facecolor(color)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")


def draw_watermark(ax: Any, theme: dict[str, Any]) -> None:
    """Draw the large, subtle watermark letter centred behind the content."""
    text = str(theme.get("watermark_text", "A")).strip()
    if not text:
        return
    ax.text(
        0.5, 0.45, text, transform=ax.transAxes, ha="center", va="center",
        fontsize=FS_WATERMARK, fontweight="bold",
        color=theme.get("accent_blue", "#1D6CF2"),
        alpha=float(theme.get("watermark_alpha", 0.08)), zorder=0,
    )


def draw_accent_shapes(ax: Any, theme: dict[str, Any]) -> None:
    """Draw blue decorative dots in the corners."""
    accent = theme.get("accent_blue", "#1D6CF2")
    ax.scatter(
        [0.90, 0.935, 0.97], [0.95, 0.93, 0.95], s=[70, 40, 70],
        color=accent, alpha=0.9, zorder=2, transform=ax.transAxes, clip_on=False,
    )
    ax.scatter(
        [0.035], [0.06], s=50, color=accent, alpha=0.8, zorder=2,
        transform=ax.transAxes, clip_on=False,
    )


def draw_header(ax: Any, brand: dict[str, Any], theme: dict[str, Any] | None = None) -> None:
    """Place the logo top-left, or a text brand header when no logo is available."""
    theme = theme or {}
    accent = theme.get("accent_blue", "#1D6CF2")
    secondary = theme.get("secondary_text", "#6B7280")
    logo_path = brand.get("logo_path", "")

    if logo_path:
        try:
            import matplotlib.image as mpimg
            from matplotlib.offsetbox import OffsetImage, AnnotationBbox

            img = mpimg.imread(logo_path)
            zoom = min(1.0, 90.0 / max(1, img.shape[0]))
            box = OffsetImage(img, zoom=zoom)
            anchor = AnnotationBbox(
                box, (MARGIN_LEFT, _y_from_top(ax, LOGO_TOP_IN)),
                xycoords="axes fraction", frameon=False,
                box_alignment=(0.0, 1.0), zorder=5,
            )
            ax.add_artist(anchor)
            return
        except Exception:  # noqa: BLE001 — a bad/missing logo must never crash a chart
            pass

    # Text-only brand header fallback.
    ax.text(
        MARGIN_LEFT, _y_from_top(ax, HEADER_TEXT_IN),
        brand.get("parent_brand", "BuildWithAbdallah"),
        transform=ax.transAxes, ha="left", va="top",
        fontsize=FS_HEADER, fontweight="bold", color=accent, zorder=5,
    )
    ax.text(
        MARGIN_LEFT + 0.16, _y_from_top(ax, HEADER_TEXT_IN),
        brand.get("name", "The Pitch Agent"),
        transform=ax.transAxes, ha="left", va="top",
        fontsize=FS_HEADER - 2, color=secondary, zorder=5,
    )


def draw_title_block(ax: Any, title: str, subtitle: str, theme: dict[str, Any]) -> None:
    """Draw the fixed-height title + subtitle block and the header divider."""
    primary = theme.get("primary_text", "#0B1F44")
    secondary = theme.get("secondary_text", "#6B7280")
    divider = theme.get("divider_color", "#D9E1EC")

    if title:
        ax.text(
            MARGIN_LEFT, _y_from_top(ax, TITLE_IN), truncate(title, 60),
            transform=ax.transAxes, ha="left", va="top",
            fontsize=FS_TITLE, fontweight="bold", color=primary, zorder=5,
        )
    if subtitle:
        ax.text(
            MARGIN_LEFT, _y_from_top(ax, SUBTITLE_IN), truncate(subtitle, 80),
            transform=ax.transAxes, ha="left", va="top",
            fontsize=FS_SUBTITLE, color=secondary, zorder=5,
        )
    divider_y = _y_from_top(ax, DIVIDER_IN)
    ax.plot(
        [MARGIN_LEFT, MARGIN_RIGHT], [divider_y, divider_y],
        transform=ax.transAxes, color=divider, lw=1.2, zorder=1,
    )


def draw_footer(ax: Any, brand: dict[str, Any], theme: dict[str, Any]) -> None:
    """Draw the shared branded footer at the fixed bottom position."""
    text = brand.get("footer", "")
    if not text:
        return
    ax.text(
        0.5, _y_from_bottom(ax, FOOTER_FROM_BOTTOM_IN), text,
        transform=ax.transAxes, ha="center", va="center",
        fontsize=FS_FOOTER, style="italic",
        color=theme.get("secondary_text", "#6B7280"), zorder=5,
    )


# ── Composition + save ───────────────────────────────────────────────────────

def create_canvas(
    n_rows: int,
    brand: dict[str, Any],
    theme: dict[str, Any],
    title: str = "",
    subtitle: str = "",
    footer_text: str | None = None,
) -> tuple[Any, Any, Layout]:
    """Build a branded figure; return ``(fig, ax, layout)``.

    The single full-figure axes already carries background, watermark, accent
    shapes, header, title block, and footer. Content block renderers draw on the
    same ``ax`` using ``layout`` for deterministic row placement.
    """
    plt = _ensure_matplotlib()
    width, height = figure_size_for(n_rows)
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([0, 0, 1, 1])

    draw_background(ax, theme)
    draw_watermark(ax, theme)
    draw_accent_shapes(ax, theme)
    draw_header(ax, brand, theme)
    draw_title_block(ax, title, subtitle, theme)

    footer_brand = dict(brand)
    if footer_text is not None:
        footer_brand["footer"] = footer_text
    draw_footer(ax, footer_brand, theme)

    return fig, ax, Layout(height_in=height, n_rows=n_rows)


def generate_list_card(
    title: str,
    subtitle: str,
    rows: list[dict[str, Any]],
    output_path: str,
    *,
    footer_text: str | None = None,
    config_path: str | None = None,
    theme_name: str | None = None,
) -> str:
    """Render a branded list-card image and save it to *output_path*.

    This is the single public entry point for any post that follows the standard
    template layout: logo → title → subtitle → divider → N bullet rows → footer.

    Each dict in *rows* may contain:
        label  – main left text            (required)
        col_a  – middle-right accent text  (optional, rendered in blue)
        col_b  – far-right secondary text  (optional, rendered in grey)

    Returns the resolved absolute path of the saved file.

    Example::

        generate_list_card(
            title="Upcoming World Cup Fixtures",
            subtitle="World Cup 2026 • Fixture data • football-data.org",
            rows=[
                {"label": "Mexico vs South Africa", "col_a": "Group A", "col_b": "2026-06-11"},
                {"label": "Korea Republic vs Czechia", "col_a": "Group A", "col_b": "2026-06-12"},
            ],
            output_path="artifacts/fixtures.png",
        )
    """
    from pitch_agent.chart_blocks import draw_list_rows
    from pitch_agent.chart_themes import load_theme

    brand = load_brand_config(config_path)
    theme = load_theme(theme_name, config_path)

    fig, ax, layout = create_canvas(
        n_rows=max(len(rows), 1),
        brand=brand,
        theme=theme,
        title=title,
        subtitle=subtitle,
        footer_text=footer_text,
    )
    draw_list_rows(ax, rows, theme, layout)
    return save_chart(fig, output_path, theme)


def save_chart(fig: Any, output_path: str, theme: dict[str, Any]) -> str:
    """Save the figure with the theme background and close it."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib.pyplot as plt

    fig.savefig(
        output, dpi=DPI,
        facecolor=theme.get("background_color", "#F7F9FC"), edgecolor="none",
    )
    plt.close(fig)
    return str(output)
