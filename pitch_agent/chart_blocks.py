"""Deterministic content-block renderers for The Pitch Agent template engine.

Each block draws onto the shared full-figure axes (fraction coordinates) using a
:class:`pitch_agent.brand_template.Layout` for fixed row placement. No random
placement, no AI layout — same inputs always produce the same visual.
"""
from __future__ import annotations

from typing import Any

from pitch_agent.brand_template import (
    FS_RANK,
    FS_ROW,
    FS_ROW_SECONDARY,
    FS_STAT_LABEL,
    FS_STAT_NUMBER,
    Layout,
    truncate,
)

# Fixed column geometry (axes fraction) shared by ranked rows.
_BAR_X0 = 0.58
_BAR_X1 = 0.86
_SCORE_X = 0.94
_NAME_MAX_CHARS = 34
_FIXTURE_LABEL_MAX_CHARS = 36


def _bar_height(layout: Layout) -> float:
    return min(0.34 * layout.row_step, 0.05)


def _draw_track_bar(
    ax: Any, y: float, frac: float, height: float,
    track_color: str, fill_color: str,
) -> None:
    """Draw a horizontal track with a proportional accent fill."""
    from matplotlib.patches import Rectangle

    frac = max(0.0, min(1.0, frac))
    ax.add_patch(Rectangle(
        (_BAR_X0, y - height / 2), _BAR_X1 - _BAR_X0, height,
        transform=ax.transAxes, facecolor=track_color, edgecolor="none", zorder=2,
    ))
    if frac > 0:
        ax.add_patch(Rectangle(
            (_BAR_X0, y - height / 2), (_BAR_X1 - _BAR_X0) * frac, height,
            transform=ax.transAxes, facecolor=fill_color, edgecolor="none", zorder=3,
        ))


def draw_leaderboard_rows(
    ax: Any, rows: list[dict[str, Any]], theme: dict[str, Any], layout: Layout,
) -> None:
    """Ranked rows: rank, player (+ position tag), proportional bar, score."""
    primary = theme.get("primary_text", "#0B1F44")
    secondary = theme.get("secondary_text", "#6B7280")
    accent = theme.get("accent_blue", "#1D6CF2")
    divider = theme.get("divider_color", "#D9E1EC")

    scores = [float(r.get("score", 0) or 0) for r in rows]
    max_score = max(scores) if scores else 1.0
    height = _bar_height(layout)

    for i, row in enumerate(rows):
        y = layout.row_y(i)
        rank = row.get("rank", i + 1)
        ax.text(layout.left, y, str(rank), transform=ax.transAxes,
                ha="left", va="center", fontsize=FS_RANK, fontweight="bold",
                color=accent)
        pos = (row.get("position") or "").upper()
        tag = f"   ·  {pos}" if pos in ("FWD", "MID", "DEF", "GK") else ""
        name = truncate(row.get("player_name", ""), _NAME_MAX_CHARS)
        ax.text(layout.left + 0.04, y, f"{name}{tag}", transform=ax.transAxes,
                ha="left", va="center", fontsize=FS_ROW, color=primary)

        score = float(row.get("score", 0) or 0)
        _draw_track_bar(ax, y, score / max_score if max_score else 0,
                        height, divider, accent)
        ax.text(_SCORE_X, y, f"{score:.1f}", transform=ax.transAxes,
                ha="right", va="center", fontsize=FS_ROW, fontweight="bold",
                color=primary)


def draw_position_rows(
    ax: Any, rows: list[dict[str, Any]], theme: dict[str, Any], layout: Layout,
) -> None:
    """Ranked rows with an emphasised position chip per player."""
    primary = theme.get("primary_text", "#0B1F44")
    accent = theme.get("accent_blue", "#1D6CF2")
    divider = theme.get("divider_color", "#D9E1EC")
    bg = theme.get("background_color", "#F7F9FC")

    scores = [float(r.get("score", 0) or 0) for r in rows]
    max_score = max(scores) if scores else 1.0
    height = _bar_height(layout)

    from matplotlib.patches import FancyBboxPatch

    for i, row in enumerate(rows):
        y = layout.row_y(i)
        ax.text(layout.left, y, str(row.get("rank", i + 1)), transform=ax.transAxes,
                ha="left", va="center", fontsize=FS_RANK, fontweight="bold",
                color=accent)
        # Position chip.
        pos = (row.get("position") or "").upper() or "—"
        chip_x, chip_w = layout.left + 0.035, 0.05
        chip_h = min(0.5 * layout.row_step, 0.045)
        ax.add_patch(FancyBboxPatch(
            (chip_x, y - chip_h / 2), chip_w, chip_h,
            boxstyle="round,pad=0.004,rounding_size=0.01",
            transform=ax.transAxes, facecolor=accent, edgecolor="none", zorder=3,
        ))
        ax.text(chip_x + chip_w / 2, y, pos, transform=ax.transAxes,
                ha="center", va="center", fontsize=9, fontweight="bold",
                color=bg, zorder=4)

        name = truncate(row.get("player_name", ""), _NAME_MAX_CHARS - 6)
        ax.text(chip_x + chip_w + 0.02, y, name, transform=ax.transAxes,
                ha="left", va="center", fontsize=FS_ROW, color=primary)

        score = float(row.get("score", 0) or 0)
        _draw_track_bar(ax, y, score / max_score if max_score else 0,
                        height, divider, accent)
        ax.text(_SCORE_X, y, f"{score:.1f}", transform=ax.transAxes,
                ha="right", va="center", fontsize=FS_ROW, fontweight="bold",
                color=primary)


