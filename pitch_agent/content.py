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

from pitch_agent import MODEL_VERSION, MODEL_VERSION_LABEL
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
    "match_recap",
    "real_data_connected",
]

# Fixture-driven pillars work before any player grades exist: they read the
# matches table instead of the Form Index leaderboard.
FIXTURE_PILLARS = ("matchday_preview", "match_recap", "real_data_connected")

# Confidence tiers for predictions. A credible analyst headlines only the
# games with a real edge and says "too close to call" on coin-flips — that
# both reads sharper and keeps the public hit-rate honest-but-strong.
CONFIDENT_PICK = 0.58   # >= this top-outcome prob → a headlined pick
LEAN_PICK = 0.50        # >= this → a soft lean; below → too close to call

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
FORM_INDEX_TAGLINE = "The Pitch Agent tracks performance, not predictions."

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
        "group or stage context. No predictions, no money talk — just what is "
        "coming up and an invitation to follow for Form Index updates once the "
        "matches are played."
    ),
    "match_recap": (
        "Write a football-only post-match recap for The Pitch Agent. "
        "Report the final score, compare the journaled prediction to the "
        "actual result, and show the model's running record. Keep the copy "
        "strictly consumer-facing and limited to on-pitch performance. "
        "Never present non-journaled numbers as model predictions."
    ),
    "real_data_connected": (
        "Generate a structured builder update confirming that real World Cup "
        "fixtures are now connected and the agent is ready to grade results."
    ),
}


def _journal_run(task_type: str, **kwargs):
    """Taco run-journal context. Journaling must never break the pipeline:
    if agent_journal is unavailable, fall back to an inert record."""
    try:
        from agent_journal.journal import record_run
        return record_run(task_type, **kwargs)
    except Exception:
        import contextlib
        from types import SimpleNamespace

        @contextlib.contextmanager
        def _null():
            yield SimpleNamespace(
                model_used="", output_ref="", error=None, outcome=None,
                outcome_detail=None, tool_calls=[], run_id=None,
            )
        return _null()


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
    """Journal-instrumented wrapper around :func:`_generate_content_impl`."""
    with _journal_run(
        "generate",
        pillar=pillar,
        input_summary=f"mode={mode} dry_run={dry_run} use_ai={use_ai} match={match_id or '-'}",
    ) as rec:
        result = _generate_content_impl(
            pillar=pillar, mode=mode, db_path=db_path, dry_run=dry_run,
            position=position, match_id=match_id,
            headline_index_mode=headline_index_mode,
            leaderboard_scope=leaderboard_scope,
            send_telegram_review=send_telegram_review,
            telegram_debug=telegram_debug, strict_telegram=strict_telegram,
            use_ai=use_ai,
        )
        ai = result.get("ai_rewrite") or {}
        rec.model_used = ai.get("model", "") if ai.get("used") else "template"
        rec.output_ref = (result.get("metadata") or {}).get("chart_path", "") or ""
        return result


