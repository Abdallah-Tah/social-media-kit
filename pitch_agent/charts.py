"""Chart rendering for The Pitch Agent.

Every chart is built from the shared BuildWithAbdallah light brand template
(:mod:`pitch_agent.brand_template`) so all visuals belong to one brand system
rather than looking like generic matplotlib output. The legacy dark style is
available by setting ``brand.chart_theme: "dark"`` in ``config/pitch_agent.yaml``.
"""
from __future__ import annotations

from typing import Any

from pitch_agent import MODEL_VERSION_LABEL, PITCH_AGENT_CARD_FOOTER, brand_template, chart_blocks
from pitch_agent.brand_template import DEFAULT_CHART_DIR
from pitch_agent.chart_themes import load_theme
from pitch_agent.transparency import get_chart_footer

DEMO_DATA_NOTE = "Demo data only"

# Position tags shown next to player names (no crowded multi-colour legend).
POSITION_TAGS = ("FWD", "MID", "DEF", "GK")


def _load_brand_and_theme(footer: str | None = None) -> tuple[dict, dict]:
    """Load the brand identity and theme palette, with the footer injected.

    ``get_chart_footer()`` is the single source of truth for the footer string,
    so every renderer routes through it (keeping all chart types in sync).
    """
    brand = brand_template.load_brand_config()
    brand["footer"] = get_chart_footer() if footer is None else footer
    theme = load_theme()
    return brand, theme


def build_chart_title(
    scope: str = "daily",
    position: str | None = None,
    count: int = 10,
) -> str:
    """Build the branded chart title, e.g. ``Daily Form Index — Top 10``."""
    if position:
        pos = position.upper()
        return f"Top {pos} Form Index — Top {count}"
    labels = {
        "daily": "Daily Form Index",
        "player_match": "Match Form Index",
        "tournament": "Tournament Form Index",
    }
    return f"{labels.get(scope, 'Form Index Leaderboard')} — Top {count}"


def build_chart_subtitle(
    provider_name: str = "",
    data_quality: str = "basic",
    as_of_date: str = "",
    model_version_label: str = MODEL_VERSION_LABEL,
) -> str:
    """Build the chart subtitle, e.g. ``<date> • Form Index v1.0 Lite • Basic data``.

    When the provider is the sample CSV source, append ``Demo data only`` so the
    chart can never be mistaken for live tournament data.
    """
    parts: list[str] = []
    pretty_date = _format_date(as_of_date)
    if pretty_date:
        parts.append(pretty_date)
    parts.append(model_version_label)
    quality = (data_quality or "basic").strip() or "basic"
    parts.append(f"{quality.capitalize()} data")
    if _is_demo_provider(provider_name):
        parts.append(DEMO_DATA_NOTE)
    return " • ".join(parts)


def _is_demo_provider(provider_name: str) -> bool:
    providers = (provider_name or "").lower()
    return "csv" in [p.strip() for p in providers.split(",") if p.strip()]


def _format_date(value: str) -> str:
    """Format an ISO date (YYYY-MM-DD) as 'Month D, YYYY'; pass through on failure."""
    value = (value or "").strip()
    if not value:
        return ""
    from datetime import datetime
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        return value


def render_leaderboard_chart(
    data: list[dict[str, Any]],
    output_path: str | None = None,
    position: str | None = None,
    title: str | None = None,
    scope: str = "daily",
    provider_name: str = "",
    data_quality: str = "basic",
    as_of_date: str = "",
    model_version_label: str = MODEL_VERSION_LABEL,
) -> str:
    """Render a horizontal bar chart of Form Index scores.

    Parameters
    ----------
    data : list of dict
        Each dict must have: player_name, score, position (optional).
    output_path : str or None
        Where to save the PNG.
    position : str or None
        If set, filters title to the position.
    title : str or None
        Custom title.  When omitted, a branded title is built from ``scope``.
    scope : str
        Leaderboard scope, used to build the default title.
    provider_name : str
        Source provider; ``csv`` adds a ``Demo data only`` note to the subtitle.
    data_quality : str
        Data quality level shown in the subtitle (e.g. ``basic``).
    as_of_date : str
        Optional ISO date shown in the subtitle.
    model_version_label : str
        Frozen model label shown in the subtitle (``Form Index v1.0 Lite``).

    Returns
    -------
    str
        The output path of the rendered chart.
    """
    if output_path is None:
        suffix = f"_{position.lower()}" if position else ""
        output_path = str(DEFAULT_CHART_DIR / f"leaderboard{suffix}.png")

    brand, theme = _load_brand_and_theme()
    rows = list(data[:20])
    if title is None:
        title = build_chart_title(scope=scope, position=position, count=len(rows))
    subtitle = build_chart_subtitle(
        provider_name=provider_name,
        data_quality=data_quality,
        as_of_date=as_of_date,
        model_version_label=model_version_label,
    )

    fig, ax, layout = brand_template.create_canvas(
        len(rows), brand, theme, title=title, subtitle=subtitle,
    )
    if not rows:
        _draw_empty(ax, theme, "No data available")
    elif position:
        chart_blocks.draw_position_rows(ax, rows, theme, layout)
    else:
        chart_blocks.draw_leaderboard_rows(ax, rows, theme, layout)
    return brand_template.save_chart(fig, output_path, theme)


