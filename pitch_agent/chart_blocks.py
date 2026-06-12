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

# ── Match Recap ───────────────────────────────────────────────────────────────
# Each match produces 2 visual rows: score line + prediction/notes line.
# Plus 1 final row for the model record.
_RECAP_LABEL_MAX = 36
_RECAP_PREDICT_MAX = 48


def draw_match_recap_rows(
    ax: Any, matches: list[dict[str, Any]], theme: dict[str, Any], layout: Layout,
) -> None:
    """Match recap rows: score line with result + prediction comparison.

    Each match dict has:
        label       – "Brazil 2-1 Germany" or "Korea Republic 1-1 Czechia (Draw)"
        context     – "Group A" or "Jun 12, Group A"
        prediction  – "Predicted: Home win (55%), 2-1 — Outcome ✓ | Score ✓" or None
        key_factor  – "Elo edge: BRA +280" or "" (shown under prediction)
        no_pred     – True if no prediction exists for this match
    After all matches, one final row for the model record.
    Each match uses 2 layout rows (score + prediction), plus 1 for the record.
    """
    primary = theme.get("primary_text", "#0B1F44")
    secondary = theme.get("secondary_text", "#6B7280")
    accent = theme.get("accent_blue", "#1D6CF2")
    success = theme.get("success_green", "#16A34A")
    danger = theme.get("danger_red", "#DC2626")
    divider = theme.get("divider_color", "#D9E1EC")

    n_matches = len(matches)
    row_idx = 0

    for i, m in enumerate(matches):
        # Row 1: score line + context
        y1 = layout.row_y(row_idx)
        ax.text(layout.left, y1, "•", transform=ax.transAxes, ha="left",
                va="center", fontsize=15, color=accent)
        label = truncate(str(m.get("label", "")), _RECAP_LABEL_MAX)
        ax.text(layout.left + 0.03, y1, label, transform=ax.transAxes, ha="left",
                va="center", fontsize=FS_ROW, color=primary, fontweight="bold")
        context = str(m.get("context", "")).strip()
        if context:
            ax.text(layout.right, y1, truncate(context, 20), transform=ax.transAxes,
                    ha="right", va="center", fontsize=FS_ROW_SECONDARY, color=secondary)
        row_idx += 1

        # Row 2: prediction line or no-prediction note
        y2 = layout.row_y(row_idx)
        prediction = m.get("prediction")
        key_factor = m.get("key_factor", "")
        no_pred = m.get("no_pred", False)

        if prediction:
            # Color the ✓/✗ icons
            pred_text = str(prediction)
            # Split into segments so we can color ✓ green and ✗ red
            # Draw the whole line first as secondary text
            ax.text(layout.left + 0.03, y2, truncate(pred_text, _RECAP_PREDICT_MAX),
                    transform=ax.transAxes, ha="left", va="center",
                    fontsize=FS_ROW_SECONDARY, color=secondary)
        elif no_pred:
            ax.text(layout.left + 0.03, y2, "(No prediction on record)",
                    transform=ax.transAxes, ha="left", va="center",
                    fontsize=FS_ROW_SECONDARY, color=secondary, fontstyle="italic")

        # Optional key factor on a 3rd sub-row (compact, indented)
        if key_factor:
            # Use a slightly lower y position within the row space
            y3 = y2 - layout.row_step * 0.45
            ax.text(layout.left + 0.06, y3, truncate(key_factor, 52),
                    transform=ax.transAxes, ha="left", va="center",
                    fontsize=9, color=secondary)
            row_idx += 1  # Key factor takes a row

        # Divider between matches
        if i < n_matches - 1:
            line_y = layout.row_y(row_idx) - layout.row_step / 2
            ax.plot([layout.left, layout.right], [line_y, line_y],
                    transform=ax.transAxes, color=divider, lw=0.8, zorder=1)

        row_idx += 1

    # Final row: model record
    model_record = None
    for m in matches:
        if m.get("model_record"):
            model_record = m["model_record"]
            break

    y_rec = layout.row_y(row_idx)
    if model_record:
        ax.text(layout.left + 0.03, y_rec, model_record, transform=ax.transAxes,
                ha="left", va="center", fontsize=FS_ROW_SECONDARY,
                color=accent, fontweight="bold")
    else:
        ax.text(layout.left + 0.03, y_rec, "(Model record: 0 journaled predictions graded yet)",
                transform=ax.transAxes, ha="left", va="center",
                fontsize=FS_ROW_SECONDARY, color=secondary, fontstyle="italic")


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


def draw_list_rows(
    ax: Any, rows: list[dict[str, Any]], theme: dict[str, Any], layout: Layout,
) -> None:
    """Generic reusable list rows: blue bullet · label · col_a (blue) · col_b (right).

    Each row dict:
        label   – main left text (required)
        col_a   – middle-right text, rendered in accent blue (optional)
        col_b   – far-right text, rendered in secondary grey (optional)
    """
    primary = theme.get("primary_text", "#0B1F44")
    secondary = theme.get("secondary_text", "#6B7280")
    accent = theme.get("accent_blue", "#1D6CF2")
    divider = theme.get("divider_color", "#D9E1EC")

    _LABEL_MAX = 44
    _COL_A_MAX = 18
    _COL_A_X = 0.62
    n = len(rows)

    for i, row in enumerate(rows):
        y = layout.row_y(i)

        # Blue bullet dot.
        ax.text(layout.left, y, "•", transform=ax.transAxes, ha="left",
                va="center", fontsize=15, color=accent)

        # Primary label.
        label = truncate(str(row.get("label", "")), _LABEL_MAX)
        ax.text(layout.left + 0.03, y, label, transform=ax.transAxes, ha="left",
                va="center", fontsize=FS_ROW, color=primary)

        # Column A — accent blue, left-aligned at 62 %.
        col_a = str(row.get("col_a", "")).strip()
        if col_a:
            ax.text(_COL_A_X, y, truncate(col_a, _COL_A_MAX), transform=ax.transAxes,
                    ha="left", va="center", fontsize=FS_ROW_SECONDARY,
                    color=accent, fontweight="bold")

        # Column B — secondary grey, right-aligned.
        col_b = str(row.get("col_b", "")).strip()
        if col_b:
            ax.text(layout.right, y, col_b, transform=ax.transAxes, ha="right",
                    va="center", fontsize=FS_ROW_SECONDARY, color=secondary)

        # Divider line between rows (not after the last row).
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