def _generate_content_impl(
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
    if pillar == "match_recap":
        scope = "finished"
        from pitch_agent.fixtures import get_finished_matches
        data = get_finished_matches(db_path=db_path, limit=10, match_id=match_id)
    elif pillar in FIXTURE_PILLARS:
        scope = "fixtures"
        from pitch_agent.fixtures import get_fixtures
        data = get_fixtures(db_path=db_path, limit=10)
    else:
        scope = _default_scope_for_pillar(pillar, leaderboard_scope)
        data = _fetch_pillar_data(pillar, db_path, position, match_id, scope)

    # Generate content
    recap_data = None  # For match_recap, populated separately
    if pillar == "match_recap" and mode != "builder_mode":
        recap_data = _build_match_recap_data(data, db_path)
        content = recap_data["text"]
    elif mode == "builder_mode":
        content = _generate_builder_mode(pillar, data, headline_index_mode)
    else:
        content = _generate_fan_mode(pillar, data, headline_index_mode, position, db_path=db_path)

    result = {
        "pillar": pillar,
        "mode": mode,
        "content": content,
        "goal_string": FAN_GOAL_STRINGS.get(pillar, ""),
        "disclaimer": TRADEMARK_DISCLAIMER,
        "recap_data": recap_data,  # None for non-recap pillars
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
            import sys
            print(ai_result["warning"], file=sys.stderr)
        if not ai_result["used"]:
            import sys
            print("AI rewrite unavailable; using template content.", file=sys.stderr)
        if ai_result["used"]:
            if mode == "builder_mode" and isinstance(content, dict):
                content["ai_summary"] = ai_result["content"]
                result["content"] = content
            else:
                result["content"] = ai_result["content"]

    if send_telegram_review:
        _ensure_review_chart(result["metadata"], data, position, recap_data=recap_data, db_path=db_path)
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
    recap_data: dict[str, Any] | None = None,
    db_path: str = "pitch_agent.db",
) -> None:
    """Render a review chart when the metadata points to a missing chart file.

    matchday_preview is time-sensitive (fixtures roll over daily), so its
    card is always re-rendered instead of reusing a cached file.
    """
    chart_path = metadata.get("chart_path")
    if not chart_path:
        return
    pillar = metadata.get("pillar", "")
    if Path(chart_path).is_file() and pillar != "matchday_preview":
        return

    # For match_recap, render HTML → PNG card via Playwright
    if pillar == "match_recap" and recap_data and recap_data.get("matches"):
        try:
            from pitch_agent.html_cards import render_match_recap_html_card
            render_match_recap_html_card(
                recap_data["matches"],
                output_path=chart_path,
                model_record=recap_data.get("model_record", ""),
            )
        except Exception as exc:
            import sys
            print(f"[pitch_agent] HTML card render failed ({exc}), falling back to matplotlib", file=sys.stderr)
            from pitch_agent.charts import render_match_recap_chart
            render_match_recap_chart(
                recap_data["matches"],
                output_path=chart_path,
                model_record=recap_data.get("model_record", ""),
            )
        return

    if not data:
        return

    # For matchday_preview, render the HTML → PNG card (same brand template
    # as match_recap) instead of the old matplotlib fixtures chart.
    if pillar == "matchday_preview":
        try:
            from pitch_agent.html_cards import render_matchday_preview_html_card
            card = _matchday_preview_card_data(data, db_path=db_path)
            render_matchday_preview_html_card(
                card["fixtures"],
                results=card["results"],
                model_record=card["model_record"],
                output_path=chart_path,
            )
            return
        except Exception as exc:
            import sys
            print(f"[pitch_agent] HTML card render failed ({exc}), falling back to matplotlib", file=sys.stderr)
            # fall through to the matplotlib path below

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
        if pillar == "matchday_preview":
            chart_path = str(
                Path("artifacts") / "pitch_agent" / "charts" / "fixtures.png"
            )
        elif pillar == "match_recap":
            chart_path = str(
                Path("artifacts") / "pitch_agent" / "charts" / "match_recap.png"
            )
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
    db_path: str = "pitch_agent.db",
) -> str:
    """Generate a short, human-readable football story for fan_mode.

    The leaderboard data is the source of truth, but the visible post reads as
    a few sentences (leader, a challenger, a quieter story) rather than a raw
    table — much friendlier for X, Threads, Facebook, and LinkedIn.
    """
    if pillar == "matchday_preview":
        return _generate_matchday_preview(data, db_path=db_path)
    if pillar == "match_recap":
        return _generate_match_recap(data, db_path=db_path)
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


