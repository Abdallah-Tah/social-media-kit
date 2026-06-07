"""Content generation for the 9 content pillars.

Generates text content for social media (fan_mode) or structured JSON
(builder_mode).  During the group stage, per-match and daily leaderboards
are the headline; cumulative tournament index only becomes meaningful
after enough matches.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from pitch_agent import MODEL_VERSION, MODEL_VERSION_LABEL, PITCH_AGENT_CAPTION_DISCLAIMER
from pitch_agent.config import load_env
from pitch_agent.transparency import TRADEMARK_DISCLAIMER

DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"
FAN_MODE_FORBIDDEN_TERMS = (
    "python",
    "sqlite",
    "api",
    "smkit",
    "cron",
    "github",
    "code",
    "betting",
    "gambling",
    "sportsbook",
    "odds",
    "wagering",
)
PUBLIC_FORBIDDEN_TERMS = (
    "betting",
    "gambling",
    "sportsbook",
    "odds",
    "wagering",
)

# ── Content pillars ────────────────────────────────────────────────────────

PILLARS = [
    "form_index_update",
    "position_leaderboard",
    "player_spotlight",
    "team_form_report",
    "news_digest",
    "stat_of_the_day",
    "underdog_watch",
    "post_match_grades",
    "builder_update",
    "matchday_preview",
    "match_prediction",
    "real_data_connected",
]

# Fixture-driven pillars work before any player grades exist: they read the
# matches table instead of the Form Index leaderboard.
FIXTURE_PILLARS = ("matchday_preview", "match_prediction", "real_data_connected")

# The four pillars frozen as production-ready for the World Cup launch. Other
# pillars still run but are not yet considered launch quality.
PRIORITY_PILLARS = (
    "form_index_update",
    "position_leaderboard",
    "player_spotlight",
    "post_match_grades",
)

# Position display names
POSITION_NAMES = {
    "FWD": "Forwards",
    "MID": "Midfielders",
    "DEF": "Defenders",
    "GK": "Goalkeepers",
}

# Short phrases used to weave a position into a sentence.
POSITION_PHRASES = {
    "FWD": "in attack",
    "MID": "from midfield",
    "DEF": "from defence",
    "GK": "in goal",
}

# Consumer-facing tagline that frames the project as analytics, not tipping.
FORM_INDEX_TAGLINE = "The Pitch Agent tracks performance and explains match outlooks with public data."

# Keep fan posts comfortably short for X, Threads, Facebook, and LinkedIn.
FAN_MODE_MAX_CHARS = 900

# ── Fan-mode goal strings ──────────────────────────────────────────────────

FAN_GOAL_STRINGS = {
    "form_index_update": (
        "Write a football-only analytics post for The Pitch Agent using the "
        "attached Form Index leaderboard data. Focus on top performers, "
        "surprising scores, and what the data reveals. Keep the copy strictly "
        "consumer-facing and limited to on-pitch performance."
    ),
    "position_leaderboard": (
        "Write a football-only analytics post for The Pitch Agent using the "
        "attached position leaderboard chart. Focus on the top performers by "
        "position, why the ranking is interesting, and what the data shows "
        "beyond goals. Keep the copy strictly consumer-facing and limited to "
        "on-pitch performance."
    ),
    "player_spotlight": (
        "Write a football-only player spotlight post for The Pitch Agent. "
        "Highlight an individual player's Form Index performance and what "
        "makes their numbers stand out. Keep the copy strictly consumer-facing "
        "and limited to on-pitch performance."
    ),
    "team_form_report": (
        "Write a football-only team form report for The Pitch Agent. "
        "Analyse how a team's players are performing across positions "
        "using Form Index data. Keep the copy strictly consumer-facing and "
        "limited to on-pitch performance."
    ),
    "news_digest": (
        "Write a football-only news digest for The Pitch Agent. "
        "Summarise key Form Index movements and notable performances. "
        "Keep the copy strictly consumer-facing and limited to on-pitch "
        "performance."
    ),
    "stat_of_the_day": (
        "Write a football-only stat-of-the-day post for The Pitch Agent. "
        "Pick one striking statistic from the Form Index data and explain "
        "why it matters. Keep the copy strictly consumer-facing and limited "
        "to on-pitch performance."
    ),
    "underdog_watch": (
        "Write a football-only underdog watch post for The Pitch Agent. "
        "Highlight players or teams punching above their weight according to "
        "the Form Index. Keep the copy strictly consumer-facing and limited "
        "to on-pitch performance."
    ),
    "post_match_grades": (
        "Write a football-only post-match grades post for The Pitch Agent. "
        "Grade individual performances using Form Index scores. "
        "Keep the copy strictly consumer-facing and limited to on-pitch "
        "performance."
    ),
    "builder_update": (
        "Generate a structured builder update with the latest Form Index "
        "scores, leaderboard changes, and data quality notes."
    ),
    "matchday_preview": (
        "Write a short, football-only preview of the upcoming World Cup "
        "fixtures for The Pitch Agent. Mention the next few matches and any "
        "group or stage context. No match estimates, no certainty claims — just what is "
        "coming up and an invitation to follow for Form Index updates once the "
        "matches are played."
    ),
    "match_prediction": (
        "Write a short, football-only post sharing The Pitch Agent's data-based "
        "educational match predictions for upcoming World Cup fixtures. Use "
        "prediction, match outlook, and predicted score language only when it is "
        "clearly framed as data-based, educational, and not betting advice. Mention "
        "the side with a model edge only when confidence is clear. Include the "
        "required World Cup disclaimer."
    ),
    "real_data_connected": (
        "Generate a structured builder update confirming that real World Cup "
        "fixtures are now connected and the agent is ready to grade results."
    ),
}


def generate_content(
    pillar: str,
    mode: str = "fan_mode",
    db_path: str = "pitch_agent.db",
    dry_run: bool = False,
    position: str | None = None,
    match_id: str | None = None,
    headline_index_mode: str = "daily",
    leaderboard_scope: str | None = None,
    send_telegram_review: bool = False,
    telegram_debug: bool = False,
    strict_telegram: bool = False,
    use_ai: bool = False,
) -> dict[str, Any]:
    """Generate content for a given pillar.

    Parameters
    ----------
    pillar : str
        One of the 9 content pillars.
    mode : str
        ``fan_mode`` for human-readable text, ``builder_mode`` for JSON.
    db_path : str
        Path to the SQLite database.
    dry_run : bool
        If True, print to stdout but do not record in the runs table.
    position : str or None
        Filter by position (for position_leaderboard pillar).
    match_id : str or None
        Filter by match (for form_index_update, post_match_grades).
    headline_index_mode : str
        ``daily`` (group stage) or ``cumulative`` (knockout).
    leaderboard_scope : str or None
        Optional explicit leaderboard scope.  By default, public update pillars
        use daily scope and post-match grades use player-match scope.
    send_telegram_review : bool
        If True, send the visible post and safe metadata to Telegram review.
    telegram_debug : bool
        If True, include the raw generated payload in the Telegram review.
    strict_telegram : bool
        Stored in the result so CLI callers can fail after visible output when
        Telegram review is skipped.
    use_ai : bool
        If True, ask Anthropic to rewrite/summarize the template output. Missing
        credentials or request failures keep the template output.

    Returns
    -------
    dict
        With keys: ``pillar``, ``mode``, ``content``, ``goal_string``.
    """
    if pillar not in PILLARS:
        raise ValueError(f"Unknown pillar '{pillar}'. Available: {', '.join(PILLARS)}")

    # Fetch data based on pillar
    if pillar in FIXTURE_PILLARS:
        scope = "fixtures"
        if pillar == "match_prediction":
            from pitch_agent.predict import predict_upcoming
            data = predict_upcoming(db_path=db_path, limit=10)
        else:
            from pitch_agent.fixtures import get_fixtures
            data = get_fixtures(db_path=db_path, limit=10)
    else:
        scope = _default_scope_for_pillar(pillar, leaderboard_scope)
        data = _fetch_pillar_data(pillar, db_path, position, match_id, scope)

    # Generate content
    if mode == "builder_mode":
        content = _generate_builder_mode(pillar, data, headline_index_mode)
    else:
        content = _generate_fan_mode(pillar, data, headline_index_mode, position)

    result = {
        "pillar": pillar,
        "mode": mode,
        "content": content,
        "goal_string": FAN_GOAL_STRINGS.get(pillar, ""),
        "disclaimer": TRADEMARK_DISCLAIMER,
        "metadata": _build_operational_metadata(
            pillar=pillar,
            mode=mode,
            data=data,
            position=position,
            match_id=match_id,
            scope=scope,
        ),
    }

    if use_ai:
        ai_result = _rewrite_with_anthropic(
            pillar=pillar,
            mode=mode,
            content=content,
            data=data,
            headline_index_mode=headline_index_mode,
        )
        result["ai_rewrite"] = {
            "used": ai_result["used"],
            "model": ai_result["model"],
        }
        if ai_result.get("warning"):
            result["ai_rewrite"]["warning"] = ai_result["warning"]
            print(ai_result["warning"])
        if not ai_result["used"]:
            print("AI rewrite unavailable; using template content.")
        if ai_result["used"]:
            if mode == "builder_mode" and isinstance(content, dict):
                content["ai_summary"] = ai_result["content"]
                result["content"] = content
            else:
                result["content"] = ai_result["content"]

    from pitch_agent.validation import validate_pitch_agent_post
    validation_errors = validate_pitch_agent_post(
        title=str(pillar).replace("_", " ").title(),
        caption=str(result["content"]),
        rows=data if isinstance(data, list) else [],
        footer_text="BuildWithAbdallah.com" if pillar not in FIXTURE_PILLARS else None,
        require_rows=pillar in FIXTURE_PILLARS,
    )
    result["validation_errors"] = validation_errors
    if validation_errors:
        print("Pitch Agent validation warnings: " + "; ".join(validation_errors))

    if send_telegram_review:
        _ensure_review_chart(result["metadata"], data, position)
        from pitch_agent.telegram_review import send_review
        result["telegram_review"] = send_review(result, debug=telegram_debug)
        result["strict_telegram"] = strict_telegram

    if dry_run:
        output_content = result["content"]
        print(f"[DRY RUN] {pillar} ({mode}):\n")
        if mode == "builder_mode":
            print(json.dumps(output_content, indent=2))
        else:
            print(output_content)
        if TRADEMARK_DISCLAIMER not in str(output_content):
            print(f"\n{TRADEMARK_DISCLAIMER}")
        return result

    # Record the run (not for dry runs)
    from pitch_agent.db import get_connection, insert_run
    conn = get_connection(db_path)
    insert_run(conn, {
        "run_type": "content_generation",
        "pillar": pillar,
        "provider": "",
        "mode": mode,
        "dry_run": 0,
        "status": "completed",
    })
    conn.close()

    return result


def _fetch_pillar_data(
    pillar: str,
    db_path: str,
    position: str | None = None,
    match_id: str | None = None,
    scope: str = "daily",
) -> list[dict[str, Any]]:
    """Fetch leaderboard data for a pillar."""
    from pitch_agent.leaderboard import get_leaderboard

    if pillar == "post_match_grades":
        scope = "player_match"
    return get_leaderboard(
        db_path=db_path,
        position=position,
        limit=20,
        scope=scope,
        match_id=match_id,
    )


def _default_scope_for_pillar(pillar: str, explicit_scope: str | None = None) -> str:
    """Return the default leaderboard scope for a content pillar."""
    if explicit_scope:
        return explicit_scope
    if pillar == "post_match_grades":
        return "player_match"
    if pillar in {"form_index_update", "position_leaderboard"}:
        return "daily"
    return "daily"


def _ensure_review_chart(
    metadata: dict[str, Any],
    data: list[dict[str, Any]],
    position: str | None = None,
) -> None:
    """Render the review chart for the current content.

    Always regenerates so the reviewed image reflects the current fixtures/scores
    and branding — chart paths are deterministic and shared across runs, so a
    stale file from a previous run must not be reused.
    """
    chart_path = metadata.get("chart_path")
    if not chart_path or not data:
        return

    from pitch_agent.charts import render_for_pillar
    render_for_pillar(
        metadata.get("pillar", ""),
        data,
        output_path=chart_path,
        scope=metadata.get("leaderboard_scope", "daily"),
        position=position,
        provider_name=metadata.get("provider_name", ""),
        data_quality=metadata.get("data_quality_level", "basic") or "basic",
        as_of_date=str(data[0].get("match_date", "")) if data else "",
    )


def _build_operational_metadata(
    pillar: str,
    mode: str,
    data: list[dict[str, Any]],
    position: str | None = None,
    match_id: str | None = None,
    scope: str = "daily",
) -> dict[str, Any]:
    """Return internal metadata for debugging, dedupe, and publishing."""
    status_note = ""
    chart_path = ""

    if pillar in FIXTURE_PILLARS:
        # Fixture-driven content reads the matches table, not Form Index scores.
        provider_name = _fixture_provider(data)
        quality = "fixture-only"
        status_note = "real fixtures, no player grades yet"
        charts_dir = Path("artifacts") / "pitch_agent" / "charts"
        if pillar == "matchday_preview":
            chart_path = str(charts_dir / "fixtures.png")
        elif pillar == "match_prediction":
            chart_path = str(charts_dir / "match_estimates.png")
            status_note = "data-based estimates, not betting advice"
    else:
        providers: set[str] = set()
        quality_levels: set[str] = set()
        for row in data:
            try:
                breakdown = json.loads(row.get("score_breakdown_json") or "{}")
            except json.JSONDecodeError:
                breakdown = {}
            if breakdown.get("provider_name"):
                providers.add(str(breakdown["provider_name"]))
            if breakdown.get("data_quality_level"):
                quality_levels.add(str(breakdown["data_quality_level"]))
        provider_name = ",".join(sorted(providers))
        quality = ",".join(sorted(quality_levels))
        charts_dir = Path("artifacts") / "pitch_agent" / "charts"
        if pillar in {"form_index_update", "position_leaderboard"}:
            suffix = f"_{position.lower()}" if position else ""
            chart_path = str(charts_dir / f"leaderboard{suffix}.png")
        elif pillar in {
            "player_spotlight", "post_match_grades",
            "stat_of_the_day", "team_form_report",
        }:
            # These pillars chart the same leaderboard data; give each its own
            # branded image so Telegram review can attach one.
            chart_path = str(charts_dir / f"{pillar}.png")

    key_parts = [pillar, mode]
    key_parts.append(scope.replace("_", "-"))
    if position:
        key_parts.append(position.upper())
    if match_id:
        key_parts.append(match_id)

    from pitch_agent.config import load_brand
    brand = load_brand()

    metadata = {
        "mode": mode,
        "pillar": pillar,
        "brand": brand.get("name", ""),
        "brand_parent": brand.get("parent_brand", ""),
        "model_version": MODEL_VERSION,
        "model_version_label": MODEL_VERSION_LABEL,
        "production_ready": pillar in PRIORITY_PILLARS,
        "leaderboard_scope": scope,
        "provider_name": provider_name,
        "chart_path": chart_path,
        "post_key": ":".join(key_parts),
        "smkit_command": f"smkit publish --pillar {pillar} --mode {mode}",
        "data_quality_level": quality,
    }
    if status_note:
        metadata["status_note"] = status_note
    return metadata


def _generate_fan_mode(
    pillar: str,
    data: list[dict[str, Any]],
    headline_index_mode: str,
    position: str | None = None,
) -> str:
    """Generate a short, human-readable football story for fan_mode.

    The leaderboard data is the source of truth, but the visible post reads as
    a few sentences (leader, a challenger, a quieter story) rather than a raw
    table — much friendlier for X, Threads, Facebook, and LinkedIn.
    """
    if pillar == "matchday_preview":
        return _generate_matchday_preview(data)
    if pillar == "match_prediction":
        return _generate_match_prediction(data)
    if pillar in FIXTURE_PILLARS:
        # e.g. real_data_connected is a builder-mode pillar with no fan narrative.
        return (
            "This update is available in builder mode.\n\n"
            f"{TRADEMARK_DISCLAIMER}"
        )

    if not data:
        return "No data available for this pillar yet."

    header = _fan_mode_header(pillar, headline_index_mode, position)
    narrative = _build_fan_narrative(data, headline_index_mode)

    parts = [header, "", narrative, "", FORM_INDEX_TAGLINE, "", TRADEMARK_DISCLAIMER]
    return "\n".join(parts)


def _generate_matchday_preview(fixtures: list[dict[str, Any]]) -> str:
    """Build a short, estimate-free preview of the next few fixtures."""
    if not fixtures:
        return (
            "No upcoming fixtures available yet.\n\n"
            "Follow The Pitch Agent for Form Index updates once matches are played.\n\n"
            f"{TRADEMARK_DISCLAIMER}"
        )

    upcoming = fixtures[:5]
    lines = ["🗓️ Matchday Preview", ""]
    lines.append(f"Next up on the World Cup calendar — {len(upcoming)} matches to watch:")
    lines.append("")
    for fx in upcoming:
        label = fx.get("match_label") or "TBD"
        context = _fixture_context(fx)
        date = _short_date(fx.get("date", ""))
        bullet = f"• {label}"
        details = " — ".join(part for part in (date, context) if part)
        if details:
            bullet += f" ({details})"
        lines.append(bullet)
    lines.append("")
    lines.append(
        "Follow The Pitch Agent for Form Index updates once matches are played."
    )
    lines.append("")
    lines.append(TRADEMARK_DISCLAIMER)
    return "\n".join(lines)


def _prediction_phrase(pred: dict[str, Any]) -> str:
    """Return safe, compact public wording for an educational model prediction."""
    outcome = pred.get("predicted_outcome", "")
    p_home = float(pred.get("p_home", 0) or 0)
    p_draw = float(pred.get("p_draw", 0) or 0)
    p_away = float(pred.get("p_away", 0) or 0)
    confidence = max(p_home, p_draw, p_away)
    if confidence < 0.38:
        return "too close to call"
    if confidence < 0.46:
        return "balanced matchup"
    if outcome == "HOME":
        label = pred.get("home_team_name", "Home")
        edge = "strong edge" if confidence >= 0.65 else "slight edge"
        return f"{label} {edge} ({round(p_home * 100)}%)"
    if outcome == "AWAY":
        label = pred.get("away_team_name", "Away")
        edge = "strong edge" if confidence >= 0.65 else "slight edge"
        return f"{label} {edge} ({round(p_away * 100)}%)"
    return f"balanced matchup ({round(p_draw * 100)}% draw)"


def _generate_match_prediction(predictions: list[dict[str, Any]]) -> str:
    """Build a short, human preview of educational match predictions.

    Public wording may use prediction language when it is clearly framed as
    educational, data-based, not guaranteed, and not betting advice.
    """
    from pitch_agent.predict import PREDICTION_DISCLAIMER

    if not predictions:
        return (
            "No upcoming fixtures to predict yet.\n\n"
            "Educational predictions appear once the schedule and early results are in.\n\n"
            f"{PITCH_AGENT_CAPTION_DISCLAIMER}"
        )

    upcoming = predictions[:3]
    lines = ["🔮 World Cup Match Predictions", ""]
    lines.append(
        f"Here are The Pitch Agent's data-based predictions for the next {len(upcoming)} matches:"
    )
    lines.append("")
    for p in upcoming:
        home = p.get("home_team_name", "")
        away = p.get("away_team_name", "")
        projected = str(p.get("most_likely_score", "")).replace("-", "–")
        line = f"• {home} vs {away} — {_prediction_phrase(p)}"
        if projected:
            line += f" — predicted {projected}"
        lines.append(line)
    lines.append("")
    lines.append("These predictions are generated from public data for educational analytics only. They are not guarantees and not betting advice.")
    lines.append("")
    lines.append(PREDICTION_DISCLAIMER)
    lines.append("")
    lines.append(PITCH_AGENT_CAPTION_DISCLAIMER)
    return "\n".join(lines)


def _fixture_context(fixture: dict[str, Any]) -> str:
    """Return a 'Group A' / stage label for a fixture when available."""
    from pitch_agent.fixtures import normalize_stage_label
    return (normalize_stage_label(fixture.get("group_name"))
            or normalize_stage_label(fixture.get("stage")))


def _short_date(value: str) -> str:
    """Format an ISO date/datetime as 'Jun 11'; pass through on failure."""
    value = (value or "").strip()
    if not value:
        return ""
    from datetime import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%b %-d")
        except ValueError:
            continue
    return value[:10]


def _fan_mode_header(
    pillar: str,
    headline_index_mode: str,
    position: str | None = None,
) -> str:
    """Return the headline line for a fan-mode post."""
    if pillar == "position_leaderboard" and position:
        pos_name = POSITION_NAMES.get(position.upper(), position)
        return f"🏆 Top {pos_name} — Form Index Leaderboard"
    if pillar == "form_index_update":
        if headline_index_mode == "daily":
            return "📊 Daily Form Index Update"
        return "📊 Cumulative Form Index Leaderboard"
    return f"📋 {pillar.replace('_', ' ').title()}"


def _build_fan_narrative(
    data: list[dict[str, Any]],
    headline_index_mode: str,
) -> str:
    """Turn the leaderboard rows into a few narrative sentences."""
    leader = data[0]
    descriptor = "today's Form Index" if headline_index_mode == "daily" else "the Form Index"

    leader_line = (
        f"{leader['player_name']} ({leader['team_name']}) leads {descriptor} with "
        f"a {leader['score']:.1f}{_position_phrase_suffix(leader)}"
    )
    match_label = str(leader.get("match_label") or "").strip()
    if match_label:
        leader_line += f" after {match_label}"
    key_reason = str(leader.get("key_reason") or "").strip()
    if key_reason:
        leader_line += f" — {key_reason}"
    leader_line += "."

    movement = leader.get("score_movement")
    if movement:
        direction = "up" if movement > 0 else "down"
        leader_line += (
            f" That is {abs(movement):.0f} points {direction} on the previous match."
        )

    sentences = [leader_line]

    challenger = data[1] if len(data) > 1 else None
    if challenger:
        sentences.append(
            f"{challenger['player_name']} ({challenger['team_name']}) follows at "
            f"{challenger['score']:.1f}, keeping the chase close."
        )

    exclude = {leader.get("player_id")}
    if challenger:
        exclude.add(challenger.get("player_id"))
    surprise = _find_surprise(data, exclude)
    if surprise:
        phrase = POSITION_PHRASES.get((surprise.get("position") or "").upper(), "")
        where = f" {phrase}" if phrase else ""
        sentences.append(
            f"The quiet story{where}: {surprise['player_name']} "
            f"({surprise['team_name']}) lands at {surprise['score']:.1f}, a reminder "
            "the Index rewards more than goals."
        )

    return "\n\n".join(sentences)


def _position_phrase_suffix(row: dict[str, Any]) -> str:
    """Return ` from midfield`-style suffix, or empty when unknown."""
    phrase = POSITION_PHRASES.get((row.get("position") or "").upper(), "")
    return f" {phrase}" if phrase else ""


def _find_surprise(
    data: list[dict[str, Any]],
    exclude: set[Any],
) -> dict[str, Any] | None:
    """Pick a top-of-table story, preferring a non-forward to show breadth."""
    for row in data[:5]:
        if row.get("player_id") in exclude:
            continue
        if (row.get("position") or "").upper() != "FWD":
            return row
    for row in data[:5]:
        if row.get("player_id") not in exclude:
            return row
    return None


def _generate_builder_mode(
    pillar: str,
    data: list[dict[str, Any]],
    headline_index_mode: str,
) -> dict[str, Any]:
    """Generate structured JSON content for builder_mode."""
    if pillar == "real_data_connected":
        return _generate_real_data_connected(data)
    return {
        "pillar": pillar,
        "headline_index_mode": headline_index_mode,
        "data": data,
        "disclaimer": TRADEMARK_DISCLAIMER,
        "model_version": "1.0.0-lite",
    }


def _generate_real_data_connected(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    """Builder update confirming real fixtures are connected and grade-ready."""
    provider = _fixture_provider(fixtures) or "football-data"
    return {
        "pillar": "real_data_connected",
        "summary": (
            "The Pitch Agent now pulls real World Cup fixtures from "
            f"{provider}.org and is ready to grade player performances with "
            "Form Index v1.0 Lite once match results are available."
        ),
        "provider": provider,
        "data_quality_level": "fixture-only",
        "status": "real fixtures, no player grades yet",
        "fixtures_loaded": len(fixtures),
        "next_step": (
            "Re-run the data sync after matches are played to compute Form "
            "Index scores and switch to result-based content."
        ),
        "model_version": MODEL_VERSION,
        "model_version_label": MODEL_VERSION_LABEL,
        "disclaimer": TRADEMARK_DISCLAIMER,
    }


def _fixture_provider(fixtures: list[dict[str, Any]]) -> str:
    """Return the most common provider name across fixtures."""
    counts: dict[str, int] = {}
    for fx in fixtures:
        name = str(fx.get("provider_name") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def _rewrite_with_anthropic(
    pillar: str,
    mode: str,
    content: Any,
    data: list[dict[str, Any]],
    headline_index_mode: str,
) -> dict[str, Any]:
    """Optionally rewrite template content with Anthropic, falling back safely."""
    load_env()
    model = (
        os.environ.get("BWA_ANTHROPIC_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or DEFAULT_ANTHROPIC_MODEL
    )
    api_key = os.environ.get("BWA_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "used": False,
            "model": model,
            "content": content,
            "warning": (
                "⚠️ Anthropic rewrite skipped: missing BWA_ANTHROPIC_API_KEY "
                "or ANTHROPIC_API_KEY."
            ),
        }

    prompt = _anthropic_prompt(
        pillar=pillar,
        mode=mode,
        content=content,
        data=data,
        headline_index_mode=headline_index_mode,
    )
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "used": False,
            "model": model,
            "content": content,
            "warning": f"⚠️ Anthropic rewrite skipped: {_safe_error_message(str(exc))}",
        }

    if response.status_code >= 400:
        return {
            "used": False,
            "model": model,
            "content": content,
            "warning": f"⚠️ Anthropic rewrite skipped: HTTP {response.status_code}: {_anthropic_error_message(response)}",
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "used": False,
            "model": model,
            "content": content,
            "warning": "⚠️ Anthropic rewrite skipped: invalid JSON response.",
        }

    text = _anthropic_text(payload)
    if not text:
        return {
            "used": False,
            "model": model,
            "content": content,
            "warning": "⚠️ Anthropic rewrite skipped: empty response.",
        }
    forbidden_terms = PUBLIC_FORBIDDEN_TERMS
    if mode == "fan_mode":
        forbidden_terms = FAN_MODE_FORBIDDEN_TERMS
    if _contains_forbidden_term(text, forbidden_terms):
        return {
            "used": False,
            "model": str(payload.get("model") or model),
            "content": content,
            "warning": "⚠️ Anthropic rewrite skipped: response contained disallowed wording.",
        }
    if mode == "fan_mode" and TRADEMARK_DISCLAIMER not in text:
        text = f"{text.rstrip()}\n\n{TRADEMARK_DISCLAIMER}"
    return {
        "used": True,
        "model": str(payload.get("model") or model),
        "content": text,
        "warning": "",
    }


def _anthropic_prompt(
    pillar: str,
    mode: str,
    content: Any,
    data: list[dict[str, Any]],
    headline_index_mode: str,
) -> str:
    compact_rows = [
        {
            "rank": row.get("rank"),
            "player": row.get("player_name"),
            "team": row.get("team_name"),
            "position": row.get("position"),
            "score": row.get("score"),
        }
        for row in data[:10]
    ]
    if mode == "builder_mode":
        return (
            "Create a concise builder update for The Pitch Agent. You may refer "
            "to the technical pipeline, data quality, leaderboard scope, and "
            "model version. Keep it limited to system operations and football "
            "performance, with no money-stake calls to action.\n\n"
            f"pillar: {pillar}\n"
            f"headline_index_mode: {headline_index_mode}\n"
            f"leaderboard: {json.dumps(compact_rows, ensure_ascii=True)}\n"
            f"current_payload: {json.dumps(content, ensure_ascii=True, default=str)}"
        )
    return (
        "Rewrite this football Form Index post for The Pitch Agent. Keep it "
        "concise, fan friendly, and focused only on what happened on the pitch. "
        "Use simple English and avoid hype, certainty claims, and gambling language. "
        "Prediction wording is allowed only when framed as educational and "
        "data-based. Keep the independent project note if "
        "it appears. Do not add money-related language.\n\n"
        f"pillar: {pillar}\n"
        f"leaderboard: {json.dumps(compact_rows, ensure_ascii=True)}\n"
        f"post:\n{content}"
    )


def _anthropic_text(payload: dict[str, Any]) -> str:
    parts = []
    for item in payload.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(p for p in parts if p).strip()


def _anthropic_error_message(response: Any) -> str:
    try:
        payload = response.json()
    except ValueError:
        return _safe_error_message(getattr(response, "text", "") or "request failed")
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if isinstance(error, dict):
        text = error.get("message") or error.get("type") or "request failed"
    else:
        text = str(error or "request failed")
    return _safe_error_message(text)


def _safe_error_message(text: str) -> str:
    redacted = os.environ.get("BWA_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    safe = str(text).replace(redacted, "[redacted]") if redacted else str(text)
    return " ".join(safe.split())[:500]


def _contains_forbidden_term(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)
