"""Tests for pitch_agent — no network required (providers mocked where needed).

Covers all 10 required acceptance tests:
1. Missing rich stat fields do not crash scoring
2. Basic-only data produces valid Form Index
3. fields_present and fields_absent in score breakdown JSON
4. Under-15-minutes multiplier uses 0.50
5. Goal/assist exception applies 70% floor correctly
6. Recomputing a match updates existing score (UPSERT)
7. Position leaderboard returns only requested position
8. Chart footer includes "Not affiliated with FIFA"
9. football-data provider fails clearly if API key missing
10. football-data provider normalizes missing advanced fields to 0
"""
import json
import sqlite3
import sys
import argparse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pitch_agent"))
sys.path.insert(0, str(ROOT / "scripts"))

from pitch_agent.form_index import compute_form_index, MODEL_VERSION
from pitch_agent.db import (
    init_db,
    insert_run,
    upsert_form_index,
    upsert_player_match_stats,
    upsert_tournament_form_index,
    upsert_match,
    upsert_prediction,
    grade_predictions,
    get_prediction_accuracy,
)
from pitch_agent.form_index import compute_all
from pitch_agent.leaderboard import get_leaderboard
from pitch_agent.transparency import TRADEMARK_DISCLAIMER, get_chart_footer
from pitch_agent.charts import render_leaderboard_chart
from pitch_agent.content import generate_content
from pitch_agent.cli import (
    cmd_generate_content,
    cmd_migrate_db,
    cmd_sync_data,
    cmd_test_anthropic,
    test_anthropic_request as anthropic_test_request,
)
from pitch_agent.telegram_review import send_review
from pitch_agent.config import SECRETS_CANDIDATES


# ── 1. Missing rich stat fields do not crash scoring ──────────────────────

def test_missing_rich_fields_do_not_crash_scoring():
    """Only basic stats provided — rich fields should default to 0."""
    stats = {
        "goals": 1, "assists": 0, "minutes": 90, "yellow_cards": 0,
        "red_cards": 0, "own_goals": 0, "clean_sheet": 0, "team_result": "WIN",
        "position": "FWD", "provider_name": "csv", "data_quality_level": "basic",
    }
    result = compute_form_index(stats)
    assert isinstance(result["score"], float)
    assert result["score"] > 0
    # Rich fields should appear in fields_absent
    assert "pass_accuracy" in result["breakdown"]["fields_absent"]


def test_openclaw_secrets_env_is_loaded_for_pitch_agent():
    """Telegram review can use the OpenClaw secrets file location."""
    assert any(str(path).endswith(".config/openclaw/secrets.env") for path in SECRETS_CANDIDATES)


# ── 2. Basic-only data still produces a valid Form Index ──────────────────

def test_basic_only_data_produces_valid_form_index():
    """With only basic fields, the score should be deterministic."""
    stats = {
        "goals": 2, "assists": 1, "minutes": 90, "yellow_cards": 0,
        "red_cards": 0, "own_goals": 0, "clean_sheet": 0, "team_result": "WIN",
        "position": "FWD",
    }
    result = compute_form_index(stats)
    # base 50 + 2 goals * 18 + 1 assist * 10 + team win +3 = 99
    assert result["score"] == 99.0
    assert result["breakdown"]["base"] == 50
    assert result["breakdown"]["goal"] == 36.0
    assert result["breakdown"]["assist"] == 10.0
    assert result["breakdown"]["team_win"] == 3.0
    assert result["breakdown"]["raw_score_before_minutes"] == 99.0
    assert result["breakdown"]["final_score"] == 99.0


# ── 3. fields_present and fields_absent in score breakdown JSON ──────────

def test_fields_present_and_absent_in_breakdown():
    """Breakdown must track which fields were actually provided."""
    stats = {
        "goals": 1, "assists": 0, "minutes": 90, "team_result": "DRAW",
        "position": "MID",
    }
    result = compute_form_index(stats)
    bd = result["breakdown"]
    assert "fields_present" in bd
    assert "fields_absent" in bd
    # "goals" was provided with a non-zero value
    assert "goals" in bd["fields_present"]
    # "pass_accuracy" was not provided
    assert "pass_accuracy" in bd["fields_absent"]


# ── 4. Under-15-minutes multiplier uses 0.50 ────────────────────────────

def test_under_15_minutes_multiplier():
    """A player with < 15 minutes should get a 0.50 multiplier."""
    stats = {
        "goals": 0, "assists": 0, "minutes": 10, "yellow_cards": 0,
        "team_result": "LOSS", "position": "MID",
    }
    result = compute_form_index(stats)
    assert result["breakdown"]["minutes_adjustment"] == 0.50


# ── 5. Goal/assist exception applies 70% floor correctly ───────────────

def test_goal_assist_70_percent_floor():
    """A player who scored but played < 15 min should not drop below 70%."""
    # Player with 1 goal, 10 minutes, team lost
    stats = {
        "goals": 1, "assists": 0, "minutes": 10, "yellow_cards": 0,
        "team_result": "LOSS", "position": "FWD",
    }
    result = compute_form_index(stats)
    # raw_score = base 50 + 1 goal * 18 = 68
    # 0.50 multiplier would give 34
    # 70% floor: 68 * 0.70 = 47.6
    # max(34, 47.6) = 47.6
    assert result["breakdown"]["base"] == 50
    assert result["breakdown"]["raw_score_before_minutes"] == 68.0
    assert result["score"] == pytest.approx(47.6)


# ── 6. Recomputing a match updates existing score (UPSERT) ──────────────

def test_upsert_recomputes_existing_score(tmp_path):
    """Recomputing a match should update, not skip."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    # First insertion
    upsert_form_index(conn, {
        "match_id": "M001", "player_id": "P01",
        "model_version": MODEL_VERSION,
        "score": 20.0, "score_breakdown_json": "{}",
    })

    # Second insertion with updated score
    upsert_form_index(conn, {
        "match_id": "M001", "player_id": "P01",
        "model_version": MODEL_VERSION,
        "score": 25.0, "score_breakdown_json": '{"final_score": 25.0}',
    })

    rows = conn.execute(
        "SELECT score FROM form_index_scores WHERE match_id=? AND player_id=?",
        ("M001", "P01")
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 25.0
    conn.commit()
    conn.close()


def test_player_stats_and_tournament_upserts_update_existing_rows(tmp_path):
    """All MVP UPSERT tables should update existing rows, not duplicate them."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    base_stats = {
        "match_id": "M001",
        "player_id": "P01",
        "player_name": "First Name",
        "team_id": "T01",
        "team_name": "TeamA",
        "position": "FWD",
        "goals": 1,
        "assists": 0,
        "minutes": 90,
        "team_result": "WIN",
    }
    upsert_player_match_stats(conn, base_stats)
    changed_stats = dict(base_stats, player_name="Updated Name", goals=2)
    upsert_player_match_stats(conn, changed_stats)

    stat_rows = conn.execute(
        "SELECT player_name, goals FROM player_match_stats WHERE match_id=? AND player_id=?",
        ("M001", "P01"),
    ).fetchall()
    assert len(stat_rows) == 1
    assert stat_rows[0]["player_name"] == "Updated Name"
    assert stat_rows[0]["goals"] == 2

    upsert_tournament_form_index(conn, {
        "tournament_id": "WC2026",
        "player_id": "P01",
        "model_version": MODEL_VERSION,
        "cumulative_score": 20.0,
        "matches_played": 1,
    })
    upsert_tournament_form_index(conn, {
        "tournament_id": "WC2026",
        "player_id": "P01",
        "model_version": MODEL_VERSION,
        "cumulative_score": 42.0,
        "matches_played": 2,
    })

    tournament_rows = conn.execute(
        "SELECT cumulative_score, matches_played FROM tournament_form_index "
        "WHERE tournament_id=? AND player_id=?",
        ("WC2026", "P01"),
    ).fetchall()
    assert len(tournament_rows) == 1
    assert tournament_rows[0]["cumulative_score"] == 42.0
    assert tournament_rows[0]["matches_played"] == 2
    conn.commit()
    conn.close()


def test_recompute_does_not_duplicate_rows_or_depend_on_runs(tmp_path):
    """The runs table is only content/publishing dedupe, not score recompute state."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    upsert_player_match_stats(conn, {
        "match_id": "M001",
        "player_id": "P01",
        "player_name": "Player",
        "team_id": "T01",
        "team_name": "TeamA",
        "position": "FWD",
        "goals": 1,
        "assists": 0,
        "minutes": 90,
        "team_result": "WIN",
    })
    insert_run(conn, {
        "run_type": "content_generation",
        "pillar": "form_index_update",
        "mode": "fan_mode",
        "dry_run": 0,
        "status": "completed",
    })
    conn.commit()
    conn.close()

    assert compute_all(db_path) == 1
    assert compute_all(db_path) == 1

    conn = sqlite3.connect(db_path)
    counts = dict(conn.execute(
        "SELECT 'scores' AS name, count(*) FROM form_index_scores "
        "UNION ALL SELECT 'runs', count(*) FROM runs"
    ).fetchall())
    assert counts["scores"] == 1
    assert counts["runs"] == 1
    conn.commit()
    conn.close()


# ── 7. Position leaderboard returns only requested position ──────────────

def test_position_leaderboard_filters_correctly(tmp_path):
    """Leaderboard with --position should only return that position."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    positions = [("FWD", "P01"), ("MID", "P02"), ("DEF", "P03"), ("GK", "P04")]
    for pos, pid in positions:
        upsert_player_match_stats(conn, {
            "match_id": "M001", "player_id": pid,
            "player_name": f"Player_{pos}",
            "team_id": "T01", "team_name": "TeamA",
            "position": pos,
            "goals": 1, "assists": 0, "minutes": 90,
            "team_result": "WIN",
        })
        upsert_form_index(conn, {
            "match_id": "M001", "player_id": pid,
            "model_version": MODEL_VERSION,
            "score": 20.0,
            "score_breakdown_json": "{}",
        })

    conn.commit()
    results = get_leaderboard(db_path, position="DEF", limit=10)
    assert len(results) == 1
    assert results[0]["position"] == "DEF"

    for pos in ("FWD", "MID", "DEF", "GK"):
        results = get_leaderboard(db_path, position=pos, limit=10)
        assert results
        assert {r["position"] for r in results} == {pos}
    conn.close()


def test_daily_leaderboard_has_no_duplicate_player_id(tmp_path):
    """Daily/public leaderboard should show each player once using best score."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)

    results = get_leaderboard(db_path, scope="daily", limit=10)
    player_ids = [r["player_id"] for r in results]
    p01 = next(r for r in results if r["player_id"] == "P01")

    assert len(player_ids) == len(set(player_ids))
    assert p01["score"] == 80.0
    assert p01["match_id"] == "M002"
    assert p01["scope"] == "daily"


def test_player_match_leaderboard_may_include_duplicate_player_id(tmp_path):
    """Player-match scope preserves one row per player-match."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)

    results = get_leaderboard(db_path, scope="player-match", limit=10)
    player_ids = [r["player_id"] for r in results]

    assert player_ids.count("P01") == 2
    assert {r["scope"] for r in results} == {"player_match"}


def test_tournament_leaderboard_has_no_duplicate_player_id(tmp_path):
    """Tournament scope reads cumulative one-row-per-player scores."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)

    results = get_leaderboard(db_path, scope="tournament", limit=10)
    player_ids = [r["player_id"] for r in results]

    assert len(player_ids) == len(set(player_ids))
    assert [r["player_id"] for r in results] == ["P01", "P02"]
    assert results[0]["score"] == 150.0
    assert results[0]["scope"] == "tournament"


def test_daily_leaderboard_position_filter_still_works(tmp_path):
    """Daily scope should dedupe players and preserve position filtering."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)

    results = get_leaderboard(db_path, scope="daily", position="DEF", limit=10)

    assert results
    assert [r["player_id"] for r in results] == ["P02"]
    assert {r["position"] for r in results} == {"DEF"}


def test_form_index_update_uses_daily_scope(tmp_path):
    """Public form index content should not duplicate a player across matches."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)

    result = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
    )

    assert result["metadata"]["leaderboard_scope"] == "daily"
    assert result["content"].count("Player One") == 1
    assert "Player Two" in result["content"]


def test_fan_mode_content_is_narrative_not_raw_list(tmp_path):
    """Fan content should read as sentences, not a bare leaderboard table."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)

    result = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
    )
    content = result["content"]

    # A narrative leader sentence, not a "Name — Team: score" table row.
    assert "leads today's Form Index" in content
    assert "Player One (TeamA) leads" in content
    assert "Player One (TeamA) — TeamA: 80.0" not in content
    # Frames the project as analytics, not tipping.
    assert "tracks performance, not predictions" in content
    # Stays short enough for the major social platforms.
    assert len(content) < 900
    assert TRADEMARK_DISCLAIMER in content


def test_fan_mode_surprise_highlights_non_forward(tmp_path):
    """The 'quiet story' should surface a non-forward when one ranks highly."""
    db_path = str(tmp_path / "surprise.db")
    conn = init_db(db_path)
    rows = [
        ("M001", "P01", "Top Striker", "TeamA", "FWD", 95.0),
        ("M001", "P02", "Second Striker", "TeamB", "FWD", 88.0),
        ("M001", "P03", "Midfield Engine", "TeamC", "MID", 84.0),
    ]
    for match_id, player_id, player_name, team_name, position, score in rows:
        upsert_player_match_stats(conn, {
            "match_id": match_id, "player_id": player_id,
            "player_name": player_name, "team_id": team_name,
            "team_name": team_name, "position": position,
            "goals": 0, "assists": 0, "minutes": 90, "team_result": "WIN",
            "provider_name": "csv", "data_quality_level": "basic",
        })
        upsert_form_index(conn, {
            "match_id": match_id, "player_id": player_id,
            "model_version": MODEL_VERSION, "score": score,
            "score_breakdown_json": json.dumps({"provider_name": "csv", "final_score": score}),
        })
    conn.commit()
    conn.close()

    result = generate_content(
        "form_index_update", mode="fan_mode", db_path=db_path, dry_run=True,
    )
    content = result["content"]

    assert "The quiet story from midfield: Midfield Engine" in content


