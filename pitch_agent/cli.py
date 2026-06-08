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
    p_fix.add_argument("--provider", default=None,
                       help="Restrict to one provider (e.g. football-data). "
                            "Default prefers football-data when those rows exist.")
    p_fix.add_argument("--limit", type=int, default=10, help="Number of fixtures")
    p_fix.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_fix.set_defaults(func=cmd_fixtures)

    # ── predict ──────────────────────────────────────────────────────────
    p_pred = sub.add_parser("predict",
                            help="Generate educational match predictions (data-based model outlook)")
    p_pred.add_argument("--competition", default=None, help="Competition ID filter")
    p_pred.add_argument("--limit", type=int, default=10, help="Number of fixtures")
    p_pred.add_argument("--neutral", action="store_true",
                        help="Treat all venues as neutral (no home advantage)")
    p_pred.add_argument("--render", action="store_true", help="Render a prediction card PNG")
    p_pred.add_argument("--output", "-o", default=None, help="Output PNG path (with --render)")
    p_pred.add_argument("--save", action="store_true",
                        help="Save model predictions to the DB for later accuracy scoring")
    p_pred.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_pred.set_defaults(func=cmd_predict)

    # ── predict-accuracy ─────────────────────────────────────────────────
    p_acc = sub.add_parser("predict-accuracy",
                           help="Score saved model predictions against real results")
    p_acc.add_argument("--render", action="store_true", help="Render a scorecard PNG")
    p_acc.add_argument("--output", "-o", default=None, help="Output PNG path (with --render)")
    p_acc.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_acc.set_defaults(func=cmd_predict_accuracy)

    # ── project-group ────────────────────────────────────────────────────
    p_proj = sub.add_parser("project-group",
                            help="Project group standings (chance to advance) via simulation")
    p_proj.add_argument("--group", required=True,
                        help="Group label, e.g. 'A' or 'Group A'")
    p_proj.add_argument("--sims", type=int, default=10000, help="Number of simulations")
    p_proj.add_argument("--advance", type=int, default=2,
                        help="How many teams advance (top N)")
    p_proj.add_argument("--render", action="store_true", help="Render a projection card PNG")
    p_proj.add_argument("--output", "-o", default=None, help="Output PNG path (with --render)")
    p_proj.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_proj.set_defaults(func=cmd_project_group)

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
    p_chart.add_argument("--competition", default=None,
                         help="Competition ID filter (fixtures chart)")
    p_chart.add_argument("--provider", default=None,
                         help="Restrict the fixtures chart to one provider "
                              "(e.g. football-data). Default prefers football-data.")
    p_chart.add_argument("--limit", type=int, default=10, help="Number of entries")
    p_chart.add_argument("--output", "-o", default=None, help="Output PNG path")
    p_chart.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_chart.set_defaults(func=cmd_render_chart)

    # ── generate-content ─────────────────────────────────────────────────
    from pitch_agent.content import PILLARS
    p_content = sub.add_parser("generate-content", help="Generate content for a pillar")
    p_content.add_argument("--pillar",
        choices=list(PILLARS),
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
    p_content.add_argument("--send-telegram-review", action="store_true",
                           help="Send visible post and safe metadata to Telegram review")
    p_content.add_argument("--strict-telegram", action="store_true",
                           help="Fail if Telegram review is requested but cannot be sent")
    p_content.add_argument("--db", default="pitch_agent.db", help="Database path")
    p_content.set_defaults(func=cmd_generate_content)

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
                "model_version": "1.0.0-lite",
                "score": result["score"],
                "score_breakdown_json": json.dumps(result["breakdown"]),
            })
            count += 1
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
    from pitch_agent.fixtures import get_fixtures, normalize_stage_label

    fixtures = get_fixtures(
        db_path=args.db,
        competition_id=args.competition,
        limit=args.limit,
        provider_name=getattr(args, "provider", None),
    )
    if not fixtures:
        print("No fixtures found. Run `sync-data` first.")
        return 1

    print(f"\n🗓️  Upcoming Fixtures ({len(fixtures)})\n")
    print(f"{'Date':<12} {'Stage/Group':<16} {'Match':<34} {'Status':<10}")
    print("-" * 74)
    for fx in fixtures:
        context = (normalize_stage_label(fx.get("group_name"))
                   or normalize_stage_label(fx.get("stage")))
        date = str(fx.get("date") or "")[:10]
        print(f"{date:<12} {context[:16]:<16} {fx['match_label'][:34]:<34} "
              f"{(fx.get('status') or '')[:10]:<10}")
    print(f"\n{get_chart_footer()}")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    from pitch_agent.predict import (
        PREDICTION_DISCLAIMER, predict_upcoming, save_predictions,
    )

    predictions = predict_upcoming(
        db_path=args.db,
        competition_id=args.competition,
        limit=args.limit,
        neutral=args.neutral,
    )
    if not predictions:
        print("No upcoming fixtures to predict. Run `sync-data` first.")
        return 1

    print(f"\n🔮 World Cup Match Predictions ({len(predictions)})\n")
    print(f"{'Match':<34} {'Home%':>6} {'Draw%':>6} {'Away%':>6}  {'Score':>6}")
    print("-" * 64)
    for p in predictions:
        match = f"{p['home_team_name']} vs {p['away_team_name']}"
        print(f"{match[:34]:<34} {p['p_home']*100:>5.0f}% {p['p_draw']*100:>5.0f}% "
              f"{p['p_away']*100:>5.0f}%  {p['most_likely_score']:>6}")

    if args.save:
        n = save_predictions(predictions, db_path=args.db)
        print(f"\n💾 Saved {n} prediction(s) for later accuracy scoring.")

    if args.render:
        from pitch_agent.charts import render_prediction_chart
        out = render_prediction_chart(predictions, output_path=args.output, limit=args.limit)
        print(f"🖼️  Prediction card: {out}")

    print(f"\n{PREDICTION_DISCLAIMER}")
    return 0