def draw_fixture_rows(
    ax: Any, fixtures: list[dict[str, Any]], theme: dict[str, Any], layout: Layout,
) -> None:
    """Fixture rows: blue bullet, match label, group/stage in blue, date right."""
    primary = theme.get("primary_text", "#0B1F44")
    secondary = theme.get("secondary_text", "#6B7280")
    accent = theme.get("accent_blue", "#1D6CF2")
    divider = theme.get("divider_color", "#D9E1EC")

    n = len(fixtures)
    for i, fx in enumerate(fixtures):
        y = layout.row_y(i)
        label = truncate(fx.get("match_label") or "TBD", _FIXTURE_LABEL_MAX_CHARS)
        ax.text(layout.left, y, "•", transform=ax.transAxes, ha="left",
                va="center", fontsize=15, color=accent)
        ax.text(layout.left + 0.03, y, label, transform=ax.transAxes, ha="left",
                va="center", fontsize=FS_ROW, color=primary)

        group = str(fx.get("group_name") or "").replace("_", " ").title().strip()
        stage = str(fx.get("stage") or "").replace("_", " ").title().strip()
        context = group or stage
        if context:
            ax.text(0.62, y, truncate(context, 16), transform=ax.transAxes,
                    ha="left", va="center", fontsize=FS_ROW_SECONDARY,
                    color=accent, fontweight="bold")
        date = str(fx.get("date") or "")[:10]
        if date:
            ax.text(layout.right, y, date, transform=ax.transAxes, ha="right",
                    va="center", fontsize=FS_ROW_SECONDARY, color=secondary)
        if i < n - 1:
            line_y = y - layout.row_step / 2
            ax.plot([layout.left, layout.right], [line_y, line_y],
                    transform=ax.transAxes, color=divider, lw=0.8, zorder=1)


def draw_player_spotlight(
    ax: Any, player: dict[str, Any], theme: dict[str, Any], layout: Layout,
) -> None:
    """A single-player card: name, team/position, big score, key reason."""
    primary = theme.get("primary_text", "#0B1F44")
    secondary = theme.get("secondary_text", "#6B7280")
    accent = theme.get("accent_blue", "#1D6CF2")

    top = layout.content_top
    name = truncate(player.get("player_name", ""), 28)
    ax.text(layout.left, top - 0.06, name, transform=ax.transAxes, ha="left",
            va="top", fontsize=26, fontweight="bold", color=primary)

    pos = (player.get("position") or "").upper()
    team = player.get("team_name", "")
    meta = " · ".join(part for part in (team, pos) if part)
    if meta:
        ax.text(layout.left, top - 0.20, meta, transform=ax.transAxes, ha="left",
                va="top", fontsize=13, color=secondary)

    score = float(player.get("score", 0) or 0)
    ax.text(layout.right, top - 0.04, f"{score:.1f}", transform=ax.transAxes,
            ha="right", va="top", fontsize=FS_STAT_NUMBER, fontweight="bold",
            color=accent)
    ax.text(layout.right, top - 0.30, "Form Index", transform=ax.transAxes,
            ha="right", va="top", fontsize=12, color=secondary)

    reason = player.get("key_reason") or ""
    if reason:
        ax.text(layout.left, layout.content_bottom + 0.10, truncate(reason, 70),
                transform=ax.transAxes, ha="left", va="bottom", fontsize=13,
                color=primary)


def draw_stat_card(
    ax: Any, stat: dict[str, Any], theme: dict[str, Any], layout: Layout,
) -> None:
    """A big-number stat card: value, label, optional sub-line."""
    primary = theme.get("primary_text", "#0B1F44")
    secondary = theme.get("secondary_text", "#6B7280")
    accent = theme.get("accent_blue", "#1D6CF2")

    mid = (layout.content_top + layout.content_bottom) / 2
    value = str(stat.get("value", ""))
    label = truncate(str(stat.get("label", "")), 48)
    sub = truncate(str(stat.get("sub", "")), 60)

    ax.text(0.5, mid + 0.10, value, transform=ax.transAxes, ha="center",
            va="center", fontsize=FS_STAT_NUMBER, fontweight="bold", color=accent)
    if label:
        ax.text(0.5, mid - 0.06, label, transform=ax.transAxes, ha="center",
                va="center", fontsize=FS_STAT_LABEL, fontweight="bold", color=primary)
    if sub:
        ax.text(0.5, mid - 0.14, sub, transform=ax.transAxes, ha="center",
                va="center", fontsize=11, color=secondary)