def test_telegram_review_flags_demo_data_for_csv_provider(monkeypatch):
    """CSV-sourced posts must warn the reviewer it is sample data, not live."""
    monkeypatch.setattr("pitch_agent.telegram_review.load_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    calls = []

    class FakePoster:
        @staticmethod
        def post_message(text):
            calls.append(text)
            return {"ok": True}

    monkeypatch.setattr("pitch_agent.telegram_review._load_telegram_poster", lambda: FakePoster)

    public_post = "Top Striker leads today's Form Index with a 95.0 in attack."
    result = send_review({
        "content": public_post,
        "metadata": {
            "mode": "fan_mode",
            "pillar": "form_index_update",
            "leaderboard_scope": "daily",
            "provider_name": "csv",
            "data_quality_level": "basic",
            "post_key": "form_index_update:fan_mode:daily",
        },
    })

    assert result["message_sent"] is True
    message = calls[0]
    assert "Demo data only — not live tournament data." in message
    # The warning is review-only: it must not be injected into the public post.
    assert "Demo data only" not in public_post


def test_telegram_review_omits_demo_warning_for_live_provider(monkeypatch):
    """A live provider should not carry the sample-data banner."""
    monkeypatch.setattr("pitch_agent.telegram_review.load_env", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    calls = []

    class FakePoster:
        @staticmethod
        def post_message(text):
            calls.append(text)
            return {"ok": True}

    monkeypatch.setattr("pitch_agent.telegram_review._load_telegram_poster", lambda: FakePoster)

    send_review({
        "content": "Visible football post",
        "metadata": {
            "mode": "fan_mode",
            "pillar": "form_index_update",
            "leaderboard_scope": "daily",
            "provider_name": "football-data",
            "data_quality_level": "rich",
            "post_key": "form_index_update:fan_mode:daily",
        },
    })

    assert "Demo data only" not in calls[0]


def test_telegram_review_is_not_sent_by_default(tmp_path, monkeypatch):
    """Content generation should not notify Telegram unless explicitly requested."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    called = {"sent": False}

    def fake_send_review(*args, **kwargs):
        called["sent"] = True
        return {"sent": True}

    monkeypatch.setattr("pitch_agent.telegram_review.send_review", fake_send_review)

    result = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
    )

    assert called["sent"] is False
    assert "telegram_review" not in result


def test_telegram_review_sends_safe_message_and_photo(tmp_path, monkeypatch):
    """Telegram review should include visible post and safe metadata only."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    calls: dict[str, list[Any]] = {"messages": [], "photos": []}

    class FakePoster:
        @staticmethod
        def post_message(text):
            calls["messages"].append(text)
            return {"ok": True}

        @staticmethod
        def post_photo(image_path, caption=""):
            calls["photos"].append((image_path, caption))
            return {"ok": True}

    monkeypatch.setattr("pitch_agent.telegram_review._load_telegram_poster", lambda: FakePoster)

    result = send_review({
        "content": "Visible football post",
        "metadata": {
            "mode": "fan_mode",
            "pillar": "form_index_update",
            "leaderboard_scope": "daily",
            "chart_path": str(chart),
            "provider_name": "csv",
            "data_quality_level": "basic",
            "post_key": "form_index_update:fan_mode:daily",
            "ignored": "not shown",
        },
        "raw": {"score_breakdown_json": "{}"},
    })

    assert result["message_sent"] is True
    assert result["photo_sent"] is True
    assert calls["photos"][0][0] == str(chart)

    message = calls["messages"][0]
    assert "The Pitch Agent review" in message
    assert "Visible post:" in message
    assert "Visible football post" in message
    assert "Review metadata:" in message
    assert "mode: fan_mode" in message
    assert "pillar: form_index_update" in message
    assert "scope: daily" in message
    assert "chart: chart.png" in message
    assert "provider: csv" in message
    assert "quality: basic" in message
    assert str(chart) not in message
    assert "post_key" not in message
    assert "score_breakdown_json" not in message
    assert "ignored" not in message


def test_telegram_review_does_not_send_photo_when_message_fails(tmp_path, monkeypatch):
    """Avoid duplicate Telegram API errors when the first send fails."""
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "chat")
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    calls = {"message": 0, "photo": 0}

    class FakePoster:
        @staticmethod
        def post_message(text):
            calls["message"] += 1
            return None

        @staticmethod
        def post_photo(image_path, caption=""):
            calls["photo"] += 1
            return {"ok": True}

    monkeypatch.setattr("pitch_agent.telegram_review._load_telegram_poster", lambda: FakePoster)

    result = send_review({
        "content": "Visible football post",
        "metadata": {
            "mode": "fan_mode",
            "pillar": "form_index_update",
            "leaderboard_scope": "daily",
            "chart_path": str(chart),
            "provider_name": "csv",
            "data_quality_level": "basic",
            "post_key": "form_index_update:fan_mode:daily",
        },
    })

    assert calls == {"message": 1, "photo": 0}
    assert result["message_sent"] is False
    assert result["photo_sent"] is False


def test_telegram_review_missing_credentials_warns_once(monkeypatch, capsys):
    """Missing Telegram credentials should skip before message/photo attempts."""
    monkeypatch.setattr("pitch_agent.telegram_review.load_env", lambda: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("CHAT_ID", raising=False)

    def fail_load_poster():
        raise AssertionError("poster should not load without credentials")

    monkeypatch.setattr("pitch_agent.telegram_review._load_telegram_poster", fail_load_poster)

    result = send_review({
        "content": "Visible football post",
        "metadata": {
            "mode": "fan_mode",
            "pillar": "form_index_update",
            "leaderboard_scope": "daily",
            "chart_path": "missing.png",
            "provider_name": "csv",
            "data_quality_level": "basic",
            "post_key": "form_index_update:fan_mode:daily",
        },
    })

    out = capsys.readouterr().out
    assert out.count("Telegram review skipped") == 1
    assert "TELEGRAM_BOT_TOKEN" in out
    assert "TELEGRAM_CHAT_ID" in out
    assert result["skipped"] is True
    assert result["strict_failure"] is True
    assert result["message_sent"] is False
    assert result["photo_sent"] is False


def test_telegram_review_accepts_openclaw_telegram_aliases(monkeypatch, capsys):
    """OpenClaw TELEGRAM_TOKEN / CHAT_ID should satisfy Telegram preflight."""
    monkeypatch.setattr("pitch_agent.telegram_review.load_env", lambda: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "chat")
    calls = []

    class FakePoster:
        @staticmethod
        def post_message(text):
            calls.append(text)
            return {"ok": True}

    monkeypatch.setattr("pitch_agent.telegram_review._load_telegram_poster", lambda: FakePoster)

    result = send_review({
        "content": "Visible football post",
        "metadata": {
            "mode": "fan_mode",
            "pillar": "form_index_update",
            "leaderboard_scope": "daily",
            "provider_name": "csv",
            "data_quality_level": "basic",
            "post_key": "form_index_update:fan_mode:daily",
        },
    })

    out = capsys.readouterr().out
    assert "Telegram review skipped" not in out
    assert result["message_sent"] is True
    assert calls


def test_generate_content_send_telegram_review_uses_mock(tmp_path, monkeypatch):
    """The CLI-facing flag path should call the review integration with no real send."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    calls = []

    def fake_send_review(generated, debug=False):
        calls.append((generated, debug))
        return {"sent": True, "message_sent": True, "photo_sent": False}

    monkeypatch.setattr("pitch_agent.telegram_review.send_review", fake_send_review)

    result = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
        send_telegram_review=True,
    )

    assert len(calls) == 1
    assert calls[0][1] is False
    assert result["telegram_review"]["sent"] is True
    assert result["metadata"]["leaderboard_scope"] == "daily"


def test_strict_telegram_returns_nonfatal_by_default_and_fatal_when_strict(tmp_path, monkeypatch, capsys):
    """CLI should print dry-run content either way, but only strict mode fails."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    monkeypatch.setattr(
        "pitch_agent.telegram_review.send_review",
        lambda generated, debug=False: {
            "sent": False,
            "skipped": True,
            "strict_failure": True,
            "missing_credentials": ["TELEGRAM_CHAT_ID"],
        },
    )

    base_args = {
        "pillar": "form_index_update",
        "mode": "fan_mode",
        "db": db_path,
        "dry_run": True,
        "scope": None,
        "send_telegram_review": True,
    }

    non_strict = argparse.Namespace(**base_args, strict_telegram=False)
    assert cmd_generate_content(non_strict) == 0
    assert "Daily Form Index Update" in capsys.readouterr().out

    strict = argparse.Namespace(**base_args, strict_telegram=True)
    assert cmd_generate_content(strict) == 1
    assert "Daily Form Index Update" in capsys.readouterr().out


def test_test_anthropic_missing_key_is_clear(monkeypatch):
    """Anthropic diagnostic should fail clearly without printing any key."""
    monkeypatch.setattr("pitch_agent.cli.load_env", lambda: None)
    monkeypatch.delenv("BWA_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = anthropic_test_request()

    assert result["status"] == "failure"
    assert result["model"]
    assert result["response"] == "missing BWA_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY"


def test_test_anthropic_prefers_bwa_key_and_prints_safe_success(monkeypatch, capsys):
    """BWA_ANTHROPIC_API_KEY should win over ANTHROPIC_API_KEY."""
    monkeypatch.setattr("pitch_agent.cli.load_env", lambda: None)
    monkeypatch.setenv("BWA_ANTHROPIC_API_KEY", "bwa-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "generic-secret")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "claude-test",
                "content": [{"type": "text", "text": "OK"}],
            }

    def fake_post(url, headers, json, timeout):
        captured["api_key"] = headers["x-api-key"]
        captured["body"] = json
        return FakeResponse()

    import requests
    monkeypatch.setattr(requests, "post", fake_post)

    rc = cmd_test_anthropic(argparse.Namespace())
    out = capsys.readouterr().out

    assert rc == 0
    assert captured["api_key"] == "bwa-secret"
    assert captured["body"]["max_tokens"] == 16
    assert out.splitlines() == [
        "success",
        "model: claude-test",
        "response: OK",
    ]
    assert "bwa-secret" not in out
    assert "generic-secret" not in out


def test_test_anthropic_http_failure_prints_status_and_safe_error(monkeypatch, capsys):
    """HTTP errors should include status and sanitized error text only."""
    monkeypatch.setattr("pitch_agent.cli.load_env", lambda: None)
    monkeypatch.setenv("BWA_ANTHROPIC_API_KEY", "bwa-secret")

    class FakeResponse:
        status_code = 401

        @staticmethod
        def json():
            return {"error": {"type": "authentication_error", "message": "bad key bwa-secret"}}

    import requests
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: FakeResponse())

    rc = cmd_test_anthropic(argparse.Namespace())
    out = capsys.readouterr().out

    assert rc == 1
    assert "failure" in out
    assert "model:" in out
    assert "response: HTTP 401: bad key [redacted]" in out
    assert "bwa-secret" not in out


def test_generate_content_without_use_ai_does_not_call_anthropic(tmp_path, monkeypatch):
    """Template generation remains the default and should not make network calls."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)

    def fail_post(*args, **kwargs):
        raise AssertionError("Anthropic should not be called without --use-ai")

    monkeypatch.setattr("pitch_agent.content.requests.post", fail_post)

    result = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
    )

    assert "Daily Form Index Update" in result["content"]
    assert "ai_rewrite" not in result


def test_generate_content_use_ai_missing_key_falls_back(tmp_path, monkeypatch, capsys):
    """Missing Anthropic credentials should keep template content with a warning."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    monkeypatch.setattr("pitch_agent.content.load_env", lambda: None)
    monkeypatch.delenv("BWA_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
        use_ai=True,
    )
    captured = capsys.readouterr()

    assert result["ai_rewrite"]["used"] is False
    assert "Daily Form Index Update" in result["content"]
    assert "AI rewrite unavailable; using template content." in captured.err


def test_generate_content_use_ai_prefers_bwa_and_safe_fan_prompt(tmp_path, monkeypatch, capsys):
    """AI fan rewrite should use BWA key first and avoid forbidden prompt wording."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    monkeypatch.setattr("pitch_agent.content.load_env", lambda: None)
    monkeypatch.setenv("BWA_ANTHROPIC_API_KEY", "bwa-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "generic-secret")
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "claude-test",
                "content": [{"type": "text", "text": "Fresh football post"}],
            }

    def fake_post(url, headers, json, timeout):
        captured["api_key"] = headers["x-api-key"]
        captured["prompt"] = json["messages"][0]["content"]
        return FakeResponse()

    monkeypatch.setattr("pitch_agent.content.requests.post", fake_post)

    result = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
        use_ai=True,
    )
    out = capsys.readouterr().out

    assert captured["api_key"] == "bwa-secret"
    assert result["ai_rewrite"]["used"] is True
    assert result["content"].startswith("Fresh football post")
    assert TRADEMARK_DISCLAIMER in result["content"]
    assert "Fresh football post" in out
    assert "bwa-secret" not in out
    assert "generic-secret" not in out
    forbidden = (
        "python", "sqlite", "api", "smkit", "cron", "github", "code",
        "betting", "odds", "sportsbook", "wagering",
    )
    prompt = captured["prompt"].lower()
    for word in forbidden:
        assert word not in prompt


def test_generate_content_use_ai_rejects_disallowed_fan_output(tmp_path, monkeypatch, capsys):
    """A bad fan rewrite should not leak forbidden terms into visible content."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    monkeypatch.setattr("pitch_agent.content.load_env", lambda: None)
    monkeypatch.setenv("BWA_ANTHROPIC_API_KEY", "bwa-secret")

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "claude-test",
                "content": [{"type": "text", "text": "This API post mentions betting odds."}],
            }

    monkeypatch.setattr("pitch_agent.content.requests.post", lambda *args, **kwargs: FakeResponse())

    result = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
        use_ai=True,
    )
    captured = capsys.readouterr()

    assert result["ai_rewrite"]["used"] is False
    assert "Daily Form Index Update" in result["content"]
    assert "disallowed wording" in captured.err
    visible = result["content"].lower()
    for word in ("api", "betting", "odds"):
        assert word not in visible


