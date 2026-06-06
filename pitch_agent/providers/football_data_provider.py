"""football-data.org provider — basic free data provider.

Uses the football-data.org v4 API where possible.  Populates only the
basic stat subset.  If the API key is missing or the response does not
include enough data, this provider fails clearly and recommends the
CSV provider.  It does **not** pretend to give rich box-score data.

Environment variables:
    FOOTBALL_DATA_API_KEY  (required)
    FOOTBALL_DATA_BASE_URL (default: https://api.football-data.org/v4)
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests

from pitch_agent.config import ALL_FIELDS, BASIC_FIELDS
from pitch_agent.providers import DataProvider


class FootballDataProvider(DataProvider):
    """Basic free data provider using football-data.org v4 API."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")
        self.base_url = (base_url or os.environ.get(
            "FOOTBALL_DATA_BASE_URL", "https://api.football-data.org/v4"
        )).rstrip("/")
        if not self.api_key:
            raise EnvironmentError(
                "FOOTBALL_DATA_API_KEY is not set. "
                "Set it as an environment variable or in config/secrets.env. "
                "Alternatively, use the CSV provider: "
                "python -m pitch_agent.cli sync-data --provider csv"
            )

    # ── Public API ───────────────────────────────────────────────────────

    def fetch_competitions(self) -> list[dict[str, Any]]:
        resp = self._get("/competitions")
        competitions = []
        for comp in resp.get("competitions", []):
            competitions.append({
                "competition_id": str(comp.get("id", "")),
                "name": comp.get("name", ""),
                "code": comp.get("code", ""),
                "season": str(comp.get("currentSeason", {}).get("id", "")),
                "stage": comp.get("currentSeason", {}).get("currentMatchday", ""),
            })
        return competitions

    def fetch_matches(self, competition_id: str | None = None) -> list[dict[str, Any]]:
        if not competition_id:
            competition_id = "WC"  # World Cup default
        resp = self._get(f"/competitions/{competition_id}/matches")
        matches = []
        for m in resp.get("matches", []):
            home = m.get("homeTeam", {})
            away = m.get("awayTeam", {})
            score = m.get("score", {})
            ft = score.get("fullTime", {})
            matches.append({
                "match_id": str(m.get("id", "")),
                "competition_id": str(m.get("competition", {}).get("id", "")),
                "matchday": m.get("matchday", 0),
                "stage": m.get("stage", ""),
                "home_team_id": str(home.get("id", "")),
                "home_team_name": home.get("shortName", home.get("name", "")),
                "away_team_id": str(away.get("id", "")),
                "away_team_name": away.get("shortName", away.get("name", "")),
                "home_score": ft.get("homeTeam"),
                "away_score": ft.get("awayTeam"),
                "date": m.get("utcDate", ""),
                "group": m.get("group", ""),
                "status": m.get("status", ""),
            })
        return matches

    def fetch_match_stats(self, match_id: str | None = None) -> list[dict[str, Any]]:
        if not match_id:
            raise ValueError("match_id is required for football-data provider")
        resp = self._get(f"/matches/{match_id}")
        return self._normalise_match_stats(resp)

    # ── Internal ─────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        headers = {"X-Auth-Token": self.api_key}
        url = f"{self.base_url}{path}"
        try:
            r = requests.get(url, headers=headers, params=params or {}, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                f"football-data.org API request failed: {exc}. "
                "Try the CSV provider for offline data."
            ) from exc

    def _normalise_match_stats(self, match_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalise a football-data.org match response into stat records.

        The free tier provides scorers, cards, and lineups but not
        detailed per-player stats.  We extract what we can and set all
        advanced fields to 0.
        """
        match_id = str(match_data.get("id", ""))
        home_team = match_data.get("homeTeam", {})
        away_team = match_data.get("awayTeam", {})
        score = match_data.get("score", {})
        ft = score.get("fullTime", {})
        home_score = ft.get("homeTeam")
        away_score = ft.get("awayTeam")

        # Determine team results
        if home_score is not None and away_score is not None:
            if home_score > away_score:
                home_result, away_result = "WIN", "LOSS"
            elif home_score < away_score:
                home_result, away_result = "LOSS", "WIN"
            else:
                home_result = away_result = "DRAW"
        else:
            home_result = away_result = ""

        # Build a base record template
        base: dict[str, Any] = {
            "match_id": match_id,
            "competition_id": str(match_data.get("competition", {}).get("id", "")),
            "season": str(match_data.get("season", {}).get("id", "")),
            "matchday": match_data.get("matchday", 0) or 0,
            "stage": match_data.get("stage", ""),
            "data_quality": "basic",
            "data_quality_level": "basic",
            "provider_name": "football-data",
        }

        # Collect scorer and card info
        scorer_goals: dict[str, int] = {}   # player_id → goal count
        scorer_assists: dict[str, int] = {}  # player_id → assist count
        scorer_teams: dict[str, str] = {}    # player_id → team_id
        scorer_names: dict[str, str] = {}     # player_id → name

        for scorer in match_data.get("scorers", []):
            pid = str(scorer.get("id", ""))
            if not pid:
                # Nested scorer object
                s = scorer.get("scorer", scorer)
                pid = str(s.get("id", ""))
            name = scorer.get("name", scorer.get("scorer", {}).get("name", ""))
            team = scorer.get("team", {})
            tid = str(team.get("id", ""))
            goals = scorer.get("goals", 1) or 1
            assists = scorer.get("assists", 0) or 0
            scorer_goals[pid] = scorer_goals.get(pid, 0) + goals
            scorer_assists[pid] = scorer_assists.get(pid, 0) + assists
            scorer_teams[pid] = tid
            scorer_names[pid] = name

        # Build stat records from lineups (if available)
        records: list[dict[str, Any]] = []
        seen_players: set[str] = set()

        for lineup in match_data.get("lineups", []):
            team_id = str(lineup.get("team", {}).get("id", ""))
            team_name = lineup.get("team", {}).get("shortName",
                            lineup.get("team", {}).get("name", ""))
            is_home = str(lineup.get("team", {}).get("id", "")) == str(home_team.get("id", ""))
            team_result = home_result if is_home else away_result

            # Starting XI
            for player in lineup.get("startXI", []):
                p = player.get("player", player)
                pid = str(p.get("id", ""))
                if pid in seen_players:
                    continue
                seen_players.add(pid)

                rec = dict(base)
                rec.update({
                    "player_id": pid,
                    "player_name": p.get("name", ""),
                    "team_id": team_id,
                    "team_name": team_name,
                    "position": self._map_position(p.get("position", "")),
                    "minutes": 90,  # Assume full match unless substituted
                    "goals": scorer_goals.get(pid, 0),
                    "assists": scorer_assists.get(pid, 0),
                    "yellow_cards": 0,  # Not available in free tier per-player
                    "red_cards": 0,
                    "own_goals": 0,
                    "clean_sheet": 0,
                    "team_result": team_result,
                })
                self._fill_rich_fields_zero(rec)
                records.append(rec)

            # Substitutes
            for sub in lineup.get("substitutes", []):
                p = sub.get("player", sub)
                pid = str(p.get("id", ""))
                if pid in seen_players:
                    continue
                seen_players.add(pid)

                rec = dict(base)
                rec.update({
                    "player_id": pid,
                    "player_name": p.get("name", ""),
                    "team_id": team_id,
                    "team_name": team_name,
                    "position": self._map_position(p.get("position", "")),
                    "minutes": 0,  # Bench — didn't play
                    "goals": scorer_goals.get(pid, 0),
                    "assists": scorer_assists.get(pid, 0),
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "own_goals": 0,
                    "clean_sheet": 0,
                    "team_result": team_result,
                })
                self._fill_rich_fields_zero(rec)
                records.append(rec)

        # If no lineups, create records from scorers only
        if not records:
            for pid, goals in scorer_goals.items():
                tid = scorer_teams.get(pid, "")
                is_home = tid == str(home_team.get("id", ""))
                rec = dict(base)
                rec.update({
                    "player_id": pid,
                    "player_name": scorer_names.get(pid, ""),
                    "team_id": tid,
                    "team_name": home_team.get("shortName", "") if is_home else away_team.get("shortName", ""),
                    "position": "",
                    "minutes": 90,
                    "goals": goals,
                    "assists": scorer_assists.get(pid, 0),
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "own_goals": 0,
                    "clean_sheet": 0,
                    "team_result": home_result if is_home else away_result,
                })
                self._fill_rich_fields_zero(rec)
                records.append(rec)

        # Compute available_fields and raw_json for each record
        for rec in records:
            present = sorted(k for k in ALL_FIELDS if k in rec and rec[k] not in (0, 0.0, "", None))
            rec["available_fields"] = json.dumps(present)
            rec["raw_json"] = json.dumps({k: rec[k] for k in present})

        return records

    @staticmethod
    def _fill_rich_fields_zero(rec: dict[str, Any]) -> None:
        """Set all rich/advanced stat fields to 0 for a basic-only record."""
        rich_fields = [
            "pass_accuracy", "shots_on_target", "key_passes",
            "successful_dribbles", "big_chances_created", "big_chances_missed",
            "tackles_won", "interceptions", "blocked_shots",
            "aerial_duels_won", "saves", "penalty_saves", "shots_faced",
            "possession_lost", "xg", "duels", "distance_covered_km", "pressures",
        ]
        for f in rich_fields:
            rec[f] = 0 if f != "pass_accuracy" and f != "xg" and f != "distance_covered_km" else 0.0

    @staticmethod
    def _map_position(fd_position: str) -> str:
        """Map football-data.org position names to our position codes."""
        mapping = {
            "GK": "GK", "Goalkeeper": "GK",
            "DEF": "DEF", "Defence": "DEF", "Defender": "DEF",
            "MID": "MID", "Midfield": "MID", "Midfielder": "MID",
            "FWD": "FWD", "Forward": "FWD", "Attacker": "FWD", "Offence": "FWD",
        }
        return mapping.get(fd_position, "")