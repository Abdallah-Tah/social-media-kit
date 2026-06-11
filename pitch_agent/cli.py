"""The Pitch Agent CLI — independent World Cup analytics.

Usage:
    python -m pitch_agent.cli init-db
    python -m pitch_agent.cli sync-data --provider csv
    python -m pitch_agent.cli compute-index --all
    python -m pitch_agent.cli leaderboard --scope daily --limit 10
    python -m pitch_agent.cli leaderboard --scope daily --position DEF --limit 10
    python -m pitch_agent.cli render-chart --type leaderboard --scope daily
    python -m pitch_agent.cli render-chart --type position_leaderboard --position DEF
    python -m pitch_agent.cli generate-content --pillar form_index_update --mode fan_mode --dry-run
    python -m pitch_agent.cli transparency
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pitch_agent import MODEL_VERSION as CURRENT_MODEL_VERSION

from pitch_agent import __version__, TRADEMARK_DISCLAIMER
from pitch_agent.config import PitchAgentConfig, load_env
from pitch_agent.transparency import get_chart_footer, get_disclaimer, get_methodology

DEFAULT_ANTHROPIC_TEST_MODEL = "claude-3-5-haiku-latest"


def _normalise_chart_type(value: str) -> str:
    """Normalize chart type aliases while documenting the canonical names."""
    return value.replace("-", "_")


def _normalise_scope(value: str) -> str:
    """Normalize public scope aliases while documenting the canonical names."""
    normalized = value.replace("-", "_").lower()
    return "player_match" if normalized == "match" else normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pitch-agent",
        description="The Pitch Agent — independent World Cup analytics.",
    )
    parser.add_argument("--version", action="version", version=f"pitch-agent {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    # ── init-db ────────────────────────────────────────────────────────
    p_init = sub.add_parser("init-db", help="Initialize the SQLite database")
    p_init.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_init.set_defaults(func=cmd_init_db)

    # ── migrate-db ──────────────────────────────────────────────────────
    p_migrate = sub.add_parser("migrate-db",
                               help="Apply pending schema migrations to an existing DB")
    p_migrate.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_migrate.set_defaults(func=cmd_migrate_db)

    # ── sync-data ───────────────────────────────────────────────────────
    p_sync = sub.add_parser("sync-data", help="Sync match data from a provider")
    p_sync.add_argument("--provider", choices=["csv", "football-data", "api-football"],
                        default="csv", help="Data provider (default: csv)")
    p_sync.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_sync.add_argument("--competition", default=None, help="Competition ID to sync")
    p_sync.add_argument("--max-matches", type=int, default=10, dest="max_matches",
                        help="Max finished matches to fetch stats for per sync "
                             "(per-match providers only; protects API rate limits)")
    p_sync.set_defaults(func=cmd_sync_data)

    # ── compute-index ───────────────────────────────────────────────────
    p_compute = sub.add_parser("compute-index", help="Compute Form Index scores")
    p_compute.add_argument("--all", action="store_true", dest="compute_all",
                           help="Recompute all matches")
    p_compute.add_argument("--match", default=None, help="Compute for specific match ID")
    p_compute.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_compute.set_defaults(func=cmd_compute_index)

    # ── leaderboard ─────────────────────────────────────────────────────
    p_lb = sub.add_parser("leaderboard", help="Show Form Index leaderboard")
    p_lb.add_argument("--scope", type=_normalise_scope,
                      choices=["daily", "player_match", "tournament"],
                      default="daily",
                      help="Leaderboard scope: daily, player-match, or tournament")
    p_lb.add_argument("--position", choices=["FWD", "MID", "DEF", "GK"],
                      default=None, help="Filter by position")
    p_lb.add_argument("--match", default=None,
                      help="Match ID filter for player-match scope")
    p_lb.add_argument("--limit", type=int, default=10, help="Number of results")
    p_lb.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_lb.set_defaults(func=cmd_leaderboard)

    # ── fixtures ─────────────────────────────────────────────────────────
    p_fix = sub.add_parser("fixtures", help="Show stored upcoming fixtures")
    p_fix.add_argument("--competition", default=None, help="Competition ID filter")
    p_fix.add_argument("--limit", type=int, default=10, help="Number of fixtures")
    p_fix.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_fix.set_defaults(func=cmd_fixtures)

    # ── render-chart ─────────────────────────────────────────────────────
    p_chart = sub.add_parser("render-chart", help="Render a chart as PNG")
    p_chart.add_argument("--type", type=_normalise_chart_type,
                         choices=["leaderboard", "position_leaderboard", "fixtures"],
                         required=True, help="Chart type")
    p_chart.add_argument("--position", choices=["FWD", "MID", "DEF", "GK"],
                        default=None, help="Position filter (for position_leaderboard)")
    p_chart.add_argument("--scope", type=_normalise_scope,
                         choices=["daily", "player_match", "tournament"],
                         default="daily",
                         help="Leaderboard scope: daily, player-match, or tournament")
    p_chart.add_argument("--limit", type=int, default=10, help="Number of entries")
    p_chart.add_argument("--output", "-o", default=None, help="Output PNG path")
    p_chart.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_chart.set_defaults(func=cmd_render_chart)

    # ── generate-content ─────────────────────────────────────────────────
    p_content = sub.add_parser("generate-content", help="Generate content for a pillar")
    p_content.add_argument("--pillar",
        choices=[
            "form_index_update", "position_leaderboard", "player_spotlight",
            "team_form_report", "news_digest", "stat_of_the_day",
            "underdog_watch", "post_match_grades", "builder_update",
            "matchday_preview", "real_data_connected",
        ],
        required=True,
        help="Content pillar")
    p_content.add_argument("--mode", choices=["fan_mode", "builder_mode"],
                           default="fan_mode", help="Output mode")
    p_content.add_argument("--scope", type=_normalise_scope,
                           choices=["daily", "player_match", "tournament"],
                           default=None,
                           help="Optional leaderboard scope override")
    p_content.add_argument("--dry-run", action="store_true",
                           help="Print content without recording")
    p_content.add_argument("--use-ai", action="store_true",
                           help="Optionally rewrite template content with Anthropic")
    p_content.add_argument("--strict-ai", action="store_true",
                           help="Fail with exit code 1 if AI rewrite is requested but unavailable")
    p_content.add_argument("--send-telegram-review", action="store_true",
                           help="Send visible post and safe metadata to Telegram review")
    p_content.add_argument("--strict-telegram", action="store_true",
                           help="Fail if Telegram review is requested but cannot be sent")
    p_content.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_content.set_defaults(func=cmd_generate_content)

    # ── predict ────────────────────────────────────────────────────────────
    p_predict = sub.add_parser("predict", help="Generate Poisson scoreline prediction for a match")
    p_predict.add_argument("--match", required=True, help="Match ID to predict")
    p_predict.add_argument("--top", type=int, default=3, help="Number of top scorelines to show")
    p_predict.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_predict.set_defaults(func=cmd_predict)

    # ── recompute ────────────────────────────────────────────────────────
    p_recompute = sub.add_parser("recompute", help="Purge stale model versions and recompute Form Index")
    p_recompute.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_recompute.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    p_recompute.set_defaults(func=cmd_recompute)

    # ── accuracy ──────────────────────────────────────────────────────────
    p_accuracy = sub.add_parser("accuracy", help="Show prediction accuracy stats")
    p_accuracy.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_accuracy.add_argument("--model-version", default=CURRENT_MODEL_VERSION, help="Model version")
    p_accuracy.set_defaults(func=cmd_accuracy)

    # ── load-priors ───────────────────────────────────────────────────
    p_priors = sub.add_parser("load-priors", help="Load Elo priors from CSV")
    p_priors.add_argument("--csv", required=True, help="CSV file with team_id,team_name,elo columns")
    p_priors.add_argument("--source", default="manual", help="Source label for the Elo data")
    p_priors.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_priors.set_defaults(func=cmd_load_priors)

    # ── validate-priors ────────────────────────────────────────────────
    p_validate = sub.add_parser("validate-priors", help="List teams in upcoming fixtures missing a prior")
    p_validate.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_validate.set_defaults(func=cmd_validate_priors)

    # ── record-result ────────────────────────────────────────────────
    p_result = sub.add_parser("record-result", help="Set match result and grade predictions")
    p_result.add_argument("match_id", help="Match ID (e.g. 537327)")
    p_result.add_argument("home_score", type=int, help="Home team score")
    p_result.add_argument("away_score", type=int, help="Away team score")
    p_result.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_result.set_defaults(func=cmd_record_result)

    # ── transparency ────────────────────────────────────────────────────
    p_trans = sub.add_parser("transparency",
                              help="Show trademark and affiliation disclaimer")
    p_trans.set_defaults(func=cmd_transparency)

    # ── test-anthropic ──────────────────────────────────────────────────
    p_anthropic = sub.add_parser("test-anthropic",
                                 help="Test Anthropic credentials with one tiny request")
    p_anthropic.set_defaults(func=cmd_test_anthropic)

    return parser


# ── Command handlers ───────────────────────────────────────────────────────

def cmd_init_db(args: argparse.Namespace) -> int:
    from pitch_agent.db import init_db
    conn = init_db(args.db)
    conn.close()
    print(f"✓ Database initialized at {args.db}")
    return 0


def cmd_migrate_db(args: argparse.Namespace) -> int:
    from pitch_agent.db import migrate_db
    added = migrate_db(args.db)
    if added:
        print(f"✓ Migrated {args.db}: added column(s) {', '.join(added)}")
    else:
        print(f"✓ {args.db} is already up to date")
    return 0


def cmd_sync_data(args: argparse.Namespace) -> int:
    from pitch_agent.providers import ensure_registered, get_provider
    from pitch_agent.db import get_connection, upsert_match, upsert_player_match_stats

    # Load secrets so providers that need an API key (e.g. football-data) can
    # find it in config/secrets.env or ~/.config/**/secrets.env.
    load_env()

    # Apply any pending schema migrations so an older DB (e.g. a matches table
    # without the status/provider_name columns) does not silently skip rows.
    from pitch_agent.db import migrate_db
    added = migrate_db(args.db)
    if added:
        print(f"✓ Migrated database: added column(s) {', '.join(added)}")

    ensure_registered()
    provider = get_provider(args.provider)

    if args.provider == "csv":
        # CSV provider: sync competitions, matches, then all stats
        data_dir = None  # uses default
        from pitch_agent.providers.csv_provider import CSVProvider
        provider = CSVProvider(data_dir=data_dir)

    print(f"Syncing data from {args.provider} provider...")

    # Sync match metadata first so leaderboards can show match label, date,
    # and score movement. Providers without match metadata simply skip this.
    matches: list[dict] = []
    if hasattr(provider, "fetch_matches"):
        conn = get_connection(args.db)
        try:
            fetched = provider.fetch_matches(competition_id=args.competition)
        except Exception as exc:  # noqa: BLE001 — match metadata is best-effort
            fetched = []
            print(f"  (match metadata sync skipped: {exc})")
        for match in fetched:
            try:
                match.setdefault("provider_name", args.provider)
                # Store matches under the competition identifier the user synced
                # with (e.g. "WC") so `fixtures --competition WC` finds them.
                if args.competition:
                    match["competition_id"] = args.competition
                upsert_match(conn, match)
                matches.append(match)
            except Exception as exc:  # noqa: BLE001 — skip one bad row, keep the rest
                print(f"  (skipped match {match.get('match_id')}: {exc})")
        conn.commit()
        conn.close()
    if matches:
        print(f"✓ Synced {len(matches)} match metadata records from {args.provider}")

    # Fetch player-match stats.  CSV returns everything in one call; per-match
    # providers (e.g. football-data) are queried one finished match at a time.
    if args.provider == "csv":
        stats = provider.fetch_match_stats(match_id=args.competition)
        if not stats:
            stats = provider.fetch_match_stats(match_id=None)
    else:
        stats = _fetch_stats_for_finished_matches(provider, matches, args.max_matches)

    if not stats:
        if matches:
            # Fixtures exist but no results yet (e.g. before kickoff) — not an error.
            print("No finished matches to grade yet; fixtures synced, results pending.")
            return 0
        print(f"No data returned from {args.provider} provider.")
        return 1

    conn = get_connection(args.db)
    count = 0
    for record in stats:
        upsert_player_match_stats(conn, record)
        count += 1
    conn.commit()

    # Grade any predictions where match results are now known
    from pitch_agent.db import grade_predictions
    graded = grade_predictions(conn)
    if graded:
        print(f"✓ Graded {graded} prediction(s)")

    conn.close()

    print(f"✓ Synced {count} player-match stat records from {args.provider}")
    return 0


def _fetch_stats_for_finished_matches(
    provider: object,
    matches: list[dict],
    max_matches: int,
) -> list[dict]:
    """Fetch player-match stats for finished matches, most recent first.

    Per-match providers (e.g. football-data) require one request per match, so
    we only query matches that already have a result and cap the count to stay
    within API rate limits.
    """
    finished = [m for m in matches if m.get("home_score") is not None]
    finished.sort(key=lambda m: str(m.get("date", "")), reverse=True)
    if max_matches and max_matches > 0:
        finished = finished[:max_matches]

    records: list[dict] = []
    for match in finished:
        match_id = match.get("match_id")
        try:
            records.extend(provider.fetch_match_stats(match_id=match_id))
        except Exception as exc:  # noqa: BLE001 — one bad match shouldn't abort the sync
            print(f"  (stats skipped for match {match_id}: {exc})")
    if finished:
        print(f"  Fetched stats for {len(finished)} finished match(es)")
    return records


def cmd_compute_index(args: argparse.Namespace) -> int:
    from pitch_agent.form_index import compute_all

    if not args.compute_all and not args.match:
        print("Specify --all or --match MATCH_ID")
        return 1

    if args.compute_all:
        count = compute_all(db_path=args.db)
        print(f"✓ Computed Form Index for {count} player-match records")
    else:
        # Single match computation
        import sqlite3
        from pitch_agent.form_index import compute_form_index
        from pitch_agent.db import get_connection, upsert_form_index

        conn = get_connection(args.db)
        rows = conn.execute(
            "SELECT * FROM player_match_stats WHERE match_id = ?",
            (args.match,),
        ).fetchall()
        count = 0
        for row in rows:
            result = compute_form_index(dict(row))
            upsert_form_index(conn, {
                "match_id": args.match,
                "player_id": row["player_id"],
                "model_version": CURRENT_MODEL_VERSION,
                "score": result["score"],
                "score_breakdown_json": json.dumps(result["breakdown"]),
            })
            count += 1
        conn.commit()
        conn.close()
        print(f"✓ Computed Form Index for {count} players in match {args.match}")

    return 0


def cmd_leaderboard(args: argparse.Namespace) -> int:
    from pitch_agent.leaderboard import get_leaderboard

    results = get_leaderboard(
        db_path=args.db,
        position=args.position,
        limit=args.limit,
        scope=args.scope,
        match_id=args.match,
    )

    if not results:
        print("No Form Index scores found. Run `compute-index` first.")
        return 1

    pos_label = f" ({args.position})" if args.position else ""
    scope_label = args.scope.replace("_", "-")
    print(f"\n🏆 Form Index Leaderboard [{scope_label}]{pos_label}\n")
    print(f"{'Rank':<5} {'Player':<25} {'Team':<20} {'Pos':<5} {'Score':>8}")
    print("-" * 65)
    for r in results:
        print(f"{r['rank']:<5} {r['player_name']:<25} {r['team_name']:<20} "
              f"{r['position']:<5} {r['score']:>8.1f}")
    print(f"\n{get_chart_footer()}")
    return 0


def cmd_fixtures(args: argparse.Namespace) -> int:
    from pitch_agent.fixtures import get_fixtures

    fixtures = get_fixtures(
        db_path=args.db,
        competition_id=args.competition,
        limit=args.limit,
    )
    if not fixtures:
        print("No fixtures found. Run `sync-data` first.")
        return 1

    print(f"\n🗓️  Upcoming Fixtures ({len(fixtures)})\n")
    print(f"{'Date':<12} {'Stage/Group':<16} {'Match':<34} {'Status':<10}")
    print("-" * 74)
    for fx in fixtures:
        context = (fx.get("group_name") or fx.get("stage") or "").replace("_", " ")
        date = str(fx.get("date") or "")[:10]
        print(f"{date:<12} {context[:16]:<16} {fx['match_label'][:34]:<34} "
              f"{(fx.get('status') or '')[:10]:<10}")
    print(f"\n{get_chart_footer()}")
    return 0


def cmd_render_chart(args: argparse.Namespace) -> int:
    from pitch_agent.leaderboard import get_leaderboard
    from pitch_agent.charts import render_leaderboard_chart, render_fixtures_chart

    if args.type == "fixtures":
        from pitch_agent.fixtures import get_fixtures
        fixtures = get_fixtures(db_path=args.db, limit=args.limit)
        if not fixtures:
            print("No fixtures found. Run `sync-data` first.")
            return 1
        output = render_fixtures_chart(fixtures, output_path=args.output, limit=args.limit)
        print(f"✓ Chart saved to {output}")
        return 0

    position = args.position if args.type == "position_leaderboard" else None
    results = get_leaderboard(
        db_path=args.db,
        position=position,
        limit=args.limit,
        scope=args.scope,
    )

    if not results:
        print("No Form Index scores found. Run `compute-index` first.")
        return 1

    provider_name = ""
    data_quality = "basic"
    as_of_date = str(results[0].get("match_date", "") or "")
    try:
        breakdown = json.loads(results[0].get("score_breakdown_json") or "{}")
        provider_name = breakdown.get("provider_name", "")
        data_quality = breakdown.get("data_quality_level", "basic") or "basic"
    except (ValueError, TypeError):
        pass

    output = render_leaderboard_chart(
        data=results,
        output_path=args.output,
        position=position,
        scope=args.scope,
        provider_name=provider_name,
        data_quality=data_quality,
        as_of_date=as_of_date,
    )
    print(f"✓ Chart saved to {output}")
    return 0


def cmd_generate_content(args: argparse.Namespace) -> int:
    from pitch_agent.content import generate_content

    config = PitchAgentConfig.load()
    result = generate_content(
        pillar=args.pillar,
        mode=args.mode,
        db_path=args.db,
        dry_run=args.dry_run,
        headline_index_mode=config.headline_index_mode,
        leaderboard_scope=args.scope,
        send_telegram_review=args.send_telegram_review,
        strict_telegram=args.strict_telegram,
        use_ai=getattr(args, "use_ai", False),
    )
    if (
        args.strict_telegram
        and args.send_telegram_review
        and result.get("telegram_review", {}).get("strict_failure")
    ):
        return 1
    if getattr(args, 'strict_ai', False) and getattr(args, "use_ai", False):
        ai = result.get("ai_rewrite", {})
        if ai and not ai.get("used", True) and ai.get("warning"):
            import sys
            print(f"Strict-ai: AI rewrite failed: {ai['warning']}", file=sys.stderr)
            return 1
    return 0


def cmd_transparency(args: argparse.Namespace) -> int:
    print(get_methodology())
    print()
    print("Chart footer:")
    print(get_chart_footer())
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    """Generate a Poisson scoreline prediction for a match."""
    from pitch_agent.db import get_connection, upsert_prediction, get_team_prior, count_team_matches
    from pitch_agent.poisson import (
        form_index_to_xg, top_scorelines, match_outcome_probs,
        prediction_key_factor, elo_to_xg, predict_xg, resolve_predicted_outcome,
    )
    from pitch_agent.leaderboard import get_match_leaderboard

    conn = get_connection(args.db)

    match = conn.execute(
        "SELECT home_team_name, away_team_name, home_team_id, away_team_id FROM matches WHERE match_id = ?",
        (args.match,),
    ).fetchone()
    if not match:
        print(f"Match {args.match} not found")
        conn.close()
        return 1

    home_team = match["home_team_name"]
    away_team = match["away_team_name"]
    home_team_id = match.get("home_team_id", "") or ""
    away_team_id = match.get("away_team_id", "") or ""

    # Fetch Form Index scores for both teams in this match
    rows = conn.execute(
        """
        SELECT s.player_id, s.score, p.team_id, p.team_name, p.position,
               p.goals, p.assists, p.minutes, p.team_result
        FROM form_index_scores s
        JOIN player_match_stats p
            ON s.match_id = p.match_id AND s.player_id = p.player_id
        WHERE s.match_id = ? AND s.model_version = ?
        """,
        (args.match, CURRENT_MODEL_VERSION),
    ).fetchall()

    # Separate home and away teams
    home_team_db_id = rows[0]["team_id"] if rows else None
    home_scores = [dict(r) for r in rows if r["team_id"] == home_team_db_id] if home_team_db_id else []
    away_scores = [dict(r) for r in rows if r["team_id"] != home_team_db_id] if home_team_db_id else []

    # If we can't split by team, use all scores as home
    if not away_scores and home_scores:
        away_scores = home_scores[len(home_scores)//2:]
        home_scores = home_scores[:len(home_scores)//2]

    home_avg = sum(r["score"] for r in home_scores) / len(home_scores) if home_scores else None
    away_avg = sum(r["score"] for r in away_scores) / len(away_scores) if away_scores else None

    # Fetch Elo priors
    home_prior = get_team_prior(conn, home_team_id) if home_team_id else None
    away_prior = get_team_prior(conn, away_team_id) if away_team_id else None
    home_elo = home_prior["elo"] if home_prior else None
    away_elo = away_prior["elo"] if away_prior else None

    # Count tournament matches played by each team
    home_matches = count_team_matches(conn, home_team)
    away_matches = count_team_matches(conn, away_team)

    # Load host nations and team IDs from config
    from pitch_agent.config import PitchAgentConfig as _PAC
    cfg = _PAC.load()
    host_nations = cfg.host_nations
    host_team_ids = cfg.host_team_ids

    # Compute blended xG (per-team)
    home_xg, away_xg, basis_home, basis_away = predict_xg(
        home_team=home_team,
        away_team=away_team,
        home_avg_fi=home_avg,
        away_avg_fi=away_avg,
        home_elo=home_elo,
        away_elo=away_elo,
        home_matches=home_matches,
        away_matches=away_matches,
        host_nations=host_nations,
        host_team_ids=host_team_ids,
    )

    outcomes = match_outcome_probs(home_xg, away_xg)
    top = top_scorelines(home_xg, away_xg, n=args.top)
    key_factor = prediction_key_factor(
        home_scores if home_scores else [{"score": home_avg or 50, "goals": 0}],
        away_scores if away_scores else [{"score": away_avg or 50, "goals": 0}],
    )

    # Most likely scoreline
    predicted_home = top[0]["home_goals"]
    predicted_away = top[0]["away_goals"]

    # Most likely outcome (argmax with tie-breaking)
    predicted_outcome = resolve_predicted_outcome(outcomes, top[0])
    outcome_label = {"home": "Home win", "draw": "Draw", "away": "Away win"}[predicted_outcome]
    outcome_prob = {
        "home": outcomes["home_win"],
        "draw": outcomes["draw"],
        "away": outcomes["away_win"],
    }[predicted_outcome]

    # Basis labels for display
    basis_label_map = {"elo_prior": "pre-tournament Elo", "blended": "Elo+FI blend", "form_index": "Form Index"}
    home_basis_label = basis_label_map.get(basis_home, basis_home)
    away_basis_label = basis_label_map.get(basis_away, basis_away)
    # Combined basis for DB storage
    if basis_home == basis_away:
        basis = basis_home
    elif "elo_prior" in (basis_home, basis_away):
        basis = "blended"
    else:
        basis = basis_home

    print(f"Match: {home_team} vs {away_team}")
    if home_avg is not None and away_avg is not None:
        print(f"Home avg Form Index: {home_avg:.1f}  |  Away avg Form Index: {away_avg:.1f}")
    if home_elo is not None and away_elo is not None:
        print(f"Home Elo: {home_elo:.0f}  |  Away Elo: {away_elo:.0f}")
    print(f"Home xG: {home_xg:.2f} ({home_basis_label})  |  Away xG: {away_xg:.2f} ({away_basis_label})")
    print(f"Key factor: {key_factor}")
    print()
    print(f"Outcome probabilities:")
    print(f"  Home win: {outcomes['home_win']*100:.1f}%")
    print(f"  Draw:     {outcomes['draw']*100:.1f}%")
    print(f"  Away win: {outcomes['away_win']*100:.1f}%")
    print()
    print(f"Most likely outcome: {outcome_label} ({outcome_prob*100:.0f}%)")
    print(f"Most likely score:   {top[0]['label']}")
    if basis != "form_index":
        print(f"(pre-tournament Elo)")
    print()
    print(f"Top {args.top} scorelines:")
    for s in top:
        print(f"  {s['label']}: {s['probability']*100:.1f}%")

    # Store prediction in DB
    upsert_prediction(conn, {
        "match_id": args.match,
        "model_version": CURRENT_MODEL_VERSION,
        "predicted_home": predicted_home,
        "predicted_away": predicted_away,
        "predicted_outcome": predicted_outcome,
        "basis_home": basis_home,
        "basis_away": basis_away,
        "home_win_prob": outcomes["home_win"],
        "draw_prob": outcomes["draw"],
        "away_win_prob": outcomes["away_win"],
        "top_scorelines": top,
        "key_factor": key_factor,
    })
    conn.commit()

    # Grade any finished matches
    from pitch_agent.db import grade_predictions
    graded = grade_predictions(conn)
    conn.close()

    if graded:
        print(f"\n✓ Graded {graded} finished prediction(s)")

    print(f"\n✓ Prediction stored for match {args.match}")
    return 0


def cmd_recompute(args: argparse.Namespace) -> int:
    """Purge stale model versions and recompute Form Index with the current model."""
    from pitch_agent.db import get_connection
    from pitch_agent.form_index import compute_all, MODEL_VERSION as FORM_MODEL_VERSION

    conn = get_connection(args.db)

    # Count rows with old model versions
    stale_rows = conn.execute(
        "SELECT COUNT(*) FROM form_index_scores WHERE model_version != ?",
        (CURRENT_MODEL_VERSION,),
    ).fetchone()[0]
    stale_tournament = conn.execute(
        "SELECT COUNT(*) FROM tournament_form_index WHERE model_version != ?",
        (CURRENT_MODEL_VERSION,),
    ).fetchone()[0]

    total_stale = stale_rows + stale_tournament

    if total_stale == 0:
        print(f"No stale model versions found. All scores are {CURRENT_MODEL_VERSION}.")
        conn.close()
        return 0

    if args.dry_run:
        print(f"Would delete {stale_rows} form_index_scores rows and {stale_tournament} tournament_form_index rows with model_version != {CURRENT_MODEL_VERSION}")
        conn.close()
        return 0

    # Delete stale rows
    conn.execute(
        "DELETE FROM form_index_scores WHERE model_version != ?",
        (CURRENT_MODEL_VERSION,),
    )
    conn.execute(
        "DELETE FROM tournament_form_index WHERE model_version != ?",
        (CURRENT_MODEL_VERSION,),
    )
    conn.commit()
    print(f"✓ Purged {stale_rows} form_index_scores and {stale_tournament} tournament_form_index rows with old model versions.")
    conn.close()

    # Recompute with current model
    count = compute_all(db_path=args.db)
    print(f"✓ Recomputed {count} player-match scores with model version {CURRENT_MODEL_VERSION}")
    return 0


def cmd_accuracy(args: argparse.Namespace) -> int:
    """Show prediction accuracy stats."""
    from pitch_agent.db import get_connection, get_prediction_accuracy

    conn = get_connection(args.db)
    stats = get_prediction_accuracy(conn, model_version=args.model_version)
    conn.close()

    if stats["total"] == 0:
        print("No graded predictions yet. Use `predict --match MATCH_ID` first.")
        return 0

    print(f"Prediction accuracy ({args.model_version}):")
    print(f"  Outcome:  {stats['correct']}/{stats['total']} correct ({stats['pct']}%)")
    gradable = stats["exact_gradable"]
    legacy = stats["legacy_count"]
    if gradable > 0:
        print(f"  Exact score: {stats['exact_correct']}/{gradable} correct ({stats['exact_pct']}%)")
    else:
        print("  Exact score: no graded data yet")
    if legacy > 0:
        print(f"  ({legacy} predictions predate exact-score tracking)")
    return 0


def cmd_load_priors(args: argparse.Namespace) -> int:
    """Load Elo prior ratings from a CSV file into team_priors table."""
    import csv
    from pathlib import Path
    from pitch_agent.db import get_connection, upsert_team_prior

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        return 1

    conn = get_connection(args.db)
    count = 0
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = row.get("team_id", "").strip()
            team_name = row.get("team_name", "").strip()
            elo = float(row.get("elo", 1500))
            if not team_id:
                continue
            upsert_team_prior(conn, {
                "team_id": team_id,
                "team_name": team_name or team_id,
                "elo": elo,
                "source": args.source,
            })
            count += 1
    conn.commit()
    conn.close()
    print(f"✓ Loaded {count} team Elo priors from {csv_path.name}")
    return 0


def cmd_validate_priors(args: argparse.Namespace) -> int:
    """List teams in upcoming fixtures that lack a prior entry."""
    from pitch_agent.db import get_connection

    conn = get_connection(args.db)

    # Get all distinct team names from upcoming fixtures
    teams = conn.execute(
        """SELECT DISTINCT team_name FROM player_match_stats
        UNION
        SELECT DISTINCT home_team_name FROM matches
        UNION
        SELECT DISTINCT away_team_name FROM matches"""
    ).fetchall()
    team_names = {row[0] for row in teams if row[0]}

    # Get all team_ids from priors
    priors = conn.execute("SELECT team_id, team_name FROM team_priors").fetchall()
    prior_ids = {row[0] for row in priors}
    prior_names = {row[1] for row in priors}

    missing = []
    for name in sorted(team_names):
        if name not in prior_ids and name not in prior_names:
            missing.append(name)

    if not missing:
        print(f"✓ All {len(team_names)} teams have Elo priors.")
    else:
        print(f"⚠ {len(missing)} teams missing Elo priors:")
        for name in missing:
            print(f"  - {name}")

    conn.close()
    return 0


def cmd_test_anthropic(args: argparse.Namespace) -> int:
    result = test_anthropic_request()
    print(result["status"])
    print(f"model: {result['model']}")
    print(f"response: {result['response']}")
    return 0 if result["status"] == "success" else 1


def test_anthropic_request() -> dict[str, str]:
    """Make one tiny Anthropic request without ever printing the API key."""
    load_env()
    model = (
        os.environ.get("BWA_ANTHROPIC_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or DEFAULT_ANTHROPIC_TEST_MODEL
    )
    api_key = os.environ.get("BWA_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "status": "failure",
            "model": model,
            "response": "missing BWA_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY",
        }

    import requests

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 16,
                "messages": [
                    {"role": "user", "content": "Reply with exactly: OK"}
                ],
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "failure",
            "model": model,
            "response": f"request failed: {_safe_error_message(str(exc))}",
        }

    if resp.status_code >= 400:
        return {
            "status": "failure",
            "model": model,
            "response": f"HTTP {resp.status_code}: {_anthropic_error_message(resp)}",
        }

    try:
        payload = resp.json()
    except ValueError:
        return {
            "status": "failure",
            "model": model,
            "response": "invalid JSON response",
        }

    return {
        "status": "success",
        "model": str(payload.get("model") or model),
        "response": _anthropic_text(payload) or "(empty response)",
    }


def _anthropic_text(payload: dict) -> str:
    parts = []
    for item in payload.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(p for p in parts if p).strip()


def _anthropic_error_message(resp: object) -> str:
    try:
        payload = resp.json()
    except ValueError:
        return _safe_error_message(getattr(resp, "text", "") or "request failed")
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


def cmd_record_result(args: argparse.Namespace) -> int:
    """CLI handler for record-result: set match scores and status=FINISHED."""
    from pitch_agent.db import get_connection, record_match_result
    db_path = args.db
    conn = get_connection(db_path)
    try:
        result = record_match_result(conn, args.match_id, args.home_score, args.away_score)
        print(f"✓ Recorded result: {result['home_team']} {result['home_score']}-"
              f"{result['away_score']} {result['away_team']}")
        print(f"  Previous: {result['previous_home_score']}-{result['previous_away_score']} "
              f"({result['previous_status']})")
        print(f"  Predictions graded: {result['predictions_graded']}")
        return 0
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