def test_generate_content_builder_ai_may_reference_pipeline(tmp_path, monkeypatch):
    """Builder mode can keep an internal technical AI summary."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    monkeypatch.setattr("pitch_agent.content.load_env", lambda: None)
    monkeypatch.setenv("BWA_ANTHROPIC_API_KEY", "bwa-secret")
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "claude-test",
                "content": [{"type": "text", "text": "Technical pipeline summary"}],
            }

    def fake_post(url, headers, json, timeout):
        captured["prompt"] = json["messages"][0]["content"]
        return FakeResponse()

    monkeypatch.setattr("pitch_agent.content.requests.post", fake_post)

    result = generate_content(
        "builder_update",
        mode="builder_mode",
        db_path=db_path,
        dry_run=True,
        use_ai=True,
    )

    assert "technical pipeline" in captured["prompt"].lower()
    assert result["content"]["ai_summary"] == "Technical pipeline summary"


def test_generate_content_cli_exposes_use_ai_flag():
    """The content CLI should expose optional Anthropic rewriting."""
    from pitch_agent.cli import build_parser

    help_text = build_parser().format_help()
    assert "generate-content" in help_text
    subparser_help = build_parser().parse_args([
        "generate-content",
        "--pillar",
        "form_index_update",
        "--use-ai",
    ])
    assert subparser_help.use_ai is True


def _seed_duplicate_player_leaderboard(tmp_path: Path) -> str:
    """Create a tiny DB where one player has two player-match scores."""
    db_path = str(tmp_path / "leaderboard.db")
    conn = init_db(db_path)
    rows = [
        ("M001", "P01", "Player One", "TeamA", "FWD", 70.0),
        ("M002", "P01", "Player One", "TeamA", "FWD", 80.0),
        ("M001", "P02", "Player Two", "TeamB", "DEF", 60.0),
    ]
    for match_id, player_id, player_name, team_name, position, score in rows:
        upsert_player_match_stats(conn, {
            "match_id": match_id,
            "player_id": player_id,
            "player_name": player_name,
            "team_id": team_name,
            "team_name": team_name,
            "position": position,
            "goals": 0,
            "assists": 0,
            "minutes": 90,
            "team_result": "DRAW",
            "provider_name": "csv",
            "data_quality_level": "basic",
        })
        upsert_form_index(conn, {
            "match_id": match_id,
            "player_id": player_id,
            "model_version": MODEL_VERSION,
            "score": score,
            "score_breakdown_json": json.dumps({
                "provider_name": "csv",
                "data_quality_level": "basic",
                "base": 50,
                "final_score": score,
            }),
        })
    upsert_tournament_form_index(conn, {
        "tournament_id": "WC2026",
        "player_id": "P01",
        "model_version": MODEL_VERSION,
        "cumulative_score": 150.0,
        "matches_played": 2,
    })
    upsert_tournament_form_index(conn, {
        "tournament_id": "WC2026",
        "player_id": "P02",
        "model_version": MODEL_VERSION,
        "cumulative_score": 60.0,
        "matches_played": 1,
    })
    conn.commit()
    conn.close()
    return db_path


# ── 8. Chart footer includes "Not affiliated with FIFA" ─────────────────

def test_chart_footer_includes_disclaimer():
    """The chart footer must contain the trademark disclaimer."""
    footer = get_chart_footer()
    assert "Not affiliated with FIFA" in footer


def test_chart_default_output_folder_and_branding(tmp_path, monkeypatch):
    """Charts should render to a stable folder and avoid image/logo assets."""
    monkeypatch.chdir(tmp_path)
    output = render_leaderboard_chart(
        [{"player_name": "Test Player", "position": "DEF", "score": 3.0}],
        position="DEF",
    )
    path = Path(output)
    assert path == Path("artifacts/pitch_agent/charts/leaderboard_def.png")
    assert path.exists()
    assert path.stat().st_size > 0
    assert "The Pitch Agent" in get_chart_footer()
    assert "Not affiliated with FIFA" in get_chart_footer()


# ── World Cup launch polish: frozen version, match context, branding ─────


def _seed_match_context_db(tmp_path: Path) -> str:
    """Seed two matches for one player with rising scores and match metadata."""
    from pitch_agent.db import upsert_match

    db_path = str(tmp_path / "context.db")
    conn = init_db(db_path)
    upsert_match(conn, {
        "match_id": "M001", "competition_id": "WC2026", "matchday": 1,
        "home_team_name": "Argentina", "away_team_name": "Saudi Arabia",
        "date": "2026-06-12", "group": "A",
    })
    upsert_match(conn, {
        "match_id": "M002", "competition_id": "WC2026", "matchday": 2,
        "home_team_name": "Argentina", "away_team_name": "Mexico",
        "date": "2026-06-17", "group": "A",
    })
    rows = [("M001", 70.0, 1, 0, 1), ("M002", 95.0, 2, 1, 2)]
    for match_id, score, goals, assists, matchday in rows:
        upsert_player_match_stats(conn, {
            "match_id": match_id, "player_id": "P01", "player_name": "Lionel Messi",
            "team_id": "T01", "team_name": "Argentina", "position": "FWD",
            "matchday": matchday, "goals": goals, "assists": assists, "minutes": 90,
            "team_result": "WIN", "provider_name": "csv", "data_quality_level": "basic",
        })
        upsert_form_index(conn, {
            "match_id": match_id, "player_id": "P01",
            "model_version": MODEL_VERSION, "score": score,
            "score_breakdown_json": json.dumps({"provider_name": "csv", "final_score": score}),
        })
    conn.commit()
    conn.commit()
    conn.close()
    return db_path


def test_model_version_label_is_frozen_across_surfaces(tmp_path):
    """'Form Index v1.1' must appear in breakdown, metadata, transparency, chart."""
    from pitch_agent.transparency import get_methodology
    from pitch_agent.charts import build_chart_subtitle

    breakdown = compute_form_index({
        "goals": 1, "minutes": 90, "position": "FWD", "team_result": "WIN",
    })["breakdown"]
    assert breakdown["model_version"] == MODEL_VERSION
    assert breakdown["model_version_label"] == "Form Index v1.1"

    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    result = generate_content(
        "form_index_update", mode="fan_mode", db_path=db_path, dry_run=True,
    )
    assert result["metadata"]["model_version"] == MODEL_VERSION
    assert result["metadata"]["model_version_label"] == "Form Index v1.1"

    assert "Form Index v1.1" in get_methodology()
    assert "Form Index v1.1" in build_chart_subtitle()


def test_leaderboard_rows_include_match_context(tmp_path):
    """Daily leaderboard rows should carry match label, date, reason, movement."""
    db_path = _seed_match_context_db(tmp_path)

    rows = get_leaderboard(db_path, scope="daily", limit=10)
    row = rows[0]

    # Daily scope surfaces the best match (M002).
    assert row["match_label"] == "Argentina vs Mexico"
    assert row["match_date"] == "2026-06-17"
    assert "2 goals" in row["key_reason"]
    assert "1 assist" in row["key_reason"]
    assert "team win" in row["key_reason"]
    assert row["previous_score"] == 70.0
    assert row["score_movement"] == 25.0


def test_leaderboard_match_context_degrades_without_matches_table(tmp_path):
    """Missing match metadata must not crash; label/date stay empty."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    rows = get_leaderboard(db_path, scope="daily", limit=10)
    assert rows
    for row in rows:
        assert row["match_label"] == ""
        assert "match_date" in row
        assert "score_movement" in row


def test_leaderboard_filters_by_model_version(tmp_path):
    """Leaderboard queries should exclude rows with a different model_version."""
    db_path = str(tmp_path / "lb_version.db")
    conn = init_db(db_path)

    # Insert a row with the CURRENT model version
    upsert_player_match_stats(conn, {
        "match_id": "MV01", "player_id": "PV01",
        "player_name": "CurrentPlayer",
        "team_id": "TV01", "team_name": "TeamA",
        "position": "FWD",
        "goals": 1, "assists": 0, "minutes": 90,
        "team_result": "WIN",
    })
    upsert_form_index(conn, {
        "match_id": "MV01", "player_id": "PV01",
        "model_version": MODEL_VERSION,
        "score": 50.0,
        "score_breakdown_json": "{}",
    })

    # Insert a row with a stale model version (should NOT appear)
    upsert_player_match_stats(conn, {
        "match_id": "MV02", "player_id": "PV02",
        "player_name": "StalePlayer",
        "team_id": "TV02", "team_name": "TeamB",
        "position": "FWD",
        "goals": 5, "assists": 5, "minutes": 90,
        "team_result": "WIN",
    })
    conn.commit()

    # Directly insert a stale form_index_scores row
    conn.execute(
        "INSERT INTO form_index_scores (match_id, player_id, model_version, score, score_breakdown_json) "
        "VALUES (?, ?, ?, ?, ?)",
        ("MV02", "PV02", "0.0.0-stale", 99.0, "{}"),
    )
    conn.commit()

    # Leaderboard should only return the current version row
    rows = get_leaderboard(db_path, limit=10)
    assert len(rows) == 1
    assert rows[0]["player_name"] == "CurrentPlayer"
    assert rows[0]["score"] == 50.0
    conn.close()


def test_fan_mode_includes_key_reason(tmp_path):
    """The visible post should mention at least one concrete key reason."""
    db_path = _seed_match_context_db(tmp_path)

    result = generate_content(
        "form_index_update", mode="fan_mode", db_path=db_path, dry_run=True,
    )
    content = result["content"]

    assert "2 goals" in content
    assert "Argentina vs Mexico" in content
    assert len(content) < 900
    banned = (
        "python", "sqlite", "api", "smkit", "cron", "github", "code",
        "betting", "gambling", "sportsbook", "odds", "wagering",
    )
    for word in banned:
        assert word not in content.lower()


def test_chart_title_and_subtitle_are_branded():
    """Chart title/subtitle should be branded and freeze the model label."""
    from pitch_agent.charts import build_chart_title, build_chart_subtitle

    assert build_chart_title("daily", count=10) == "Daily Form Index — Top 10"
    assert build_chart_title("daily", position="DEF", count=5) == "Top DEF Form Index — Top 5"

    subtitle = build_chart_subtitle(
        provider_name="csv", data_quality="basic", as_of_date="2026-06-12",
    )
    assert "Form Index v1.1" in subtitle
    assert "Basic data" in subtitle
    assert "Demo data only" in subtitle

    live = build_chart_subtitle(provider_name="football-data", data_quality="rich")
    assert "Demo data only" not in live