def cmd_predict_accuracy(args: argparse.Namespace) -> int:
    from pitch_agent.predict import (
        PREDICTION_DISCLAIMER, accuracy_summary, score_predictions,
    )

    summary = accuracy_summary(db_path=args.db)
    if summary["n"] == 0:
        print("No scored predictions yet. Save predictions with "
              "`predict --save`, then sync results.")
        return 1

    print(f"\n📊 Prediction Accuracy\n")
    print(f"Predictions scored : {summary['n']}")
    print(f"Correct outcomes   : {summary['correct']} ({summary['accuracy']*100:.0f}%)")
    print(f"Brier score        : {summary['brier']:.3f}  (lower is better)")

    scored = score_predictions(db_path=args.db)
    print(f"\n{'Match':<34} {'Pred':>5} {'Actual':>7} {'Hit':>4}")
    print("-" * 54)
    for s in scored:
        match = f"{s['home_team_name']} vs {s['away_team_name']}"
        hit = "✅" if s["correct"] else "❌"
        print(f"{match[:34]:<34} {s['predicted_outcome']:>5} "
              f"{s['actual_outcome']:>7} {hit:>4}")

    if args.render:
        from pitch_agent.brand_template import generate_list_card_html
        rows = [{
            "label": f"{s['home_team_name']} vs {s['away_team_name']}",
            "col_a": f"{s['predicted_outcome']} → {s['actual_outcome']}",
            "col_b": "Correct" if s["correct"] else "Miss",
        } for s in scored]
        out = generate_list_card_html(
            "Prediction Accuracy",
            f"{summary['correct']}/{summary['n']} correct "
            f"({summary['accuracy']*100:.0f}%) • Poisson model",
            rows,
            args.output or "artifacts/pitch_agent/charts/prediction_accuracy.png",
            footer_text="BuildWithAbdallah.com | Educational predictions | Not betting advice | Not affiliated with FIFA",
        )
        print(f"🖼️  Scorecard card: {out}")

    print(f"\n{PREDICTION_DISCLAIMER}")
    return 0


def cmd_project_group(args: argparse.Namespace) -> int:
    from pitch_agent.predict import PREDICTION_DISCLAIMER, project_group
    from pitch_agent.fixtures import normalize_stage_label

    label = normalize_stage_label(args.group)
    projection = project_group(
        args.group, db_path=args.db, advance_count=args.advance, n_sims=args.sims,
    )
    if not projection:
        print(f"No matches found for {label}. Run `sync-data` first.")
        return 1

    print(f"\n📈 {label} — Projected Standings ({args.sims:,} sims)\n")
    print(f"{'Team':<24} {'Pts':>4} {'xPts':>6} {'Advance':>9} {'Win':>7}")
    print("-" * 54)
    for r in projection:
        print(f"{r['team'][:24]:<24} {r['current_points']:>4} {r['exp_points']:>6.1f} "
              f"{r['p_advance']*100:>7.0f}% {r['p_win_group']*100:>6.0f}%")

    if args.render:
        from pitch_agent.charts import render_group_projection_chart
        out = render_group_projection_chart(projection, label, output_path=args.output)
        print(f"\n🖼️  Projection card: {out}")

    print(f"\n{PREDICTION_DISCLAIMER}")
    return 0


def cmd_render_chart(args: argparse.Namespace) -> int:
    from pitch_agent.leaderboard import get_leaderboard
    from pitch_agent.charts import render_leaderboard_chart, render_fixtures_chart

    if args.type == "fixtures":
        from pitch_agent.fixtures import get_fixtures
        fixtures = get_fixtures(
            db_path=args.db,
            competition_id=getattr(args, "competition", None),
            limit=args.limit,
            provider_name=getattr(args, "provider", None),
        )
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
    return 0


def cmd_transparency(args: argparse.Namespace) -> int:
    print(get_methodology())
    print()
    print("Chart footer:")
    print(get_chart_footer())
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