def _fixtures_to_card_rows(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map fixture dicts to the list-card ``{label, col_a, col_b}`` schema.

    Mirrors :func:`pitch_agent.chart_blocks.draw_fixture_rows`: match label left,
    group/stage as the blue accent value, date as the muted value.
    """
    from pitch_agent.fixtures import normalize_stage_label

    rows: list[dict[str, Any]] = []
    for fx in fixtures:
        context = (normalize_stage_label(fx.get("group_name"))
                   or normalize_stage_label(fx.get("stage")))
        rows.append({
            "label": str(fx.get("match_label") or "TBD"),
            "col_a": context,
            "col_b": str(fx.get("date") or "")[:10],
        })
    return rows


def render_fixtures_chart(
    fixtures: list[dict[str, Any]],
    output_path: str | None = None,
    limit: int = 10,
    title: str = "Upcoming World Cup Matches",
    subtitle: str = "World Cup 2026 • Fixture data • football-data.org",
) -> str:
    """Render a branded list of upcoming fixtures as a PNG.

    Uses the HTML/CSS + headless-Chromium renderer (real logo, sharper type). If
    Playwright/Chromium is unavailable the matplotlib template is used as a
    fallback, so chart generation never crashes the posting pipeline.
    """
    if output_path is None:
        output_path = str(DEFAULT_CHART_DIR / "fixtures.png")

    rows = list(fixtures[:limit])
    footer = get_chart_footer()
    if rows:
        try:
            return brand_template.generate_list_card_html(
                title, subtitle, _fixtures_to_card_rows(rows), output_path,
                footer_text=footer,
            )
        except Exception as exc:  # noqa: BLE001 - fall back, never crash the pipeline
            print(f"HTML card render failed ({exc}); falling back to matplotlib.")

    brand, theme = _load_brand_and_theme(footer)
    fig, ax, layout = brand_template.create_canvas(
        len(rows), brand, theme, title=title, subtitle=subtitle,
    )
    if not rows:
        _draw_empty(ax, theme, "No upcoming fixtures available")
    else:
        chart_blocks.draw_fixture_rows(ax, rows, theme, layout)
    return brand_template.save_chart(fig, output_path, theme)


def _estimate_label(pred: dict[str, Any]) -> str:
    """Compact card label for the model edge; avoids public certainty language."""
    outcome = pred.get("predicted_outcome", "")
    p_home = float(pred.get("p_home", 0) or 0)
    p_draw = float(pred.get("p_draw", 0) or 0)
    p_away = float(pred.get("p_away", 0) or 0)
    confidence = max(p_home, p_draw, p_away)
    if confidence < 0.38:
        return "Too close"
    if confidence < 0.46:
        return "Balanced"
    if outcome == "HOME":
        return f"{pred.get('home_team_name', 'Home')} {round(p_home * 100)}%"
    if outcome == "AWAY":
        return f"{pred.get('away_team_name', 'Away')} {round(p_away * 100)}%"
    return "Balanced"


def _predictions_to_card_rows(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map internal estimate rows to compact public card rows."""
    rows: list[dict[str, Any]] = []
    for p in predictions:
        label = f"{p.get('home_team_name', '')} vs {p.get('away_team_name', '')}".strip(" vs")
        rows.append({
            "label": label or "TBD",
            "col_a": _estimate_label(p),
            "col_b": str(p.get("most_likely_score", "")).replace("-", "–"),
        })
    return rows


def render_prediction_chart(
    predictions: list[dict[str, Any]],
    output_path: str | None = None,
    limit: int = 10,
    title: str = "World Cup Match Predictions",
    subtitle: str = "Educational data model • Public football data • BuildWithAbdallah",
) -> str:
    """Render a branded card of educational match predictions (model edge + predicted score).

    Uses the shared HTML card template; falls back to matplotlib if Playwright is
    unavailable, so it never crashes the pipeline. The footer carries the
    required educational-prediction / not-affiliated disclaimer.
    """

    if output_path is None:
        output_path = str(DEFAULT_CHART_DIR / "match_predictions.png")

    footer = PITCH_AGENT_CARD_FOOTER
    rows = list(predictions[:limit])
    if rows:
        try:
            return brand_template.generate_list_card_html(
                title, subtitle, _predictions_to_card_rows(rows), output_path,
                footer_text=footer,
            )
        except Exception as exc:  # noqa: BLE001 - fall back, never crash the pipeline
            print(f"HTML card render failed ({exc}); falling back to matplotlib.")

    if rows:
        return brand_template.generate_list_card(
            title, subtitle, _predictions_to_card_rows(rows), output_path,
            footer_text=footer,
        )
    brand, theme = _load_brand_and_theme()
    brand["footer"] = footer
    fig, ax, layout = brand_template.create_canvas(4, brand, theme, title=title, subtitle=subtitle)
    _draw_empty(ax, theme, "No upcoming fixtures to predict")
    return brand_template.save_chart(fig, output_path, theme)


def render_player_spotlight_chart(
    player: dict[str, Any],
    output_path: str | None = None,
    title: str = "Player Spotlight",
    subtitle: str = "Form Index v1.0 Lite",
) -> str:
    """Render a single-player spotlight card with the brand template."""
    if output_path is None:
        output_path = str(DEFAULT_CHART_DIR / "player_spotlight.png")
    brand, theme = _load_brand_and_theme()
    fig, ax, layout = brand_template.create_canvas(
        4, brand, theme, title=title, subtitle=subtitle,
    )
    if not player:
        _draw_empty(ax, theme, "No player data available")
    else:
        chart_blocks.draw_player_spotlight(ax, player, theme, layout)
    return brand_template.save_chart(fig, output_path, theme)


def render_stat_card_chart(
    stat: dict[str, Any],
    output_path: str | None = None,
    title: str = "Stat of the Day",
    subtitle: str = "Form Index v1.0 Lite",
) -> str:
    """Render a big-number stat card with the brand template."""
    if output_path is None:
        output_path = str(DEFAULT_CHART_DIR / "stat_of_the_day.png")
    brand, theme = _load_brand_and_theme()
    fig, ax, layout = brand_template.create_canvas(
        4, brand, theme, title=title, subtitle=subtitle,
    )
    if not stat:
        _draw_empty(ax, theme, "No stat available")
    else:
        chart_blocks.draw_stat_card(ax, stat, theme, layout)
    return brand_template.save_chart(fig, output_path, theme)


def _projection_to_card_rows(projection: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map a group projection to ``{label, col_a, col_b}``: team, advance %, win-group %."""
    rows: list[dict[str, Any]] = []
    for r in projection:
        rows.append({
            "label": str(r.get("team", "")),
            "col_a": f"{round(r.get('p_advance', 0) * 100)}% advance",
            "col_b": f"{round(r.get('p_win_group', 0) * 100)}% win",
        })
    return rows


def render_group_projection_chart(
    projection: list[dict[str, Any]],
    group_label: str,
    output_path: str | None = None,
    title: str | None = None,
    subtitle: str = "Educational data model • 10k simulations • Public football data",
) -> str:
    """Render a branded card of a group's advance/win probabilities."""
    if output_path is None:
        output_path = str(DEFAULT_CHART_DIR / "group_projection.png")
    title = title or f"{group_label}: Match Outlook"
    footer = PITCH_AGENT_CARD_FOOTER
    rows = _projection_to_card_rows(projection)
    if rows:
        try:
            return brand_template.generate_list_card_html(
                title, subtitle, rows, output_path, footer_text=footer,
            )
        except Exception as exc:  # noqa: BLE001 - fall back, never crash the pipeline
            print(f"HTML card render failed ({exc}); falling back to matplotlib.")
        return brand_template.generate_list_card(
            title, subtitle, rows, output_path, footer_text=footer,
        )
    brand, theme = _load_brand_and_theme()
    brand["footer"] = footer
    fig, ax, layout = brand_template.create_canvas(4, brand, theme, title=title, subtitle=subtitle)
    _draw_empty(ax, theme, "No group data to project")
    return brand_template.save_chart(fig, output_path, theme)


def _draw_empty(ax: Any, theme: dict[str, Any], message: str) -> None:
    ax.text(0.5, 0.45, message, transform=ax.transAxes, ha="center", va="center",
            fontsize=15, color=theme.get("secondary_text", "#6B7280"))


def render_for_pillar(
    pillar: str,
    data: list[dict[str, Any]],
    output_path: str,
    scope: str = "daily",
    position: str | None = None,
    provider_name: str = "",
    data_quality: str = "basic",
    as_of_date: str = "",
) -> str:
    """Render the appropriate branded chart for a content pillar.

    All chart types share the same template engine; only the content block
    differs. Leaderboard-style pillars reuse the ranked-rows block.
    """
    if pillar == "matchday_preview":
        return render_fixtures_chart(data, output_path=output_path)
    if pillar == "match_prediction":
        return render_prediction_chart(data, output_path=output_path)
    if pillar == "player_spotlight" and data:
        return render_player_spotlight_chart(data[0], output_path=output_path)
    if pillar == "stat_of_the_day" and data:
        top = data[0]
        stat = {
            "value": f"{float(top.get('score', 0) or 0):.1f}",
            "label": top.get("player_name", ""),
            "sub": "Top Form Index today",
        }
        return render_stat_card_chart(stat, output_path=output_path)
    return render_leaderboard_chart(
        data, output_path=output_path, position=position, scope=scope,
        provider_name=provider_name, data_quality=data_quality, as_of_date=as_of_date,
    )