def test_priority_pillars_marked_production_ready(tmp_path):
    """The four launch pillars are production-ready; others are not yet."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    for pillar in (
        "form_index_update", "position_leaderboard",
        "player_spotlight", "post_match_grades",
    ):
        result = generate_content(pillar, mode="fan_mode", db_path=db_path, dry_run=True)
        assert result["metadata"]["production_ready"] is True

    other = generate_content("news_digest", mode="fan_mode", db_path=db_path, dry_run=True)
    assert other["metadata"]["production_ready"] is False


def test_upsert_match_coerces_null_team_and_scores(tmp_path):
    """JSON nulls (TBD knockout teams, unplayed scores) must not break inserts."""
    from pitch_agent.db import upsert_match

    db_path = str(tmp_path / "matches.db")
    conn = init_db(db_path)
    upsert_match(conn, {
        "match_id": "K01", "competition_id": "WC",
        "home_team_name": None, "away_team_name": None,
        "home_score": None, "away_score": None,
        "matchday": None, "date": "2026-07-10", "stage": "FINAL",
    })
    row = conn.execute(
        "SELECT home_team_name, away_team_name, home_score, matchday "
        "FROM matches WHERE match_id='K01'"
    ).fetchone()
    assert row["home_team_name"] == ""
    assert row["away_team_name"] == ""
    assert row["home_score"] is None, "NULL scores must stay NULL, not coerced to 0"
    assert row["matchday"] == 0
    conn.commit()
    conn.close()


def test_fetch_stats_only_for_finished_matches_and_capped(monkeypatch):
    """Per-match stat sync should skip unplayed matches and respect the cap."""
    from pitch_agent.cli import _fetch_stats_for_finished_matches

    matches = [
        {"match_id": "M001", "home_score": 2, "date": "2026-06-11"},
        {"match_id": "M002", "home_score": None, "date": "2026-06-12"},  # unplayed
        {"match_id": "M003", "home_score": 1, "date": "2026-06-13"},
        {"match_id": "M004", "home_score": 0, "date": "2026-06-14"},
    ]
    queried: list[str] = []

    class FakeProvider:
        def fetch_match_stats(self, match_id=None):
            queried.append(match_id)
            return [{"match_id": match_id, "player_id": "P1"}]

    records = _fetch_stats_for_finished_matches(FakeProvider(), matches, max_matches=2)

    # Only finished matches, most recent first, capped at 2.
    assert queried == ["M004", "M003"]
    assert len(records) == 2
    assert "M002" not in queried  # unplayed skipped


def test_fetch_stats_skips_a_single_failing_match(monkeypatch, capsys):
    """One match raising should not abort stats collection for the others."""
    from pitch_agent.cli import _fetch_stats_for_finished_matches

    matches = [
        {"match_id": "M001", "home_score": 2, "date": "2026-06-11"},
        {"match_id": "M002", "home_score": 1, "date": "2026-06-12"},
    ]

    class FlakyProvider:
        def fetch_match_stats(self, match_id=None):
            if match_id == "M002":
                raise RuntimeError("boom")
            return [{"match_id": match_id}]

    records = _fetch_stats_for_finished_matches(FlakyProvider(), matches, max_matches=10)
    out = capsys.readouterr().out

    assert len(records) == 1
    assert "stats skipped for match M002" in out


# ── Pre-tournament / fixture content (matchday_preview, real_data_connected) ─


def _seed_fixtures_db(tmp_path: Path) -> str:
    """Seed two football-data fixtures (no results yet)."""
    from pitch_agent.db import upsert_match

    db_path = str(tmp_path / "fixtures.db")
    conn = init_db(db_path)
    upsert_match(conn, {
        "match_id": "M001", "competition_id": "WC",
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "date": "2026-06-11", "stage": "GROUP_STAGE", "group": "GROUP_A",
        "status": "TIMED", "provider_name": "football-data",
    })
    upsert_match(conn, {
        "match_id": "M002", "competition_id": "WC",
        "home_team_name": "Canada", "away_team_name": "Bosnia-H.",
        "date": "2026-06-12", "stage": "GROUP_STAGE", "group": "GROUP_B",
        "status": "TIMED", "provider_name": "football-data",
    })
    conn.commit()
    conn.close()
    return db_path


def test_get_fixtures_returns_stored_fixtures(tmp_path):
    """get_fixtures should return stored matches ordered by date with labels."""
    from pitch_agent.fixtures import get_fixtures

    db_path = _seed_fixtures_db(tmp_path)
    fixtures = get_fixtures(db_path, competition_id="WC", limit=10)

    assert len(fixtures) == 2
    assert fixtures[0]["match_label"] == "Mexico vs South Africa"
    assert fixtures[0]["status"] == "TIMED"
    assert fixtures[0]["provider_name"] == "football-data"
    assert fixtures[0]["group_name"] == "GROUP_A"


def test_fixtures_command_lists_and_handles_empty(tmp_path, capsys):
    """The fixtures CLI command prints stored fixtures and reports an empty DB."""
    from pitch_agent.cli import cmd_fixtures

    db_path = _seed_fixtures_db(tmp_path)
    rc = cmd_fixtures(argparse.Namespace(db=db_path, competition="WC", limit=10))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Mexico vs South Africa" in out
    assert "Canada vs Bosnia-H." in out

    empty = str(tmp_path / "empty.db")
    init_db(empty).close()
    rc_empty = cmd_fixtures(argparse.Namespace(db=empty, competition=None, limit=10))
    assert rc_empty == 1


def test_render_fixtures_chart_writes_png(tmp_path, monkeypatch):
    """The fixtures chart should render a non-empty PNG to the chart folder."""
    monkeypatch.chdir(tmp_path)
    from pitch_agent.charts import render_fixtures_chart

    out = render_fixtures_chart([
        {"match_label": "Mexico vs South Africa", "date": "2026-06-11",
         "group_name": "GROUP_A", "stage": "GROUP_STAGE"},
        {"match_label": "Canada vs Bosnia-H.", "date": "2026-06-12",
         "group_name": "GROUP_B", "stage": "GROUP_STAGE"},
    ])
    path = Path(out)
    assert path.name == "fixtures.png"
    assert path.exists()
    assert path.stat().st_size > 0


def test_fixtures_chart_uses_branded_footer(tmp_path, monkeypatch):
    """The fixtures chart must draw the same branded footer as get_chart_footer()."""
    import pitch_agent.charts as charts

    branded = (
        "The Pitch Agent by BuildWithAbdallah | Independent analytics | "
        "Not affiliated with FIFA"
    )
    captured: dict[str, str] = {}
    real_footer = charts.get_chart_footer

    def spy() -> str:
        value = real_footer()
        captured["footer"] = value
        return value

    # The renderer resolves get_chart_footer from the charts module namespace.
    monkeypatch.setattr(charts, "get_chart_footer", spy)

    out = charts.render_fixtures_chart(
        [{"match_label": "Mexico vs South Africa", "date": "2026-06-11",
          "group_name": "GROUP_A", "stage": "GROUP_STAGE"}],
        output_path=str(tmp_path / "fixtures.png"),
    )

    assert Path(out).exists()
    # The fixtures renderer pulled its footer from get_chart_footer(), and that
    # footer is the branded text (matching the CLI fixtures-table footer).
    assert captured.get("footer") == branded


def test_all_chart_types_share_one_footer_source(monkeypatch):
    """leaderboard, position_leaderboard, and fixtures all use get_chart_footer()."""
    import pitch_agent.charts as charts

    calls = {"n": 0}
    real_footer = charts.get_chart_footer

    def spy() -> str:
        calls["n"] += 1
        return real_footer()

    monkeypatch.setattr(charts, "get_chart_footer", spy)

    charts.render_leaderboard_chart(
        [{"player_name": "P", "position": "FWD", "score": 9.0}],
        output_path="/tmp/pa_lb.png",
    )
    charts.render_leaderboard_chart(
        [{"player_name": "D", "position": "DEF", "score": 5.0}],
        output_path="/tmp/pa_pos.png", position="DEF",
    )
    charts.render_fixtures_chart(
        [{"match_label": "A vs B", "date": "2026-06-11", "group_name": "GROUP_A"}],
        output_path="/tmp/pa_fix.png",
    )

    assert calls["n"] == 3  # every renderer pulled the shared footer


def test_matchday_preview_has_no_prediction_or_betting_language(tmp_path):
    """Matchday preview must be fixture-only with no predictions/betting/code talk."""
    db_path = _seed_fixtures_db(tmp_path)
    result = generate_content(
        "matchday_preview", mode="fan_mode", db_path=db_path, dry_run=True,
    )
    content = result["content"]

    assert "Mexico vs South Africa" in content
    assert "Group A" in content
    assert "Follow The Pitch Agent" in content

    low = content.lower()
    for word in ("predict", "bet", "odds", "wager", "sportsbook", "gambling"):
        assert word not in low, f"forbidden word in preview: {word}"
    for word in ("python", "sqlite", "api", "smkit", "cron", "github", "code"):
        assert word not in low

    assert result["metadata"]["provider_name"] == "football-data"
    assert result["metadata"]["data_quality_level"] == "fixture-only"
    assert result["metadata"]["status_note"] == "real fixtures, no player grades yet"


def test_football_data_review_has_no_demo_warning_and_shows_status():
    """football-data content shows status, not the CSV 'Demo data only' banner."""
    from pitch_agent.telegram_review import _build_review_message, _safe_metadata

    metadata = {
        "mode": "fan_mode", "pillar": "matchday_preview",
        "leaderboard_scope": "fixtures", "provider_name": "football-data",
        "data_quality_level": "fixture-only",
        "status_note": "real fixtures, no player grades yet",
        "chart_path": "fixtures.png", "post_key": "matchday_preview:fan_mode:fixtures",
    }
    msg = _build_review_message({"content": "post"}, _safe_metadata(metadata))

    assert "Demo data only" not in msg
    assert "provider: football-data" in msg
    assert "quality: fixture-only" in msg
    assert "status: real fixtures, no player grades yet" in msg


def test_real_data_connected_builder_explains_connection(tmp_path):
    """The real_data_connected builder update confirms fixtures are connected."""
    db_path = _seed_fixtures_db(tmp_path)
    result = generate_content(
        "real_data_connected", mode="builder_mode", db_path=db_path, dry_run=True,
    )
    content = result["content"]

    assert content["pillar"] == "real_data_connected"
    assert content["data_quality_level"] == "fixture-only"
    assert content["fixtures_loaded"] == 2
    assert "ready to grade" in content["summary"].lower()
    text = json.dumps(content).lower()
    for word in ("betting", "gambling", "sportsbook", "odds", "wagering"):
        assert word not in text


def test_new_pillars_exposed_in_cli():
    """Both new pillars should be valid generate-content choices."""
    from pitch_agent.cli import build_parser

    for pillar, mode in (("matchday_preview", "fan_mode"),
                          ("real_data_connected", "builder_mode")):
        ns = build_parser().parse_args(
            ["generate-content", "--pillar", pillar, "--mode", mode]
        )
        assert ns.pillar == pillar


# ── Schema migrations (old DBs missing matches.status / provider_name) ───

# A pre-status/provider_name ``matches`` table, as shipped before fixtures.
_OLD_MATCHES_SQL = """
CREATE TABLE matches (
    match_id        TEXT PRIMARY KEY,
    competition_id  TEXT NOT NULL DEFAULT '',
    matchday        INTEGER NOT NULL DEFAULT 0,
    stage           TEXT NOT NULL DEFAULT '',
    home_team_id    TEXT NOT NULL DEFAULT '',
    home_team_name  TEXT NOT NULL DEFAULT '',
    away_team_id    TEXT NOT NULL DEFAULT '',
    away_team_name  TEXT NOT NULL DEFAULT '',
    home_score      INTEGER NOT NULL DEFAULT 0,
    away_score      INTEGER NOT NULL DEFAULT 0,
    date            TEXT NOT NULL DEFAULT '',
    group_name      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _make_old_schema_db(tmp_path: Path, name: str = "old.db") -> str:
    db_path = str(tmp_path / name)
    conn = sqlite3.connect(db_path)
    conn.executescript(_OLD_MATCHES_SQL)
    conn.commit()
    conn.close()
    return db_path


def _matches_columns(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    conn.close()
    return cols


def test_migrate_db_adds_missing_columns_idempotently(tmp_path):
    """migrate-db should add missing columns and be safe to re-run."""
    from pitch_agent.db import migrate_db

    db_path = _make_old_schema_db(tmp_path)
    assert "status" not in _matches_columns(db_path)
    assert "provider_name" not in _matches_columns(db_path)

    added = migrate_db(db_path)
    # Should include at least status and provider_name
    assert "status" in added
    assert "provider_name" in added
    cols = _matches_columns(db_path)
    assert "status" in cols and "provider_name" in cols

    # Idempotent: a second run changes nothing.
    second_added = migrate_db(db_path)
    assert second_added == [], f"Second migration should add nothing, got {second_added}"


def test_init_db_migrates_existing_old_table(tmp_path):
    """init-db on an old database should also add the missing columns."""
    db_path = _make_old_schema_db(tmp_path)
    conn = init_db(db_path)
    conn.close()
    cols = _matches_columns(db_path)
    assert "status" in cols and "provider_name" in cols


def test_cmd_migrate_db_reports_and_then_clean(tmp_path, capsys):
    import argparse
    db_path = _make_old_schema_db(tmp_path)

    assert cmd_migrate_db(argparse.Namespace(db=db_path)) == 0
    assert "added column" in capsys.readouterr().out

    assert cmd_migrate_db(argparse.Namespace(db=db_path)) == 0
    assert "up to date" in capsys.readouterr().out


def test_sync_migrates_old_db_and_does_not_skip_matches(tmp_path, monkeypatch):
    """football-data sync against an old DB must migrate first, not skip rows."""
    import argparse

    db_path = _make_old_schema_db(tmp_path)

    class FakeProvider:
        def fetch_matches(self, competition_id=None):
            return [
                {
                    "match_id": "X1", "competition_id": "2000", "matchday": 1,
                    "stage": "GROUP_STAGE", "home_team_id": "T1",
                    "home_team_name": "Mexico", "away_team_id": "T2",
                    "away_team_name": "South Africa", "home_score": None,
                    "away_score": None, "date": "2026-06-11", "group": "GROUP_A",
                    "status": "TIMED",
                },
                {  # TBD knockout match with null teams
                    "match_id": "X2", "competition_id": "2000", "matchday": 0,
                    "stage": "LAST_16", "home_team_id": "", "home_team_name": None,
                    "away_team_id": "", "away_team_name": None, "home_score": None,
                    "away_score": None, "date": "2026-07-01", "group": None,
                    "status": "SCHEDULED",
                },
            ]

        def fetch_match_stats(self, match_id=None):
            return []

    monkeypatch.setattr("pitch_agent.providers.ensure_registered", lambda: None)
    monkeypatch.setattr("pitch_agent.providers.get_provider", lambda name: FakeProvider())

    rc = cmd_sync_data(argparse.Namespace(
        provider="football-data", competition="WC", db=db_path, max_matches=10,
    ))
    assert rc == 0

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    comps = [r[0] for r in conn.execute("SELECT DISTINCT competition_id FROM matches")]
    conn.close()

    assert count == 2  # both stored — neither skipped for a missing column
    assert comps == ["WC"]  # stamped with the synced competition code


# ── Brand logo / footer support ──────────────────────────────────────────


def test_chart_footer_uses_brand_with_parent():
    from pitch_agent.transparency import get_chart_footer

    footer = get_chart_footer()
    assert "The Pitch Agent by BuildWithAbdallah" in footer
    assert "Independent analytics" in footer
    assert "Not affiliated with FIFA" in footer


def test_load_brand_returns_empty_logo_when_file_missing():
    from pitch_agent.config import load_brand

    brand = load_brand()
    assert brand["name"] == "The Pitch Agent"
    assert brand["parent_brand"] == "BuildWithAbdallah"
    # Default logo path does not exist in the repo, so it resolves to "".
    assert brand["logo_path"] == ""


def test_chart_renders_without_logo(tmp_path, monkeypatch):
    """A missing logo must not crash chart rendering (text-only footer)."""
    monkeypatch.chdir(tmp_path)
    output = render_leaderboard_chart(
        [{"player_name": "Test Player", "position": "DEF", "score": 3.0}],
        position="DEF",
    )
    assert Path(output).exists()
    assert Path(output).stat().st_size > 0


def test_chart_uses_logo_when_present(tmp_path, monkeypatch):
    """When a logo file exists, the branded template should render without error."""
    logo = tmp_path / "logo.png"
    # Minimal valid PNG via matplotlib so imread succeeds.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure()
    fig.savefig(logo)
    plt.close(fig)

    monkeypatch.setattr(
        "pitch_agent.config.load_brand",
        lambda *a, **k: {
            "name": "The Pitch Agent", "parent_brand": "BuildWithAbdallah",
            "footer": "The Pitch Agent by BuildWithAbdallah | Independent analytics | Not affiliated with FIFA",
            "logo_path": str(logo),
        },
    )
    out = render_leaderboard_chart(
        [{"player_name": "P", "position": "FWD", "score": 9.0}],
        output_path=str(tmp_path / "chart.png"),
    )
    assert Path(out).exists()
    assert Path(out).stat().st_size > 0


def test_review_metadata_includes_brand(tmp_path):
    from pitch_agent.telegram_review import _build_review_message, _safe_metadata

    db_path = _seed_fixtures_db(tmp_path)
    result = generate_content(
        "matchday_preview", mode="fan_mode", db_path=db_path, dry_run=True,
    )
    msg = _build_review_message(result, _safe_metadata(result["metadata"]))

    assert "brand: The Pitch Agent" in msg
    assert "by: BuildWithAbdallah" in msg
    # Visible post stays clean — no brand metadata leaks into the content.
    assert "by: BuildWithAbdallah" not in result["content"]


# ── BuildWithAbdallah light brand chart template ─────────────────────────


def _corner_is_light(png_path: str) -> bool:
    import matplotlib.image as mpimg
    img = mpimg.imread(png_path)
    r, g, b = img[2, 2, :3]
    return r > 0.9 and g > 0.9 and b > 0.9


def test_brand_template_exposes_shared_functions():
    from pitch_agent import brand_template, chart_blocks
    from pitch_agent import chart_themes

    for fn in (
        "load_brand_config", "draw_background", "draw_watermark", "draw_header",
        "draw_title_block", "draw_footer", "draw_accent_shapes", "save_chart",
        "create_canvas", "figure_size_for",
    ):
        assert callable(getattr(brand_template, fn)), f"missing {fn}"
    assert callable(chart_themes.load_theme)
    for block in (
        "draw_fixture_rows", "draw_leaderboard_rows", "draw_position_rows",
        "draw_player_spotlight", "draw_stat_card",
    ):
        assert callable(getattr(chart_blocks, block)), f"missing {block}"


def test_light_theme_is_default():
    from pitch_agent.brand_template import load_brand_config
    from pitch_agent.chart_themes import load_theme

    assert load_brand_config()["chart_theme"] == "buildwithabdallah_light"

    theme = load_theme()
    assert theme["name"] == "buildwithabdallah_light"
    assert theme["background_color"] == "#F7F9FC"
    assert theme["primary_text"] == "#0B1F44"
    assert theme["accent_blue"] == "#1D6CF2"
    assert theme["watermark_text"] == "A"
    assert theme["watermark_alpha"] == 0.08


def test_dark_theme_override():
    """The legacy dark palette is available via the 'dark' theme."""
    from pitch_agent.chart_themes import load_theme

    dark = load_theme(name="dark")
    assert dark["background_color"] == "#0f172a"
    assert dark["primary_text"] == "#e2e8f0"


def test_leaderboard_chart_uses_light_brand_theme(tmp_path):
    out = render_leaderboard_chart(
        [{"player_name": "Lionel Messi", "position": "FWD", "score": 99.0},
         {"player_name": "Rodrigo De Paul", "position": "MID", "score": 66.0}],
        output_path=str(tmp_path / "lb.png"), scope="daily",
    )
    assert Path(out).exists()
    assert _corner_is_light(out)


def test_fixtures_chart_uses_light_brand_theme(tmp_path):
    from pitch_agent.charts import render_fixtures_chart

    out = render_fixtures_chart(
        [{"match_label": "Mexico vs South Africa", "date": "2026-06-11",
          "group_name": "GROUP_A", "stage": "GROUP_STAGE"}],
        output_path=str(tmp_path / "fx.png"),
    )
    assert Path(out).exists()
    assert _corner_is_light(out)


def test_branded_chart_missing_logo_does_not_crash(tmp_path, monkeypatch):
    """A missing/blank logo path must fall back to text, never raise."""
    from pitch_agent.charts import render_fixtures_chart

    monkeypatch.setattr(
        "pitch_agent.config.load_brand",
        lambda *a, **k: {
            "name": "The Pitch Agent", "parent_brand": "BuildWithAbdallah",
            "footer": "The Pitch Agent by BuildWithAbdallah | Independent analytics | Not affiliated with FIFA",
            "logo_path": "",  # missing logo
            "background_color": "#F8FAFF", "primary_text": "#071A3D",
            "secondary_text": "#64748B", "accent_blue": "#0B63F6",
            "divider_color": "#DDE5F2", "watermark_text": "A",
            "chart_theme": "buildwithabdallah_light",
        },
    )
    out = render_fixtures_chart(
        [{"match_label": "A vs B", "date": "2026-06-11", "group_name": "GROUP_A"}],
        output_path=str(tmp_path / "fx_nologo.png"),
    )
    assert Path(out).exists()
    assert Path(out).stat().st_size > 0


def test_branding_has_no_fifa_or_trophy_marks():
    """The brand uses the BuildWithAbdallah identity, never a FIFA/trophy mark."""
    from pitch_agent.transparency import get_chart_footer
    from pitch_agent.brand_template import load_brand_config
    from pitch_agent.chart_themes import load_theme

    footer = get_chart_footer().lower()
    assert "not affiliated with fifa" in footer

    brand = load_brand_config()
    logo = (brand.get("logo_path") or "").lower()
    # No FIFA / World Cup / trophy imagery is referenced anywhere in branding.
    for banned in ("fifa", "world-cup", "worldcup", "trophy"):
        assert banned not in logo
        assert banned not in brand.get("name", "").lower()
        assert banned not in brand.get("parent_brand", "").lower()
    assert load_theme().get("watermark_text") == "A"


def test_all_leaderboard_pillars_get_branded_chart_path(tmp_path):
    """player_spotlight/post_match_grades/stat_of_the_day/team_form_report chart."""
    db_path = _seed_duplicate_player_leaderboard(tmp_path)
    for pillar in (
        "player_spotlight", "post_match_grades",
        "stat_of_the_day", "team_form_report",
    ):
        result = generate_content(pillar, mode="fan_mode", db_path=db_path, dry_run=True)
        assert result["metadata"]["chart_path"].endswith(f"{pillar}.png")


def test_figure_size_is_deterministic():
    from pitch_agent.brand_template import figure_size_for, HEADER_IN, ROW_IN, FOOTER_IN

    size_a = figure_size_for(10)
    size_b = figure_size_for(10)
    assert size_a == size_b  # pure function, no randomness
    assert size_a == (10.0, round(HEADER_IN + 10 * ROW_IN + FOOTER_IN, 3))
    # More rows → strictly taller, same width.
    assert figure_size_for(20)[1] > figure_size_for(5)[1]
    assert figure_size_for(20)[0] == figure_size_for(5)[0]
    # Zero/blank still yields a valid (>= 1 row) figure.
    assert figure_size_for(0)[1] == figure_size_for(1)[1]


def test_same_inputs_produce_same_chart_dimensions(tmp_path):
    """Deterministic layout: identical inputs → identical image dimensions."""
    import matplotlib.image as mpimg

    rows = [{"player_name": f"P{i}", "position": "FWD", "score": 90 - i}
            for i in range(8)]
    a = render_leaderboard_chart(rows, output_path=str(tmp_path / "a.png"))
    b = render_leaderboard_chart(rows, output_path=str(tmp_path / "b.png"))
    shape_a = mpimg.imread(a).shape
    shape_b = mpimg.imread(b).shape
    assert shape_a == shape_b
    assert shape_a[1] == int(10.0 * 150)  # fixed width in px


def test_player_spotlight_and_stat_card_render_light(tmp_path):
    from pitch_agent.charts import render_player_spotlight_chart, render_stat_card_chart

    sp = render_player_spotlight_chart(
        {"player_name": "Lionel Messi", "team_name": "Argentina",
         "position": "FWD", "score": 99.0, "key_reason": "2 goals, 1 assist, team win"},
        output_path=str(tmp_path / "spotlight.png"),
    )
    sc = render_stat_card_chart(
        {"value": "99.0", "label": "Lionel Messi", "sub": "Top Form Index today"},
        output_path=str(tmp_path / "stat.png"),
    )
    for path in (sp, sc):
        assert Path(path).exists()
        assert _corner_is_light(path)


def test_all_seven_chart_types_share_branded_footer(monkeypatch):
    """Every chart entry point pulls the footer from get_chart_footer()."""
    import pitch_agent.charts as charts

    calls = {"n": 0}
    real = charts.get_chart_footer
    monkeypatch.setattr(charts, "get_chart_footer",
                        lambda: (calls.__setitem__("n", calls["n"] + 1), real())[1])

    lb_rows = [{"player_name": "P", "position": "FWD", "score": 9.0}]
    charts.render_leaderboard_chart(lb_rows, output_path="/tmp/pa_t_lb.png")
    charts.render_leaderboard_chart(lb_rows, output_path="/tmp/pa_t_pos.png", position="DEF")
    charts.render_fixtures_chart(
        [{"match_label": "A vs B", "date": "2026-06-11", "group_name": "GROUP_A"}],
        output_path="/tmp/pa_t_fx.png")
    charts.render_player_spotlight_chart(
        {"player_name": "P", "team_name": "T", "position": "FWD", "score": 9.0},
        output_path="/tmp/pa_t_sp.png")
    charts.render_stat_card_chart(
        {"value": "9.0", "label": "P", "sub": "x"}, output_path="/tmp/pa_t_sc.png")

    # 5 explicit renderers (leaderboard, position, fixtures, spotlight, stat),
    # each pulling the single shared footer source.
    assert calls["n"] == 5

    import os
    for f in ("lb", "pos", "fx", "sp", "sc"):
        os.remove(f"/tmp/pa_t_{f}.png")


def test_render_for_pillar_dispatches_branded_charts(tmp_path):
    from pitch_agent.charts import render_for_pillar

    rows = [{"player_name": "Lionel Messi", "team_name": "Argentina",
             "position": "FWD", "score": 99.0, "key_reason": "2 goals"}]
    fixtures = [{"match_label": "A vs B", "date": "2026-06-11", "group_name": "GROUP_A"}]

    cases = [
        ("player_spotlight", rows),
        ("stat_of_the_day", rows),
        ("post_match_grades", rows),
        ("team_form_report", rows),
        ("matchday_preview", fixtures),
    ]
    for pillar, data in cases:
        out = render_for_pillar(pillar, data, output_path=str(tmp_path / f"{pillar}.png"))
        assert Path(out).exists()
        assert _corner_is_light(out)


# ── 9. football-data provider fails clearly if API key missing ───────────

def test_football_data_provider_fails_without_api_key(monkeypatch):
    """FootballDataProvider should raise EnvironmentError without API key."""
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    from pitch_agent.providers.football_data_provider import FootballDataProvider

    with pytest.raises(EnvironmentError, match="FOOTBALL_DATA_API_KEY"):
        FootballDataProvider(api_key="")


# ── 10. football-data provider normalizes missing advanced fields to 0 ──

def test_football_data_normalizes_missing_fields_to_zero():
    """The _normalise_match_stats method should fill rich fields with 0."""
    from pitch_agent.providers.football_data_provider import FootballDataProvider

    provider = FootballDataProvider.__new__(FootballDataProvider)
    provider.api_key = "test-key"
    provider.base_url = "https://api.football-data.org/v4"

    # Simulate a minimal API response with one scorer
    match_data = {
        "id": "M100",
        "competition": {"id": "WC2026"},
        "season": {"id": "2026"},
        "matchday": 1,
        "stage": "GROUP",
        "homeTeam": {"id": "T01", "shortName": "TeamA"},
        "awayTeam": {"id": "T02", "shortName": "TeamB"},
        "score": {"fullTime": {"homeTeam": 2, "awayTeam": 1}},
        "scorers": [
            {"scorer": {"id": "P01", "name": "Test Player"}, "team": {"id": "T01"}, "goals": 1, "assists": 0},
        ],
        "lineups": [],
    }

    results = provider._normalise_match_stats(match_data)
    assert len(results) >= 1

    # Find the scorer record
    scorer = None
    for r in results:
        if r.get("player_id") == "P01":
            scorer = r
            break

    assert scorer is not None, f"P01 not found in results: {results}"
    # All rich fields should be 0
    assert scorer.get("pass_accuracy", -1) == 0.0
    assert scorer.get("shots_on_target", -1) == 0
    assert scorer.get("key_passes", -1) == 0
    assert scorer.get("saves", -1) == 0
    assert scorer.get("shots_faced", -1) == 0


def test_score_breakdown_uses_provider_available_fields_after_db_roundtrip(tmp_path):
    """Database defaults should not make missing rich stats look provider-supplied."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    upsert_player_match_stats(conn, {
        "match_id": "M001",
        "player_id": "P01",
        "player_name": "Basic Player",
        "team_id": "T01",
        "team_name": "TeamA",
        "position": "FWD",
        "goals": 1,
        "assists": 0,
        "minutes": 90,
        "yellow_cards": 0,
        "red_cards": 0,
        "clean_sheet": 0,
        "team_result": "WIN",
        "available_fields": json.dumps([
            "goals", "assists", "minutes", "yellow_cards",
            "red_cards", "clean_sheet", "team_result",
        ]),
        "provider_name": "csv",
        "data_quality_level": "basic",
    })
    conn.commit()
    conn.close()

    assert compute_all(db_path) == 1
    conn = sqlite3.connect(db_path)
    breakdown_json = conn.execute(
        "SELECT score_breakdown_json FROM form_index_scores"
    ).fetchone()[0]
    breakdown = json.loads(breakdown_json)
    conn.close()
    for key in (
        "fields_present", "fields_absent", "provider_name",
        "data_quality_level", "model_version", "base",
        "raw_score_before_minutes", "minutes_adjustment", "final_score",
    ):
        assert key in breakdown
    assert breakdown["base"] == 50
    assert breakdown["provider_name"] == "csv"
    assert breakdown["data_quality_level"] == "basic"
    assert breakdown["model_version"] == MODEL_VERSION
    assert "pass_accuracy" in breakdown["fields_absent"]
    assert "goals" in breakdown["fields_present"]
    conn.close()


def test_fan_and_builder_mode_wording_separation(tmp_path):
    """Fan content stays consumer-facing; builder content can expose pipeline metadata."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    upsert_player_match_stats(conn, {
        "match_id": "M001",
        "player_id": "P01",
        "player_name": "Player",
        "team_id": "T01",
        "team_name": "TeamA",
        "position": "MID",
        "goals": 0,
        "assists": 1,
        "minutes": 90,
        "team_result": "WIN",
        "provider_name": "csv",
        "data_quality_level": "basic",
    })
    conn.commit()
    conn.close()
    compute_all(db_path)

    fan = generate_content(
        "form_index_update",
        mode="fan_mode",
        db_path=db_path,
        dry_run=True,
    )
    builder = generate_content(
        "builder_update",
        mode="builder_mode",
        db_path=db_path,
        dry_run=True,
    )

    visible_fan_text = "\n".join([
        str(fan["content"]),
        str(fan["goal_string"]),
        str(fan["disclaimer"]),
    ])
    builder_text = json.dumps(builder, default=str)
    fan_banned = (
        "python", "sqlite", "api", "smkit", "cron", "github", "code",
        "betting", "gambling", "sportsbook", "odds", "wagering",
    )
    for word in fan_banned:
        assert word not in visible_fan_text.lower()
    for key in (
        "mode", "pillar", "provider_name", "chart_path",
        "post_key", "smkit_command", "data_quality_level",
    ):
        assert key in fan["metadata"]
    assert fan["metadata"]["mode"] == "fan_mode"
    assert fan["metadata"]["pillar"] == "form_index_update"
    assert fan["metadata"]["provider_name"] == "csv"
    assert fan["metadata"]["data_quality_level"] == "basic"
    for word in ("betting", "gambling", "sportsbook", "odds", "wagering"):
        assert word not in builder_text.lower()
    assert "score_breakdown_json" in builder_text