def _generate_matchday_preview(
    fixtures: list[dict[str, Any]],
    db_path: str = "pitch_agent.db",
) -> str:
    """Build the matchday post: TODAY's games with predictions, plus a
    look back at recent results and how the Pitch Agent's predictions did.

    Only fixtures kicking off on today's local date are listed — never
    games days in advance.
    """
    import datetime as dt
    today_str = dt.date.today().strftime("%B %d")
    lines = [f"🗓️ Matchday — {today_str}", ""]

    # ── Today's matches only ─────────────────────────────────────────
    today = _upcoming_fixtures(fixtures or [], limit=6, today_only=True)
    if today:
        plural = "matches" if len(today) != 1 else "match"
        lines.append(f"⚽ Today's {plural} ({len(today)}):")
        for fx in today:
            label = fx.get("match_label") or "TBD"
            context = _fixture_context(fx)
            bullet = f"• {label}"
            if context:
                bullet += f" ({context})"
            lines.append(bullet)
            # Attach prediction if Form Index / Elo data exists
            prediction = _match_prediction(fx)
            if prediction:
                lines.append(f"  {prediction}")
        lines.append("")
    else:
        lines.append("No matches scheduled today.")
        lines.append("")

    # ── How the model did on recent results ──────────────────────────
    from pitch_agent.fixtures import get_finished_matches
    finished = get_finished_matches(db_path=db_path, limit=3)
    if finished:
        recap = _build_match_recap_data(finished, db_path)
        lines.append("🏁 How The Pitch Agent did — latest results:")
        for m in recap["matches"]:
            ctx = f" ({m['context']})" if m.get("context") else ""
            lines.append(f"• {m['label']}{ctx}")
            if m.get("prediction"):
                lines.append(f"  {m['prediction']}")
            elif m.get("no_pred"):
                lines.append("  (No prediction on record)")
        if recap.get("model_record"):
            lines.append("")
            lines.append(recap["model_record"])
        lines.append("")

    lines.append(
        "Follow The Pitch Agent for Form Index updates once matches are played."
    )
    lines.append("")
    lines.append(TRADEMARK_DISCLAIMER)
    return "\n".join(lines)