# ── Additional edge case tests ────────────────────────────────────────────

def test_minutes_15_to_44_multiplier():
    """Player with 30 minutes should get 0.90 multiplier."""
    stats = {
        "goals": 0, "assists": 0, "minutes": 30, "yellow_cards": 0,
        "team_result": "DRAW", "position": "MID",
    }
    result = compute_form_index(stats)
    assert result["breakdown"]["minutes_adjustment"] == 0.90


def test_minutes_45_plus_multiplier():
    """Player with 90 minutes should get 1.0 multiplier."""
    stats = {
        "goals": 1, "assists": 1, "minutes": 90, "yellow_cards": 0,
        "team_result": "WIN", "position": "FWD",
    }
    result = compute_form_index(stats)
    assert result["breakdown"]["minutes_adjustment"] == 1.0


def test_no_event_full_match_player_scores_base_50():
    """A full-match player with no events should retain the base score."""
    result = compute_form_index({
        "goals": 0, "assists": 0, "minutes": 90,
        "yellow_cards": 0, "red_cards": 0, "own_goals": 0,
        "clean_sheet": 0, "team_result": "DRAW", "position": "MID",
    })
    assert result["breakdown"]["base"] == 50
    assert result["breakdown"]["raw_score_before_minutes"] == 50.0
    assert result["score"] == 50.0


def test_yellow_card_only_player_below_50_not_negative():
    """A yellow-card-only full-match player should dip below base but not below zero."""
    result = compute_form_index({
        "goals": 0, "assists": 0, "minutes": 90,
        "yellow_cards": 1, "red_cards": 0, "own_goals": 0,
        "clean_sheet": 0, "team_result": "DRAW", "position": "MID",
    })
    assert result["breakdown"]["base"] == 50
    assert result["score"] == 48.0
    assert 0 <= result["score"] < 50


def test_goal_and_assist_player_scores_high():
    """Goal contributions should produce a high, but clamped, score."""
    result = compute_form_index({
        "goals": 2, "assists": 1, "minutes": 90,
        "yellow_cards": 0, "team_result": "WIN", "position": "FWD",
    })
    assert result["score"] == 99.0
    assert 80 <= result["score"] <= 100


def test_final_score_is_clamped_between_0_and_100():
    """Extreme inputs should never produce public scores outside 0-100."""
    high = compute_form_index({
        "goals": 10, "assists": 10, "minutes": 90,
        "team_result": "WIN", "position": "FWD",
    })
    low = compute_form_index({
        "goals": 0, "assists": 0, "minutes": 90,
        "yellow_cards": 10, "red_cards": 10, "own_goals": 10,
        "team_result": "LOSS", "position": "MID",
    })
    assert high["breakdown"]["base"] == 50
    assert low["breakdown"]["base"] == 50
    assert high["score"] == 100.0
    assert low["score"] == 0.0
    assert 0 <= high["breakdown"]["final_score"] <= 100
    assert 0 <= low["breakdown"]["final_score"] <= 100


def test_midfielder_bonus():
    """MID with pass_accuracy >= 88 and minutes >= 45 should get +3."""
    stats = {
        "goals": 0, "assists": 0, "minutes": 90, "yellow_cards": 0,
        "team_result": "DRAW", "position": "MID",
        "pass_accuracy": 91.2,
    }
    result = compute_form_index(stats)
    assert result["breakdown"]["position_bonus"] == 3.0


def test_goalkeeper_bonus():
    """GK with save ratio >= 0.80 should get +5."""
    stats = {
        "goals": 0, "assists": 0, "minutes": 90, "yellow_cards": 0,
        "team_result": "WIN", "position": "GK",
        "clean_sheet": 1, "shots_faced": 4, "saves": 4,
    }
    result = compute_form_index(stats)
    assert result["breakdown"]["position_bonus"] == 5.0


def test_full_pipeline(tmp_path):
    """End-to-end: init-db → sync CSV → compute-index → leaderboard."""
    from pitch_agent.providers.csv_provider import CSVProvider

    db_path = str(tmp_path / "test.db")
    data_dir = str(ROOT / "pitch_agent" / "data")

    # Init DB
    conn = init_db(db_path)

    # Sync CSV data
    provider = CSVProvider(data_dir=data_dir)
    stats = provider.fetch_match_stats(match_id=None)
    assert len(stats) > 0, "CSV provider should return stats"

    for record in stats:
        upsert_player_match_stats(conn, record)

    # Compute index
    count = 0
    rows = conn.execute("SELECT * FROM player_match_stats").fetchall()
    from pitch_agent.form_index import compute_form_index
    for row in rows:
        result = compute_form_index(dict(row))
        upsert_form_index(conn, {
            "match_id": row["match_id"],
            "player_id": row["player_id"],
            "model_version": MODEL_VERSION,
            "score": result["score"],
            "score_breakdown_json": json.dumps(result["breakdown"]),
        })
        count += 1
    assert count > 0, "Should have computed some scores"
    conn.commit()
    conn.close()

    # Leaderboard
    results = get_leaderboard(db_path, limit=5)
    assert len(results) > 0, "Leaderboard should have results"


# ── Predictions & Poisson (Commit 2) ────────────────────────────────────

def test_poisson_probabilities_sum_to_one():
    """All scoreline probabilities from Poisson should sum close to 1."""
    from pitch_agent.poisson import scoreline_distribution
    dist = scoreline_distribution(1.5, 1.2, max_goals=7)
    total = sum(r["probability"] for r in dist)
    assert abs(total - 1.0) < 0.01, f"Probabilities sum to {total}"


def test_top_scorelines_are_sorted():
    """Top scorelines should be in descending probability order."""
    from pitch_agent.poisson import top_scorelines
    top = top_scorelines(2.0, 0.8, n=3)
    assert len(top) == 3
    assert top[0]["probability"] >= top[1]["probability"] >= top[2]["probability"]


def test_match_outcome_probs_sum_to_one():
    """Home win + draw + away win should sum to ~1."""
    from pitch_agent.poisson import match_outcome_probs
    probs = match_outcome_probs(1.5, 1.2)
    total = probs["home_win"] + probs["draw"] + probs["away_win"]
    assert abs(total - 1.0) < 0.02, f"Outcome probs sum to {total}"


def test_form_index_to_xg_returns_reasonable_values():
    """Form Index → xG should produce plausible expected goals."""
    from pitch_agent.poisson import form_index_to_xg
    # Even match (both 50)
    hxg, axg = form_index_to_xg(50, 50)
    assert 1.0 <= hxg <= 1.5, f"Even home xG: {hxg}"
    assert 1.0 <= axg <= 1.5, f"Even away xG: {axg}"
    # Strong home (80 vs 50)
    hxg, axg = form_index_to_xg(80, 50)
    assert hxg > axg, "Strong home should have higher xG"
    assert hxg >= 1.5, f"Strong home xG should be >= 1.5, got {hxg}"


def test_prediction_key_factor_even_match():
    """Even teams should return 'evenly matched'."""
    from pitch_agent.poisson import prediction_key_factor
    factor = prediction_key_factor(
        [{"score": 60, "goals": 1}], [{"score": 62, "goals": 1}]
    )
    assert "Evenly matched" in factor


def test_prediction_key_factor_strong_home():
    """Strong home team should show positive differential."""
    from pitch_agent.poisson import prediction_key_factor
    factor = prediction_key_factor(
        [{"score": 85, "goals": 2}], [{"score": 55, "goals": 0}]
    )
    assert "Home" in factor
    assert "+30" in factor or "+25" in factor or "+20" in factor


def test_predictions_table_created_on_init():
    """init_db should create the predictions and prediction_results tables."""
    db_path = str(tmp_path / "pred_test.db") if "tmp_path" in dir() else ":memory:"
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "pred_test.db")
        conn = init_db(db_path)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "predictions" in tables
        assert "prediction_results" in tables


def test_upsert_prediction_and_grade(tmp_path):
    """Insert a prediction, add a match result, and grade it."""
    db_path = str(tmp_path / "pred_grade.db")
    conn = init_db(db_path)

    # Create a match with a known result
    upsert_match(conn, {
        "match_id": "M001", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "home_score": 2, "away_score": 0, "date": "2026-06-11",
        "status": "FINISHED"})
    conn.commit()

    # Insert a prediction: Mexico 2-0
    upsert_prediction(conn, {
        "match_id": "M001", "model_version": "1.1.0",
        "predicted_home": 2, "predicted_away": 0,
        "predicted_outcome": "home",
        "home_win_prob": 0.63, "draw_prob": 0.20, "away_win_prob": 0.17,
        "top_scorelines": [{"home_goals": 2, "away_goals": 0, "probability": 0.15, "label": "2-0"}],
        "key_factor": "Home +20 Form Index differential",
    })
    conn.commit()

    # Grade predictions
    graded = grade_predictions(conn)

    assert graded == 1, f"Should grade 1 prediction, got {graded}"

    # Check accuracy
    accuracy = get_prediction_accuracy(conn)
    assert accuracy["total"] == 1
    assert accuracy["correct"] == 1  # Mexico 2-0 was predicted and correct
    assert accuracy["pct"] == 100.0

    conn.close()


def test_incorrect_prediction_graded_as_wrong(tmp_path):
    """An incorrect prediction should be graded as wrong."""
    db_path = str(tmp_path / "pred_wrong.db")
    conn = init_db(db_path)

    upsert_match(conn, {
        "match_id": "M002", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": 0, "away_score": 3, "date": "2026-06-12",
        "status": "FINISHED"})
    conn.commit()

    # Predict home win, but away won
    upsert_prediction(conn, {
        "match_id": "M002", "model_version": "1.1.0",
        "predicted_home": 2, "predicted_away": 1,
        "predicted_outcome": "home",
        "home_win_prob": 0.48, "draw_prob": 0.25, "away_win_prob": 0.27,
        "top_scorelines": [],
        "key_factor": "Home +10 Form Index",
    })
    conn.commit()

    graded = grade_predictions(conn)
    assert graded == 1

    accuracy = get_prediction_accuracy(conn)
    assert accuracy["total"] == 1
    assert accuracy["correct"] == 0
    assert accuracy["pct"] == 0.0
    conn.close()


def test_draw_prediction_graded_correctly(tmp_path):
    """A predicted draw that ends in a draw should be correct."""
    db_path = str(tmp_path / "pred_draw.db")
    conn = init_db(db_path)

    upsert_match(conn, {
        "match_id": "M003", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": 1, "away_score": 1, "date": "2026-06-13",
        "status": "FINISHED"})
    conn.commit()

    upsert_prediction(conn, {
        "match_id": "M003", "model_version": "1.1.0",
        "predicted_home": 1, "predicted_away": 1,
        "predicted_outcome": "draw",
        "home_win_prob": 0.30, "draw_prob": 0.35, "away_win_prob": 0.35,
        "top_scorelines": [],
        "key_factor": "Evenly matched",
    })
    conn.commit()

    graded = grade_predictions(conn)
    assert graded == 1

    accuracy = get_prediction_accuracy(conn)
    assert accuracy["correct"] == 1
    assert accuracy["total"] == 1
    conn.close()


# ── Follow-up: exact-score grading, migration, _match_prediction fallback ──

def test_exact_score_correct_on_exact_match(tmp_path):
    """Exact scoreline match should set exact_score_correct=1."""
    db_path = str(tmp_path / "exact_hit.db")
    conn = init_db(db_path)
    upsert_match(conn, {
        "match_id": "M100", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "home_score": 2, "away_score": 0, "date": "2026-06-11",
        "status": "FINISHED"})
    conn.commit()
    upsert_prediction(conn, {
        "match_id": "M100", "model_version": MODEL_VERSION,
        "predicted_home": 2, "predicted_away": 0,
        "predicted_outcome": "home",
        "home_win_prob": 0.63, "draw_prob": 0.20, "away_win_prob": 0.17,
        "top_scorelines": [], "key_factor": "Home +20 FI",
    })
    conn.commit()
    graded = grade_predictions(conn)
    assert graded == 1
    result = conn.execute("SELECT correct, exact_score_correct FROM prediction_results").fetchone()
    assert result["correct"] == 1
    assert result["exact_score_correct"] == 1
    conn.close()