def _upcoming_fixtures(
    fixtures: list[dict[str, Any]],
    limit: int = 5,
    today_only: bool = False,
) -> list[dict[str, Any]]:
    """Filter to unplayed, future fixtures (same rules as the text preview).

    With ``today_only`` keep only fixtures whose kickoff falls on today's
    LOCAL date — the matchday post covers today's games, not days in
    advance. Fixtures with unparseable dates are excluded in that mode
    (we can't confirm they are today's).
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    today_local = now.astimezone().date()
    upcoming = []
    for fx in fixtures:
        if str(fx.get("status", "")).strip().upper() == "FINISHED":
            continue
        date_str = str(fx.get("date", ""))
        kickoff = None
        if date_str:
            try:
                kickoff = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                kickoff = None
        if kickoff is not None and kickoff.tzinfo is None:
            # Naive timestamps (e.g. date-only "2026-06-12") are local.
            kickoff = kickoff.astimezone()
        # Past-kickoff filter only applies when we have an actual kickoff
        # time — a date-only value is midnight, not a real kickoff.
        has_time = len(date_str) > 10
        if kickoff is not None and has_time and kickoff < now:
            continue
        if today_only:
            if kickoff is None or kickoff.astimezone().date() != today_local:
                continue
        upcoming.append(fx)
    return upcoming[:limit]


def _matchday_preview_card_data(
    fixtures: list[dict[str, Any]],
    db_path: str = "pitch_agent.db",
) -> dict[str, Any]:
    """Shape today's games + recent results into the matchday HTML card.

    Returns {fixtures, results, model_record}. Row counts are capped so
    the sections fit the 1200x628 card without colliding with the footer.
    """
    from datetime import datetime

    rows = []
    for fx in _upcoming_fixtures(fixtures or [], limit=3, today_only=True):
        label = fx.get("match_label") or "TBD"
        # Today's games: show LOCAL kickoff time, not the (possibly
        # next-day) UTC date — "Jun 13" under "Today's matches" reads wrong.
        date_str = str(fx.get("date", ""))
        try:
            kickoff = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if len(date_str) <= 10:  # date-only — midnight isn't a kickoff time
                raise ValueError
            date = kickoff.astimezone().strftime("%-I:%M %p")
        except (ValueError, TypeError):
            date = _short_date(date_str)
        group = _fixture_context(fx)
        prediction = _match_prediction(fx)
        if prediction:
            # Drop the verbose Elo-edge tail — the card needs one clean line.
            prediction = prediction.split(" — ")[0].strip()
            if group:
                prediction = f"{group} · {prediction}"
        elif group:
            prediction = group
        rows.append({"label": label, "context": date, "prediction": prediction})

    # Recent results with prediction grading (✓/✗) and the model record.
    # Budget: ~3 match rows + section labels + record bar fit the card.
    from pitch_agent.fixtures import get_finished_matches
    results_limit = max(1, 3 - len(rows))
    finished = get_finished_matches(db_path=db_path, limit=results_limit)
    recap = _build_match_recap_data(finished, db_path) if finished else {}

    return {
        "fixtures": rows,
        "results": recap.get("matches", []),
        "model_record": recap.get("model_record", ""),
    }


def _match_prediction(fixture: dict[str, Any]) -> str | None:
    """Return a one-line Poisson prediction for a fixture, or None.

    Uses blended xG (Elo prior → Form Index) per-team when FI data is
    available, and pure Elo prior when it isn't. Returns None only if
    neither source has data. Never falls back to team_result-derived
    numbers.
    """
    from pitch_agent.poisson import (
        form_index_to_xg, top_scorelines, match_outcome_probs,
        prediction_key_factor, elo_to_xg, predict_xg, resolve_predicted_outcome,
    )

    match_id = fixture.get("match_id") or fixture.get("id") or ""
    home_team = fixture.get("home_team_name", "")
    away_team = fixture.get("away_team_name", "")
    home_team_id = fixture.get("home_team_id", "") or ""
    away_team_id = fixture.get("away_team_id", "") or ""

    # Try to get data from the DB
    try:
        from pitch_agent.db import get_connection, get_team_prior, count_team_matches
        from pitch_agent.config import PitchAgentConfig
        cfg = PitchAgentConfig.load()
        conn = get_connection(cfg.db_path)
    except Exception:
        import sys
        print("[pitch_agent] Could not connect to DB for match prediction", file=sys.stderr)
        return None

    try:
        # Get average Form Index for each team
        rows = conn.execute(
            """
            SELECT p.team_name, AVG(s.score) as avg_score
            FROM form_index_scores s
            JOIN player_match_stats p ON s.match_id = p.match_id AND s.player_id = p.player_id
            WHERE s.model_version = ? AND (p.team_name = ? OR p.team_name = ?)
            GROUP BY p.team_name
            """,
            (MODEL_VERSION, home_team, away_team),
        ).fetchall()

        fi_map = {row["team_name"]: float(row["avg_score"]) for row in rows}
        home_avg_fi = fi_map.get(home_team)
        away_avg_fi = fi_map.get(away_team)

        # Get Elo priors (lookup by team_id first, then team_name)
        home_prior = get_team_prior(conn, home_team_id) if home_team_id else None
        if not home_prior:
            home_prior = get_team_prior(conn, home_team)
        away_prior = get_team_prior(conn, away_team_id) if away_team_id else None
        if not away_prior:
            away_prior = get_team_prior(conn, away_team)
        home_elo = home_prior["elo"] if home_prior else None
        away_elo = away_prior["elo"] if away_prior else None

        # Per-team match counts
        home_matches = count_team_matches(conn, home_team)
        away_matches = count_team_matches(conn, away_team)

        # Skip if no data at all
        if home_avg_fi is None and away_avg_fi is None and home_elo is None and away_elo is None:
            import sys
            print(
                f"[pitch_agent] No FI or Elo data for {home_team} vs {away_team} — prediction skipped",
                file=sys.stderr,
            )
            return None

        # Team missing from team_priors at n=0 → skip, not baseline
        if home_elo is None and home_avg_fi is None:
            import sys
            print(
                f"[pitch_agent] No Elo prior or FI for {home_team} — skipping",
                file=sys.stderr,
            )
            return None
        if away_elo is None and away_avg_fi is None:
            import sys
            print(
                f"[pitch_agent] No Elo prior or FI for {away_team} — skipping",
                file=sys.stderr,
            )
            return None

        # Compute blended xG (per-team)
        home_xg, away_xg, basis_home, basis_away = predict_xg(
            home_team=home_team,
            away_team=away_team,
            home_avg_fi=home_avg_fi,
            away_avg_fi=away_avg_fi,
            home_elo=home_elo,
            away_elo=away_elo,
            home_matches=home_matches,
            away_matches=away_matches,
            host_nations=cfg.host_nations,
            host_team_ids=cfg.host_team_ids,
        )

        outcomes = match_outcome_probs(home_xg, away_xg)
        top = top_scorelines(home_xg, away_xg, n=1)

        # Determine host advantage for key_factor disclosure
        host_nations_set = set(cfg.host_nations)
        host_team_ids_set = set(cfg.host_team_ids)
        is_home_advantage = (
            (home_team in host_nations_set or home_team in host_team_ids_set)
            and away_team not in host_nations_set
            and away_team not in host_team_ids_set
        )

        # Team codes for key_factor display
        from pitch_agent.poisson import TEAM_CODES
        home_code = TEAM_CODES.get(home_team, "")
        away_code = TEAM_CODES.get(away_team, "")

        key_factor = prediction_key_factor(
            [{"score": home_avg_fi or 50, "goals": 0}],
            [{"score": away_avg_fi or 50, "goals": 0}],
            home_elo=home_elo,
            away_elo=away_elo,
            basis_home=basis_home,
            basis_away=basis_away,
            home_code=home_code,
            away_code=away_code,
            is_host_advantage=is_home_advantage,
        )

        # Most likely outcome (with tie-breaking)
        predicted_outcome = resolve_predicted_outcome(outcomes, top[0])
        outcome_label = {"home": "Home win", "draw": "Draw", "away": "Away win"}[predicted_outcome]
        outcome_prob = {
            "home": outcomes["home_win"],
            "draw": outcomes["draw"],
            "away": outcomes["away_win"],
        }[predicted_outcome]

        # Basis label: collapse common cases
        basis_label_map = {
            "elo_prior": "pre-tournament Elo",
            "blended": "blended: Elo + early form",
            "form_index": "Form Index",
        }
        # Both sides same basis → single label
        if basis_home == basis_away:
            basis_tag = f" ({basis_label_map[basis_home]})"
        else:
            home_b = basis_label_map.get(basis_home, basis_home)
            away_b = basis_label_map.get(basis_away, basis_away)
            basis_tag = f" (home {home_b}, away {away_b})"

        most_likely = top[0]
        pct = outcome_prob * 100
        # Tier the call by confidence — only headline a real edge.
        if outcome_prob >= CONFIDENT_PICK:
            head = f"🎯 Pick: {outcome_label} ({pct:.0f}%) · {most_likely['label']}"
        elif outcome_prob >= LEAN_PICK:
            head = f"Lean: {outcome_label} ({pct:.0f}%) · {most_likely['label']}"
        else:
            head = f"Too close to call · slight edge {outcome_label} ({pct:.0f}%)"
        pred_str = f"{head}{basis_tag} — {key_factor}"
        return pred_str
    except Exception:
        import sys
        print(f"[pitch_agent] Prediction error for {home_team} vs {away_team}", file=sys.stderr)
        return None
    finally:
        conn.close()


def _build_match_recap_data(finished_matches: list[dict[str, Any]], db_path: str = "pitch_agent.db") -> dict[str, Any]:
    """Build structured recap data for finished matches.

    Returns a dict with:
      text: str — the fan-mode text recap
      matches: list[dict] — structured per-match data for chart rendering
      model_record: str — the running model record line
    """
    if not finished_matches:
        return {
            "text": "No finished matches to recap yet.\n\n" + TRADEMARK_DISCLAIMER,
            "matches": [],
            "model_record": "",
        }

    from pitch_agent.db import get_connection, get_prediction_accuracy
    from pitch_agent.poisson import TEAM_CODES

    conn = get_connection(db_path)

    try:
        accuracy = get_prediction_accuracy(conn)
    except Exception:
        accuracy = {"total": 0, "correct": 0, "pct": 0.0,
                    "exact_correct": 0, "exact_gradable": 0, "exact_pct": 0.0,
                    "legacy_count": 0}

    lines = ["\U0001f3c1 Match Recap", ""]
    chart_matches = []

    for match in finished_matches:
        home = match["home_team_name"]
        away = match["away_team_name"]
        home_score = match["home_score"]
        away_score = match["away_score"]
        match_id = match["match_id"]

        # Determine actual outcome
        if home_score > away_score:
            result_line = f"{home} {home_score}-{away_score} {away}"
            actual_outcome = "home"
        elif away_score > home_score:
            result_line = f"{away} {away_score}-{home_score} {home}"
            actual_outcome = "away"
        else:
            result_line = f"{home} {home_score}-{away_score} {away} (Draw)"
            actual_outcome = "draw"

        # One-line result with group context
        context = _fixture_context(match)
        date = _short_date(match.get("date", ""))
        detail_parts = [p for p in (date, context) if p]
        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
        lines.append(f"\u2022 {result_line}{detail}")

        # Chart context string
        chart_context = ", ".join(detail_parts) if detail_parts else ""

        # Look for a journaled prediction for this match
        pred = conn.execute(
            "SELECT predicted_home, predicted_away, predicted_outcome, "
            "home_win_prob, draw_prob, away_win_prob, key_factor "
            "FROM predictions WHERE match_id = ? AND model_version = ?",
            (match_id, MODEL_VERSION),
        ).fetchone()

        chart_entry = {
            "label": result_line,
            "context": chart_context,
            "prediction": None,
            "key_factor": "",
            "no_pred": False,
        }

        if pred:
            # We have a journaled prediction -- render comparison
            pred_home = pred["predicted_home"]
            pred_away = pred["predicted_away"]
            pred_outcome = pred["predicted_outcome"]
            pred_hw = pred["home_win_prob"]
            pred_d = pred["draw_prob"]
            pred_aw = pred["away_win_prob"]
            key_factor = pred["key_factor"] or ""

            outcome_label = {"home": "Home win", "draw": "Draw", "away": "Away win"}[pred_outcome]
            prob = {"home": pred_hw, "draw": pred_d, "away": pred_aw}[pred_outcome]

            # Outcome correct?
            outcome_correct = pred_outcome == actual_outcome
            outcome_icon = "\u2713" if outcome_correct else "\u2717"

            # Exact score correct?
            exact_correct = (pred_home == home_score and pred_away == away_score)
            exact_icon = "\u2713" if exact_correct else "\u2717"

            pred_str = (
                f"Predicted: {outcome_label} ({prob*100:.0f}%), {pred_home}-{pred_away} "
                f"\u2014 Outcome {outcome_icon} | Score {exact_icon}"
            )
            lines.append(f"  {pred_str}")
            if key_factor:
                lines.append(f"  {key_factor}")

            chart_entry["prediction"] = pred_str
            chart_entry["key_factor"] = key_factor
        else:
            # No journaled prediction -- render score and context only
            lines.append("  (No prediction on record for this match)")
            chart_entry["no_pred"] = True

        chart_matches.append(chart_entry)
        lines.append("")

    # Running model record -- only journaled predictions count
    if accuracy["total"] > 0:
        record_line = (
            f"Model record: {accuracy['correct']}/{accuracy['total']} outcomes "
            f"({accuracy['pct']:.0f}%"
        )
        if accuracy["exact_gradable"] > 0:
            record_line += f", {accuracy['exact_correct']}/{accuracy['exact_gradable']} exact scores {accuracy['exact_pct']:.0f}%"
        record_line += ")"
        lines.append(record_line)
    else:
        record_line = "(Model record: 0 journaled predictions graded yet)"
        lines.append(record_line)

    lines.append("")
    lines.append(TRADEMARK_DISCLAIMER)
    conn.close()

    return {
        "text": "\n".join(lines),
        "matches": chart_matches,
        "model_record": record_line,
    }


def _generate_match_recap(finished_matches: list[dict[str, Any]], db_path: str = "pitch_agent.db") -> str:
    """Build post-match recaps for finished matches.

    For each FINISHED match with non-NULL scores:
    - If a journaled prediction exists, render the prediction vs actual
      result with checkmark/cross per dimension (outcome / exact score).
    - If no journaled prediction exists, render score and context only
      -- never present non-journaled numbers as model predictions.
    - Include the running model record from get_prediction_accuracy().
    """
    data = _build_match_recap_data(finished_matches, db_path)
    return data["text"]


def _fixture_context(fixture: dict[str, Any]) -> str:
    """Return a 'Group A' / stage label for a fixture when available."""
    group = str(fixture.get("group_name") or "").strip()
    if group:
        return group.replace("_", " ").title()
    stage = str(fixture.get("stage") or "").strip()
    if stage:
        return stage.replace("_", " ").title()
    return ""


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
        "model_version": MODEL_VERSION,
    }


def _generate_real_data_connected(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    """Builder update confirming real fixtures are connected and grade-ready."""
    provider = _fixture_provider(fixtures) or "football-data"
    return {
        "pillar": "real_data_connected",
        "summary": (
            "The Pitch Agent now pulls real World Cup fixtures from "
            f"{provider}.org and is ready to grade player performances with "
            "Form Index v1.1 once match results are available."
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
        "Keep the independent project note if it appears. Do not add calls to "
        "action, predictions, or money-related language.\n\n"
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