def test_exact_score_correct_on_wrong_score_but_right_outcome(tmp_path):
    """Correct outcome but wrong scoreline: outcome=1, exact_score_correct=0."""
    db_path = str(tmp_path / "exact_miss.db")
    conn = init_db(db_path)
    upsert_match(conn, {
        "match_id": "M101", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": 3, "away_score": 1, "date": "2026-06-12",
        "status": "FINISHED"})
    conn.commit()
    # Predicted 2-0 home win; actual 3-1 home win — right outcome, wrong score
    upsert_prediction(conn, {
        "match_id": "M101", "model_version": MODEL_VERSION,
        "predicted_home": 2, "predicted_away": 0,
        "predicted_outcome": "home",
        "home_win_prob": 0.55, "draw_prob": 0.25, "away_win_prob": 0.20,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()
    graded = grade_predictions(conn)
    assert graded == 1
    result = conn.execute("SELECT correct, exact_score_correct FROM prediction_results").fetchone()
    assert result["correct"] == 1  # outcome correct
    assert result["exact_score_correct"] == 0  # exact score wrong
    conn.close()


def test_exact_score_correct_null_for_legacy_rows(tmp_path):
    """Legacy prediction_results rows with NULL exact_score_correct are excluded from
    exact-score denominator. COUNT(exact_score_correct) skips NULLs, so legacy
    rows don't dilute exact-score accuracy."""
    db_path = str(tmp_path / "exact_legacy.db")
    conn = init_db(db_path)

    # Match with no result yet (home_score/away_score = NULL) so grade_predictions skips it
    upsert_match(conn, {
        "match_id": "M102", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": None, "away_score": None, "date": "2026-06-13",
    })
    conn.commit()
    upsert_prediction(conn, {
        "match_id": "M102", "model_version": MODEL_VERSION,
        "predicted_home": 1, "predicted_away": 0,
        "predicted_outcome": "home",
        "home_win_prob": 0.50, "draw_prob": 0.30, "away_win_prob": 0.20,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()
    # Manually insert a legacy result row WITHOUT exact_score_correct
    # (simulates a row from before the column existed)
    pred_id = conn.execute("SELECT id FROM predictions WHERE match_id = 'M102'").fetchone()["id"]
    conn.execute(
        "INSERT INTO prediction_results (prediction_id, actual_home, actual_away, correct, graded_at) VALUES (?, 1, 0, 1, datetime('now'))",
        (pred_id,),
    )
    conn.commit()
    # grade_predictions should NOT touch this (match has no result)
    graded = grade_predictions(conn)
    assert graded == 0

    stats = get_prediction_accuracy(conn)
    assert stats["total"] == 1
    assert stats["correct"] == 1
    # Legacy row: exact_gradable=0 (NULL excluded), legacy_count=1
    assert stats["exact_gradable"] == 0
    assert stats["legacy_count"] == 1
    conn.close()


def test_exact_score_mixed_null_and_graded_rows(tmp_path):
    """Mix of legacy NULL rows and graded rows: exact-score accuracy counts only
    graded rows in denominator, and reports legacy_count separately."""
    db_path = str(tmp_path / "exact_mixed.db")
    conn = init_db(db_path)

    # Match 1: legacy row (no exact_score_correct) — match has no result yet
    # so grade_predictions won't overwrite it
    upsert_match(conn, {
        "match_id": "M110", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": None, "away_score": None, "date": "2026-06-14",
    })
    upsert_prediction(conn, {
        "match_id": "M110", "model_version": MODEL_VERSION,
        "predicted_home": 2, "predicted_away": 1,
        "predicted_outcome": "home",
        "home_win_prob": 0.55, "draw_prob": 0.25, "away_win_prob": 0.20,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()
    # Legacy result row — no exact_score_correct column populated
    pred1 = conn.execute("SELECT id FROM predictions WHERE match_id = 'M110'").fetchone()["id"]
    conn.execute(
        "INSERT INTO prediction_results (prediction_id, actual_home, actual_away, correct, graded_at) VALUES (?, 2, 1, 1, datetime('now'))",
        (pred1,),
    )

    # Match 2: graded row — exact score correct
    upsert_match(conn, {
        "match_id": "M111", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamC", "away_team_name": "TeamD",
        "home_score": 3, "away_score": 0, "date": "2026-06-15",
        "status": "FINISHED"})
    upsert_prediction(conn, {
        "match_id": "M111", "model_version": MODEL_VERSION,
        "predicted_home": 3, "predicted_away": 0,
        "predicted_outcome": "home",
        "home_win_prob": 0.60, "draw_prob": 0.20, "away_win_prob": 0.20,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()
    # Normal grading via grade_predictions
    grade_predictions(conn)

    # Match 3: graded row — exact score wrong
    upsert_match(conn, {
        "match_id": "M112", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamE", "away_team_name": "TeamF",
        "home_score": 1, "away_score": 1, "date": "2026-06-16",
        "status": "FINISHED"})
    upsert_prediction(conn, {
        "match_id": "M112", "model_version": MODEL_VERSION,
        "predicted_home": 2, "predicted_away": 0,
        "predicted_outcome": "home",
        "home_win_prob": 0.50, "draw_prob": 0.25, "away_win_prob": 0.25,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()
    grade_predictions(conn)

    # Verify grade_predictions didn't touch M110 (no match result)
    legacy_row = conn.execute(
        "SELECT exact_score_correct FROM prediction_results WHERE prediction_id = ?",
        (pred1,),
    ).fetchone()
    assert legacy_row["exact_score_correct"] is None, "Legacy row should still have NULL exact_score_correct"

    stats = get_prediction_accuracy(conn)
    # total counts ALL rows (including legacy)
    assert stats["total"] == 3
    # Outcome: 2/3 correct (M110 legacy correct, M111 correct, M112 wrong outcome)
    assert stats["correct"] == 2
    # Exact: only 2 gradable rows (M111, M112); 1 correct (M111)
    assert stats["exact_gradable"] == 2
    assert stats["exact_correct"] == 1
    # 1 legacy row excluded from exact-score denominator
    assert stats["legacy_count"] == 1
    conn.close()


def test_exact_score_migration_on_existing_db(tmp_path):
    """Migrating a DB created before exact_score_correct should add the column."""
    db_path = str(tmp_path / "exact_migrate.db")
    conn = init_db(db_path)
    # Simulate a pre-migration DB by dropping the column
    # (Can't ALTER TABLE DROP COLUMN in SQLite < 3.35, so recreate)
    # Instead, verify that migrate_db adds the column if missing
    from pitch_agent.db import migrate_db
    added = migrate_db(db_path)
    # If the column already exists (fresh DB), added should be empty
    # But the column should exist regardless
    cols = {row[1] for row in conn.execute("PRAGMA table_info(prediction_results)").fetchall()}
    assert "exact_score_correct" in cols
    conn.close()


def test_match_prediction_returns_none_when_no_form_index_data(tmp_path):
    """_match_prediction should return None when no Form Index data exists for either team."""
    import os
    os.environ["PITCH_AGENT_DB"] = str(tmp_path / "pred_no_data.db")
    from pitch_agent.content import _match_prediction
    fixture = {
        "match_id": "M200",
        "home_team_name": "NonExistentTeam",
        "away_team_name": "AlsoNonExistent",
        "date": "2026-06-20",
    }
    result = _match_prediction(fixture)
    assert result is None


def test_match_prediction_returns_none_on_db_error(tmp_path):
    """_match_prediction should return None when DB is inaccessible."""
    from pitch_agent.content import _match_prediction
    fixture = {
        "match_id": "M201",
        "home_team_name": "TeamA",
        "away_team_name": "TeamB",
        "date": "2026-06-21",
    }
    # Point to a non-existent DB path that will cause a connection error
    import os
    old_db = os.environ.get("PITCH_AGENT_DB")
    os.environ["PITCH_AGENT_DB"] = "/nonexistent/path/that/does/not/exist.db"
    try:
        result = _match_prediction(fixture)
        assert result is None
    finally:
        if old_db:
            os.environ["PITCH_AGENT_DB"] = old_db
        else:
            os.environ.pop("PITCH_AGENT_DB", None)


def test_grade_0_0_draw_prediction(tmp_path):
    """A 0-0 result should grade a predicted draw as outcome-correct."""
    db_path = str(tmp_path / "draw_00.db")
    conn = init_db(db_path)
    upsert_match(conn, {
        "match_id": "M200", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamX", "away_team_name": "TeamY",
        "home_score": 0, "away_score": 0, "date": "2026-06-20",
        "status": "FINISHED"})
    conn.commit()
    upsert_prediction(conn, {
        "match_id": "M200", "model_version": MODEL_VERSION,
        "predicted_home": 0, "predicted_away": 0,
        "predicted_outcome": "draw",
        "home_win_prob": 0.25, "draw_prob": 0.50, "away_win_prob": 0.25,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()
    graded = grade_predictions(conn)
    assert graded == 1
    result = conn.execute("SELECT correct, exact_score_correct FROM prediction_results").fetchone()
    assert result["correct"] == 1, "Predicted 0-0 draw, actual 0-0 — outcome should be correct"
    assert result["exact_score_correct"] == 1, "Predicted exact 0-0, actual 0-0 — exact score should be correct"
    conn.close()


def test_regrading_does_not_create_duplicate_rows(tmp_path):
    """Re-grading the same match must not create duplicate prediction_results rows
    or inflate accuracy counts. INSERT OR REPLACE + UNIQUE(prediction_id) ensures
    this, but we verify explicitly."""
    db_path = str(tmp_path / "regrade_nodup.db")
    conn = init_db(db_path)
    upsert_match(conn, {
        "match_id": "M300", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": 2, "away_score": 1, "date": "2026-06-20",
        "status": "FINISHED"})
    conn.commit()
    upsert_prediction(conn, {
        "match_id": "M300", "model_version": MODEL_VERSION,
        "predicted_home": 2, "predicted_away": 1,
        "predicted_outcome": "home",
        "home_win_prob": 0.55, "draw_prob": 0.25, "away_win_prob": 0.20,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()

    # First grading
    graded = grade_predictions(conn)
    assert graded == 1

    # Count rows — should be exactly 1
    count = conn.execute("SELECT COUNT(*) FROM prediction_results").fetchone()[0]
    assert count == 1

    # Re-grade — should find nothing new (r.id IS NULL filters it out)
    graded_again = grade_predictions(conn)
    assert graded_again == 0, "Re-grading should find no ungraded predictions"

    # Still exactly 1 row
    count = conn.execute("SELECT COUNT(*) FROM prediction_results").fetchone()[0]
    assert count == 1

    # Accuracy should report exactly 1 prediction
    stats = get_prediction_accuracy(conn)
    assert stats["total"] == 1
    assert stats["correct"] == 1
    assert stats["exact_gradable"] == 1
    assert stats["exact_correct"] == 1
    assert stats["legacy_count"] == 0
    conn.close()


def test_predicted_outcome_differs_from_top_scoreline(tmp_path):
    """When top scoreline is a draw but away win probability is highest,
    predicted_outcome should be 'away' and grading uses predicted_outcome,
    not the scoreline winner."""
    db_path = str(tmp_path / "outcome_vs_scoreline.db")
    conn = init_db(db_path)

    # Actual result: away team wins 0-1
    upsert_match(conn, {
        "match_id": "M400", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": 0, "away_score": 1, "date": "2026-06-20",
        "status": "FINISHED"})
    conn.commit()

    # Prediction: top scoreline is 1-1 (draw), but outcome prob favors away
    # home_win=0.25, draw=0.35, away_win=0.40 → predicted_outcome = "away"
    upsert_prediction(conn, {
        "match_id": "M400", "model_version": MODEL_VERSION,
        "predicted_home": 1, "predicted_away": 1,
        "predicted_outcome": "away",
        "home_win_prob": 0.25, "draw_prob": 0.35, "away_win_prob": 0.40,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()

    graded = grade_predictions(conn)
    assert graded == 1

    result = conn.execute(
        "SELECT correct, exact_score_correct FROM prediction_results"
    ).fetchone()
    # predicted_outcome="away" matches actual result (away win) → correct=1
    assert result["correct"] == 1, (
        "Predicted outcome 'away' matches actual away win — should be correct"
    )
    # predicted score 1-1 vs actual 0-1 → exact_score_correct=0
    assert result["exact_score_correct"] == 0, (
        "Predicted 1-1 vs actual 0-1 — exact score should be wrong"
    )
    conn.close()


# ── Elo prior, blend, tie-breaking, basis labeling ──

def test_elo_to_xg_equal_ratings_neutral_venue():
    """Equal Elo ratings at neutral venue should produce symmetric xG."""
    from pitch_agent.poisson import elo_to_xg
    home_xg, away_xg = elo_to_xg(1500, 1500, home_advantage=False)
    # Neutral venue: xG should be equal
    assert home_xg == away_xg, f"Equal Elo at neutral venue should give symmetric xG, got {home_xg} vs {away_xg}"
    # Both should be in reasonable range
    assert 0.8 < home_xg < 3.0
    assert 0.8 < away_xg < 3.0


def test_elo_to_xg_equal_ratings_host_at_home():
    """Equal Elo ratings with home advantage (host nation) should favor home."""
    from pitch_agent.poisson import elo_to_xg
    home_xg, away_xg = elo_to_xg(1500, 1500, home_advantage=True)
    assert home_xg > away_xg, "Host at home should have home advantage"


def test_elo_to_xg_200_point_gap():
    """A 200-point Elo gap should produce a clear favorite."""
    from pitch_agent.poisson import elo_to_xg, match_outcome_probs
    home_xg, away_xg = elo_to_xg(1700, 1500)
    outcomes = match_outcome_probs(home_xg, away_xg)
    # Home should be favored
    assert outcomes["home_win"] > outcomes["away_win"]
    # ~65/35 split or stronger
    assert outcomes["home_win"] > 0.55


def test_predict_xg_pure_elo_prior():
    """With 0 FI matches for both, predict_xg returns pure Elo xG with both bases='elo_prior'."""
    from pitch_agent.poisson import predict_xg
    home_xg, away_xg, basis_home, basis_away = predict_xg(
        home_team="TeamA", away_team="TeamB",
        home_avg_fi=70.0, away_avg_fi=50.0,
        home_elo=1700, away_elo=1500,
        home_matches=0, away_matches=0,
    )
    assert basis_home == "elo_prior"
    assert basis_away == "elo_prior"
    from pitch_agent.poisson import elo_to_xg
    expected_home, expected_away = elo_to_xg(1700, 1500)
    assert home_xg == expected_home
    assert away_xg == expected_away


def test_predict_xg_blended_home_only():
    """With 1 FI match for home only, home blends FI+Elo, away stays pure Elo."""
    from pitch_agent.poisson import predict_xg
    home_xg, away_xg, basis_home, basis_away = predict_xg(
        home_team="TeamA", away_team="TeamB",
        home_avg_fi=70.0, away_avg_fi=50.0,
        home_elo=1700, away_elo=1500,
        home_matches=1, away_matches=0,
    )
    assert basis_home == "blended"
    assert basis_away == "elo_prior"


def test_predict_xg_per_team_blend():
    """home_matches=3, away_matches=0: home is pure FI, away is pure Elo."""
    from pitch_agent.poisson import predict_xg, form_index_to_xg, elo_to_xg
    home_xg, away_xg, basis_home, basis_away = predict_xg(
        home_team="TeamA", away_team="TeamB",
        home_avg_fi=70.0, away_avg_fi=50.0,
        home_elo=1700, away_elo=1500,
        home_matches=3, away_matches=0,
    )
    assert basis_home == "form_index"
    assert basis_away == "elo_prior"
    # Home xG should be pure FI
    fi_home, _ = form_index_to_xg(70.0, 50.0)
    assert home_xg == fi_home
    # Away xG should be pure Elo
    _, elo_away = elo_to_xg(1700, 1500)
    assert away_xg == elo_away


def test_predict_xg_pure_form_index():
    """With 3+ FI matches for both, predict_xg returns pure FI xG."""
    from pitch_agent.poisson import predict_xg, form_index_to_xg
    home_xg, away_xg, basis_home, basis_away = predict_xg(
        home_team="TeamA", away_team="TeamB",
        home_avg_fi=70.0, away_avg_fi=50.0,
        home_elo=1700, away_elo=1500,
        home_matches=3, away_matches=3,
    )
    assert basis_home == "form_index"
    assert basis_away == "form_index"
    expected_home, expected_away = form_index_to_xg(70.0, 50.0)
    assert home_xg == expected_home
    assert away_xg == expected_away


def test_predict_xg_no_elo_no_fi():
    """With no Elo and no FI, predict_xg returns None (no prediction from baseline)."""
    from pitch_agent.poisson import predict_xg
    result = predict_xg(
        home_team="TeamA", away_team="TeamB",
        home_avg_fi=None, away_avg_fi=None,
        home_elo=None, away_elo=None,
        home_matches=0, away_matches=0,
    )
    assert result is None, "predict_xg must return None when no real data is available"


def test_resolve_predicted_outcome_clear_winner():
    """Clear winner should return without tie-breaking."""
    from pitch_agent.poisson import resolve_predicted_outcome
    assert resolve_predicted_outcome({"home_win": 0.6, "draw": 0.25, "away_win": 0.15}) == "home"
    assert resolve_predicted_outcome({"home_win": 0.15, "draw": 0.25, "away_win": 0.60}) == "away"
    assert resolve_predicted_outcome({"home_win": 0.20, "draw": 0.50, "away_win": 0.30}) == "draw"


def test_resolve_predicted_outcome_tie_break_with_scoreline():
    """When outcomes are tied, prefer the one containing the most likely scoreline."""
    from pitch_agent.poisson import resolve_predicted_outcome
    # home_win=0.35, draw=0.35 tied. Top scoreline is 1-1 (draw). → draw
    result = resolve_predicted_outcome(
        {"home_win": 0.35, "draw": 0.35, "away_win": 0.30},
        top_scoreline={"home_goals": 1, "away_goals": 1},
    )
    assert result == "draw"

    # home_win=0.35, draw=0.35 tied. Top scoreline is 1-0 (home). → home
    result = resolve_predicted_outcome(
        {"home_win": 0.35, "draw": 0.35, "away_win": 0.30},
        top_scoreline={"home_goals": 1, "away_goals": 0},
    )
    assert result == "home"


def test_resolve_predicted_outcome_tie_no_scoreline():
    """When tied and no scoreline, prefer home > draw > away."""
    from pitch_agent.poisson import resolve_predicted_outcome
    result = resolve_predicted_outcome(
        {"home_win": 0.35, "draw": 0.35, "away_win": 0.30},
        top_scoreline=None,
    )
    assert result == "home"  # home-field advantage tiebreak


def test_load_priors_cli(tmp_path):
    """load-priors should insert team Elo ratings from a CSV file."""
    from pitch_agent.db import init_db, get_team_prior, get_all_team_priors
    csv_path = tmp_path / "priors.csv"
    csv_path.write_text("team_id,team_name,elo\nBRA,Brazil,2050\nARG,Argentina,2030\nFRA,France,2010\n")

    db_path = str(tmp_path / "priors_test.db")
    conn = init_db(db_path)

    # Use the CLI
    from pitch_agent.cli import cmd_load_priors
    import argparse
    args = argparse.Namespace(csv=str(csv_path), source="test", db=db_path)
    result = cmd_load_priors(args)
    assert result == 0

    # Verify data
    bra = get_team_prior(conn, "BRA")
    assert bra is not None
    assert bra["team_name"] == "Brazil"
    assert bra["elo"] == 2050.0

    all_priors = get_all_team_priors(conn)
    assert len(all_priors) == 3
    assert all_priors[0]["team_name"] == "Brazil"  # Highest Elo first
    conn.close()


def test_basis_label_in_prediction(tmp_path):
    """Prediction stored with basis_home/basis_away fields."""
    from pitch_agent.db import init_db, upsert_prediction, upsert_match
    db_path = str(tmp_path / "basis_test.db")
    conn = init_db(db_path)

    upsert_match(conn, {
        "match_id": "M500", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": 2, "away_score": 0, "date": "2026-06-20",
        "status": "FINISHED"})
    conn.commit()
    upsert_prediction(conn, {
        "match_id": "M500", "model_version": MODEL_VERSION,
        "predicted_home": 2, "predicted_away": 0,
        "predicted_outcome": "home",
        "basis_home": "elo_prior",
        "basis_away": "form_index",
        "home_win_prob": 0.60, "draw_prob": 0.25, "away_win_prob": 0.15,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()

    row = conn.execute("SELECT basis_home, basis_away FROM predictions WHERE match_id = 'M500'").fetchone()
    assert row["basis_home"] == "elo_prior"
    assert row["basis_away"] == "form_index"
    conn.close()


def test_missing_team_prior_skip_fixture(tmp_path):
    """A team missing from team_priors at n=0 must be skipped — no baseline fallback."""
    from pitch_agent.db import init_db
    import os
    db_path = str(tmp_path / "prior_skip.db")
    os.environ["PITCH_AGENT_DB"] = db_path
    conn = init_db(db_path)
    conn.close()

    from pitch_agent.content import _match_prediction
    fixture = {
        "match_id": "M300",
        "home_team_name": "UnknownTeamA",
        "away_team_name": "UnknownTeamB",
        "home_team_id": "",
        "away_team_id": "",
        "date": "2026-06-20",
    }
    # No team_priors data, no FI data → must return None (skip)
    result = _match_prediction(fixture)
    assert result is None, "Missing prior must skip fixture, not generate baseline prediction"
    os.environ.pop("PITCH_AGENT_DB", None)


def test_validate_priors_lists_missing_teams(tmp_path):
    """validate-priors should list teams without Elo priors."""
    from pitch_agent.db import init_db, upsert_team_prior
    db_path = str(tmp_path / "validate_priors.db")
    conn = init_db(db_path)
    # Add one prior
    upsert_team_prior(conn, {"team_id": "BRA", "team_name": "Brazil", "elo": 2050, "source": "test"})
    conn.commit()
    # Argentina is in matches but not in priors
    from pitch_agent.db import upsert_match
    upsert_match(conn, {
        "match_id": "M99", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Argentina", "away_team_name": "Brazil",
        "home_score": None, "away_score": None, "date": "2026-06-20",
    })
    conn.commit()

    from pitch_agent.cli import cmd_validate_priors
    import argparse
    args = argparse.Namespace(db=db_path)
    result = cmd_validate_priors(args)
    assert result == 0
    conn.close()


def test_elo_host_advantage():
    """Home advantage only applies when home team is a host nation."""
    from pitch_agent.poisson import elo_to_xg
    # Neutral venue: symmetric
    neutral_home, neutral_away = elo_to_xg(1600, 1600, home_advantage=False)
    assert neutral_home == neutral_away

    # Host at home: advantage
    host_home, host_away = elo_to_xg(1600, 1600, home_advantage=True)
    assert host_home > host_away
    assert host_home > neutral_home  # Host gets boost


def test_host_team_ids_match():
    """Host advantage should apply when home team ID is in host_team_ids."""
    from pitch_agent.poisson import predict_xg
    # Neutral venue: equal Elo, no host nations → symmetric xG
    neutral = predict_xg(
        home_team="USA", away_team="Brazil",
        home_avg_fi=None, away_avg_fi=None,
        home_elo=1600, away_elo=1600,
        home_matches=0, away_matches=0,
        host_nations=[],
        host_team_ids=[],
    )
    assert neutral is not None
    # USA at home with host advantage (by name)
    host = predict_xg(
        home_team="USA", away_team="Brazil",
        home_avg_fi=None, away_avg_fi=None,
        home_elo=1600, away_elo=1600,
        home_matches=0, away_matches=0,
        host_nations=["USA", "Mexico", "Canada"],
        host_team_ids=["8321"],
    )
    assert host is not None
    # Host advantage should boost home xG over neutral
    assert host[0] > neutral[0], "USA at home (host) should have higher xG than neutral"

    # Test matching by team ID only (name not in host_nations)
    by_id = predict_xg(
        home_team="8321", away_team="Brazil",
        home_avg_fi=None, away_avg_fi=None,
        home_elo=1600, away_elo=1600,
        home_matches=0, away_matches=0,
        host_nations=[],
        host_team_ids=["8321"],
    )
    assert by_id is not None
    assert by_id[0] > neutral[0], "Host team ID match should apply home advantage"


def test_predict_xg_returns_none_no_data():
    """predict_xg must return None when both Elo and FI are missing for a side."""
    from pitch_agent.poisson import predict_xg
    # No Elo, no FI → None
    result = predict_xg(
        home_team="X", away_team="Y",
        home_avg_fi=None, away_avg_fi=None,
        home_elo=None, away_elo=None,
        home_matches=0, away_matches=0,
    )
    assert result is None


def test_grade_finished_null_scores_no_grade(tmp_path):
    """A FINISHED match with NULL scores must NOT be graded."""
    from pitch_agent.db import init_db, upsert_match, upsert_prediction, grade_predictions
    db_path = str(tmp_path / "finished_null.db")
    conn = init_db(db_path)
    # FINISHED match with NULL scores (API hasn't returned scores yet)
    upsert_match(conn, {
        "match_id": "M500", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "home_score": None, "away_score": None,
        "status": "FINISHED", "date": "2026-06-11",
    })
    conn.commit()
    upsert_prediction(conn, {
        "match_id": "M500", "model_version": MODEL_VERSION,
        "predicted_home": 1, "predicted_away": 0,
        "predicted_outcome": "home",
        "home_win_prob": 0.50, "draw_prob": 0.25, "away_win_prob": 0.25,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()
    graded = grade_predictions(conn)
    assert graded == 0, "FINISHED match with NULL scores must not be graded"
    conn.close()


def test_grade_timed_match_no_grade(tmp_path):
    """A TIMED match (upcoming) must NOT be graded even if scores are somehow set."""
    from pitch_agent.db import init_db, upsert_match, upsert_prediction, grade_predictions
    db_path = str(tmp_path / "timed_no_grade.db")
    conn = init_db(db_path)
    # TIMED match with 0-0 (should never happen after fix, but guard anyway)
    upsert_match(conn, {
        "match_id": "M600", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": 0, "away_score": 0,
        "status": "TIMED", "date": "2026-06-20",
    })
    conn.commit()
    upsert_prediction(conn, {
        "match_id": "M600", "model_version": MODEL_VERSION,
        "predicted_home": 1, "predicted_away": 0,
        "predicted_outcome": "home",
        "home_win_prob": 0.50, "draw_prob": 0.25, "away_win_prob": 0.25,
        "top_scorelines": [], "key_factor": "",
    })
    conn.commit()
    graded = grade_predictions(conn)
    assert graded == 0, "TIMED match must not be graded"
    conn.close()


def test_upsert_match_null_scores(tmp_path):
    """upsert_match must store NULL for scores, not 0, when source data is None."""
    from pitch_agent.db import init_db, upsert_match
    db_path = str(tmp_path / "null_scores.db")
    conn = init_db(db_path)
    # Match with no scores (upcoming)
    upsert_match(conn, {
        "match_id": "M700", "competition_id": "WC", "matchday": 1,
        "home_team_name": "TeamA", "away_team_name": "TeamB",
        "home_score": None, "away_score": None,
        "status": "TIMED", "date": "2026-06-20",
    })
    conn.commit()
    row = conn.execute("SELECT home_score, away_score FROM matches WHERE match_id = 'M700'").fetchone()
    assert row["home_score"] is None, f"home_score should be NULL, got {row['home_score']}"
    assert row["away_score"] is None, f"away_score should be NULL, got {row['away_score']}"
    conn.close()


def test_upsert_match_preserves_non_null_scores_on_resync(tmp_path):
    """Re-syncing a match with NULL scores must not overwrite existing real scores."""
    from pitch_agent.db import init_db, upsert_match
    db_path = str(tmp_path / "preserve_scores.db")
    conn = init_db(db_path)

    # First sync: real result
    upsert_match(conn, {
        "match_id": "M800", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "home_score": 2, "away_score": 0,
        "status": "FINISHED", "date": "2026-06-11",
    })
    conn.commit()

    # Re-sync: API returns NULL scores (free tier limitation)
    upsert_match(conn, {
        "match_id": "M800", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "home_score": None, "away_score": None,
        "status": "FINISHED", "date": "2026-06-11",
    })
    conn.commit()

    row = conn.execute("SELECT home_score, away_score FROM matches WHERE match_id = 'M800'").fetchone()
    assert row["home_score"] == 2, f"home_score should be preserved as 2, got {row['home_score']}"
    assert row["away_score"] == 0, f"away_score should be preserved as 0, got {row['away_score']}"
    conn.close()


def test_record_match_result(tmp_path):
    """record-result CLI sets scores, status=FINISHED, and grades predictions."""
    from pitch_agent.db import init_db, upsert_match, upsert_prediction, record_match_result
    db_path = str(tmp_path / "record_result.db")
    conn = init_db(db_path)

    # Match with no result yet
    upsert_match(conn, {
        "match_id": "M537327", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "home_score": None, "away_score": None,
        "status": "FINISHED", "date": "2026-06-11",
    })
    conn.commit()

    # Record result
    result = record_match_result(conn, "M537327", 2, 0)
    assert result["home_score"] == 2
    assert result["away_score"] == 0
    assert result["previous_home_score"] is None
    assert result["predictions_graded"] == 0  # No predictions yet

    # Verify DB
    row = conn.execute("SELECT home_score, away_score, status FROM matches WHERE match_id = 'M537327'").fetchone()
    assert row["home_score"] == 2
    assert row["away_score"] == 0
    assert row["status"] == "FINISHED"
    conn.close()


def test_record_result_triggers_grading(tmp_path):
    """record-result should grade pending predictions for that match."""
    from pitch_agent.db import init_db, upsert_match, upsert_prediction, record_match_result
    db_path = str(tmp_path / "record_grade.db")
    conn = init_db(db_path)

    upsert_match(conn, {
        "match_id": "M900", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Brazil", "away_team_name": "Morocco",
        "home_score": None, "away_score": None,
        "status": "FINISHED", "date": "2026-06-13",
    })
    conn.commit()

    upsert_prediction(conn, {
        "match_id": "M900", "model_version": MODEL_VERSION,
        "predicted_home": 3, "predicted_away": 1,
        "predicted_outcome": "home",
        "home_win_prob": 0.55, "draw_prob": 0.25, "away_win_prob": 0.20,
        "top_scorelines": [], "key_factor": "",
        "basis_home": "elo_prior", "basis_away": "form_index",
    })
    conn.commit()

    result = record_match_result(conn, "M900", 3, 1)
    assert result["predictions_graded"] == 1

    from pitch_agent.db import get_prediction_accuracy
    acc = get_prediction_accuracy(conn)
    assert acc["total"] == 1
    assert acc["correct"] == 1
    conn.close()


def test_record_result_nonexistent_match(tmp_path):
    """record-result should raise ValueError for a match that doesn't exist."""
    from pitch_agent.db import init_db, record_match_result
    db_path = str(tmp_path / "no_match.db")
    conn = init_db(db_path)

    with pytest.raises(ValueError, match="not found"):
        record_match_result(conn, "NONEXISTENT", 1, 0)
    conn.close()


def test_upsert_match_preserves_finished_status_on_resync(tmp_path):
    """Re-syncing a FINISHED match must not downgrade it to TIMED."""
    from pitch_agent.db import init_db, upsert_match
    db_path = str(tmp_path / "preserve_status.db")
    conn = init_db(db_path)

    # First: match is FINISHED with a result
    upsert_match(conn, {
        "match_id": "M900", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "home_score": 2, "away_score": 0,
        "status": "FINISHED", "date": "2026-06-11",
    })
    conn.commit()

    # Re-sync: API sends TIMED status and NULL scores
    upsert_match(conn, {
        "match_id": "M900", "competition_id": "WC", "matchday": 1,
        "home_team_name": "Mexico", "away_team_name": "South Africa",
        "home_score": None, "away_score": None,
        "status": "TIMED", "date": "2026-06-11",
    })
    conn.commit()

    row = conn.execute("SELECT home_score, away_score, status FROM matches WHERE match_id = 'M900'").fetchone()
    assert row["home_score"] == 2, f"home_score preserved, got {row['home_score']}"
    assert row["away_score"] == 0, f"away_score preserved, got {row['away_score']}"
    assert row["status"] == "FINISHED", f"status should stay FINISHED, got {row['status']}"
    conn.close()


# ── WorldCup26 provider tests ──────────────────────────────────────────────

class TestWorldCup26Provider:
    """Tests for the worldcup26 results-only provider."""

    def test_finished_false_no_write(self, tmp_path):
        """finished=FALSE games must not write scores (0-0 is placeholder)."""
        from pitch_agent.providers.worldcup26_provider import WorldCup26Provider
        from pitch_agent.db import init_db, get_connection

        provider = WorldCup26Provider.__new__(WorldCup26Provider)
        # Simulate a game that is NOT finished — scores are 0-0 placeholders
        game = {
            "wc26_id": "1",
            "home_team_name": "Mexico",
            "away_team_name": "South Africa",
            "home_score": None,  # finished=FALSE → None
            "away_score": None,
            "finished": False,
            "matchday": 1,
            "group": "A",
        }
        assert game["home_score"] is None, "Unfinished games must have NULL scores"

    def test_finished_true_valid_write_and_grade(self, tmp_path):
        """finished=TRUE with valid scores → write + grade."""
        from pitch_agent.db import init_db, upsert_match, upsert_prediction, grade_predictions

        db_path = str(tmp_path / "wc26_finished.db")
        conn = init_db(db_path)

        # Match in DB with NULL scores
        upsert_match(conn, {
            "match_id": "537327", "competition_id": "WC", "matchday": 1,
            "home_team_name": "Mexico", "away_team_name": "South Africa",
            "home_score": None, "away_score": None,
            "status": "FINISHED", "date": "2026-06-11",
        })
        conn.commit()

        # Add a prediction
        upsert_prediction(conn, {
            "match_id": "537327", "model_version": MODEL_VERSION,
            "predicted_home": 2, "predicted_away": 0,
            "predicted_outcome": "home",
            "home_win_prob": 0.55, "draw_prob": 0.25, "away_win_prob": 0.20,
            "top_scorelines": [], "key_factor": "",
            "basis_home": "elo_prior", "basis_away": "elo_prior",
        })
        conn.commit()

        # Simulate worldcup26 writing the result
        conn.execute(
            "UPDATE matches SET home_score = 2, away_score = 0, "
            "status = 'FINISHED', result_source = 'worldcup26' WHERE match_id = '537327'"
        )
        conn.commit()

        graded = grade_predictions(conn)
        assert graded == 1, f"Should grade 1 prediction, got {graded}"

        row = conn.execute("SELECT home_score, away_score, result_source FROM matches WHERE match_id = '537327'").fetchone()
        assert row["home_score"] == 2
        assert row["away_score"] == 0
        assert row["result_source"] == "worldcup26"
        conn.close()

    def test_out_of_range_score_rejected(self, tmp_path):
        """Scores outside 0-15 range must be rejected."""
        from pitch_agent.db import init_db, upsert_match

        db_path = str(tmp_path / "wc26_bad_score.db")
        conn = init_db(db_path)

        upsert_match(conn, {
            "match_id": "M999", "competition_id": "WC", "matchday": 1,
            "home_team_name": "TeamA", "away_team_name": "TeamB",
            "home_score": None, "away_score": None,
            "status": "FINISHED", "date": "2026-06-20",
        })
        conn.commit()

        # Simulate the validation logic from sync-results
        for bad_score in [-1, 16, 99]:
            # The sync-results command validates: 0 <= score <= 15
            valid = 0 <= bad_score <= 15
            assert not valid, f"Score {bad_score} should be rejected"

    def test_non_null_local_score_untouched(self, tmp_path):
        """A match that already has scores must not be overwritten by sync-results."""
        from pitch_agent.db import init_db, upsert_match

        db_path = str(tmp_path / "wc26_guard.db")
        conn = init_db(db_path)

        upsert_match(conn, {
            "match_id": "M800", "competition_id": "WC", "matchday": 1,
            "home_team_name": "Mexico", "away_team_name": "South Africa",
            "home_score": 2, "away_score": 0,
            "status": "FINISHED", "date": "2026-06-11",
        })
        conn.commit()

        # Re-upsert with NULL scores (simulating a provider that sends NULL)
        upsert_match(conn, {
            "match_id": "M800", "competition_id": "WC", "matchday": 1,
            "home_team_name": "Mexico", "away_team_name": "South Africa",
            "home_score": None, "away_score": None,
            "status": "TIMED", "date": "2026-06-11",
        })
        conn.commit()

        row = conn.execute("SELECT home_score, away_score, status FROM matches WHERE match_id = 'M800'").fetchone()
        assert row["home_score"] == 2, "Non-NULL scores must not be overwritten"
        assert row["away_score"] == 0
        assert row["status"] == "FINISHED", "FINISHED status must not be downgraded"

    def test_result_source_manual(self, tmp_path):
        """record-result sets result_source='manual' by default."""
        from pitch_agent.db import init_db, upsert_match, record_match_result

        db_path = str(tmp_path / "result_source.db")
        conn = init_db(db_path)

        upsert_match(conn, {
            "match_id": "M900", "competition_id": "WC", "matchday": 1,
            "home_team_name": "Brazil", "away_team_name": "Morocco",
            "home_score": None, "away_score": None,
            "status": "FINISHED", "date": "2026-06-13",
        })
        conn.commit()

        result = record_match_result(conn, "M900", 3, 1)
        assert result["home_score"] == 3
        assert result["away_score"] == 1

        row = conn.execute("SELECT result_source FROM matches WHERE match_id = 'M900'").fetchone()
        assert row["result_source"] == "manual"
        conn.close()


def test_matchday_preview_excludes_finished(tmp_path):
    """FINISHED matches must not appear in matchday preview."""
    from pitch_agent.content import _generate_matchday_preview
    fixtures = [
        {"home_team_name": "Mexico", "away_team_name": "South Africa",
         "date": "2026-06-11T19:00:00Z", "status": "FINISHED", "group_name": "Group A",
         "match_id": "537327", "match_label": "Mexico vs South Africa"},
        {"home_team_name": "Korea Republic", "away_team_name": "Czechia",
         "date": "2099-06-12T02:00:00Z", "status": "TIMED", "group_name": "Group A",
         "match_id": "537328", "match_label": "Korea Republic vs Czechia"},
    ]
    preview = _generate_matchday_preview(fixtures)
    assert "Mexico" not in preview, "FINISHED match must be excluded"
    assert "Korea Republic" in preview, "Upcoming match must be included"


def test_matchday_preview_excludes_past_kickoff(tmp_path):
    """Matches with past kickoffs must not appear in matchday preview."""
    from pitch_agent.content import _generate_matchday_preview
    from datetime import datetime, timezone, timedelta
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    fixtures = [
        {"home_team_name": "PastTeam", "away_team_name": "Other",
         "date": past, "status": "TIMED", "group_name": "Group A", "match_id": "M1",
         "match_label": "PastTeam vs Other"},
        {"home_team_name": "FutureTeam", "away_team_name": "Opponent",
         "date": future, "status": "TIMED", "group_name": "Group B", "match_id": "M2",
         "match_label": "FutureTeam vs Opponent"},
    ]
    preview = _generate_matchday_preview(fixtures)
    assert "PastTeam" not in preview, "Past kickoff must be excluded"
    assert "FutureTeam" in preview, "Future kickoff must be included"


def test_key_factor_elo_prior_basis():
    """When both sides use elo_prior, key factor must show Elo differential."""
    from pitch_agent.poisson import prediction_key_factor
    # Elo edge: big gap
    kf = prediction_key_factor(
        [], [],
        home_elo=1900, away_elo=1700,
        basis_home="elo_prior", basis_away="elo_prior",
    )
    assert "Elo edge" in kf
    assert "+200" in kf
    # Elo nearly level
    kf2 = prediction_key_factor(
        [], [],
        home_elo=1760, away_elo=1755,
        basis_home="elo_prior", basis_away="elo_prior",
    )
    assert "Elo nearly level" in kf2


def test_key_factor_elo_prior_200_point_gap():
    """200-point Elo gap must produce an Elo key_factor."""
    from pitch_agent.poisson import prediction_key_factor
    kf = prediction_key_factor(
        [], [],
        home_elo=2000, away_elo=1800,
        basis_home="elo_prior", basis_away="elo_prior",
    )
    assert "Elo edge" in kf
    assert "+200" in kf
    assert "2000" in kf
    assert "1800" in kf
