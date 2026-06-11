"""worldcup26.ir results provider — live scores for FIFA World Cup 2026.

Uses the worldcup26.ir API to fetch finished match results. This is a
**results-only** provider — it does NOT sync fixtures or player stats.
It fills in home_score/away_score for FINISHED matches where our primary
provider (football-data.org free tier) returns NULL scores.

CRITICAL: their API uses 0-0 placeholders with ``finished=FALSE`` for
upcoming matches. We map ``finished=FALSE`` to NULL scores — **never**
write 0-0 from this provider unless ``finished=TRUE``.

Authentication: JWT via register/login. Token is cached locally in
``~/.config/social-media-kit/wc26_token.json`` and reused until expiry.
Credentials come from environment variables ``WC26_EMAIL`` and
``WC26_PASSWORD``, or from ``pitch_agent.yaml`` config.

Handles API downtime gracefully — warns and exits 0 (cron-safe).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ── Team name mapping (worldcup26 name → our DB name) ────────────────────
# The worldcup26 API uses different names for some teams.
TEAM_NAME_MAP: dict[str, str] = {
    "South Korea": "Korea Republic",
    "Bosnia and Herzegovina": "Bosnia-H.",
    "Czech Republic": "Czechia",
    "United States": "USA",
    "Turkiye": "Turkey",
    "Ivory Coast": "Ivory Coast",
    "Cape Verde": "Cape Verde",
    "Curaçao": "Curaçao",
}

# ── JWT Token Cache ────────────────────────────────────────────────────────

_TOKEN_CACHE_PATH = Path(
    os.environ.get("WC26_TOKEN_PATH")
    or os.path.join(os.path.expanduser("~"), ".config", "social-media-kit", "wc26_token.json")
)

_TOKEN_TTL_SECONDS = 7_200_000  # ~83 days (API tokens valid 84 days)


class WorldCup26Provider:
    """Results-only provider for worldcup26.ir API."""

    BASE_URL = "https://worldcup26.ir"

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
    ):
        self.email = email or os.environ.get("WC26_EMAIL", "")
        self.password = password or os.environ.get("WC26_PASSWORD", "")
        self._token: str | None = None

    # ── Authentication ────────────────────────────────────────────────────

    def _load_cached_token(self) -> str | None:
        """Load a cached JWT token if still valid."""
        try:
            if _TOKEN_CACHE_PATH.exists():
                data = json.loads(_TOKEN_CACHE_PATH.read_text())
                if data.get("token") and time.time() < data.get("expires_at", 0):
                    return data["token"]
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _save_token(self, token: str) -> None:
        """Cache the JWT token with expiry."""
        _TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "token": token,
            "expires_at": time.time() + _TOKEN_TTL_SECONDS,
        }
        _TOKEN_CACHE_PATH.write_text(json.dumps(data))

    def _authenticate(self) -> str:
        """Get a valid JWT token, registering if needed."""
        # Try cached token first
        cached = self._load_cached_token()
        if cached:
            return cached

        # Try login
        try:
            resp = requests.post(
                f"{self.BASE_URL}/auth/authenticate",
                json={"email": self.email, "password": self.password},
                timeout=15,
            )
            if resp.status_code == 200:
                token = resp.json().get("token")
                if token:
                    self._save_token(token)
                    return token
        except requests.RequestException:
            pass

        # Try register
        try:
            resp = requests.post(
                f"{self.BASE_URL}/auth/register",
                json={
                    "name": "PitchAgent",
                    "email": self.email,
                    "password": self.password,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                token = resp.json().get("token")
                if token:
                    self._save_token(token)
                    return token
        except requests.RequestException:
            pass

        raise RuntimeError(
            "worldcup26.ir authentication failed. "
            "Set WC26_EMAIL and WC26_PASSWORD env vars."
        )

    def _get_token(self) -> str:
        """Ensure we have a token, authenticating if necessary."""
        if not self._token:
            self._token = self._authenticate()
        return self._token

    # ── API Calls ─────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        """Make an authenticated GET request to the worldcup26 API."""
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = requests.get(
                f"{self.BASE_URL}{path}",
                headers=headers,
                params=params or {},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"worldcup26.ir API request failed: {exc}"
            ) from exc

    def fetch_games(self) -> list[dict[str, Any]]:
        """Fetch all games from /get/games.

        Returns a list of game dicts with normalised fields:
            id, home_team_id, away_team_id, home_team_name, away_team_name,
            home_score, away_score, finished, matchday, group, type,
            local_date, stadium_id
        """
        try:
            data = self._get("/get/games")
        except RuntimeError as exc:
            print(f"[pitch_agent] worldcup26.ir fetch failed: {exc}", file=sys.stderr)
            print("[pitch_agent] Skipping worldcup26 result sync — API unavailable.", file=sys.stderr)
            return []

        games = data.get("games", [])
        if not games:
            print("[pitch_agent] worldcup26.ir returned 0 games.", file=sys.stderr)

        normalised = []
        for g in games:
            # CRITICAL: finished=FALSE means upcoming — scores are 0-0 placeholders
            # Only use scores when finished=TRUE
            finished = str(g.get("finished", "FALSE")).upper() == "TRUE"
            home_score = int(g.get("home_score", 0)) if finished else None
            away_score = int(g.get("away_score", 0)) if finished else None
            home_name = g.get("home_team_name_en", "")
            away_name = g.get("away_team_name_en", "")

            normalised.append({
                "wc26_id": str(g.get("id", "")),
                "home_team_id": str(g.get("home_team_id", "")),
                "away_team_id": str(g.get("away_team_id", "")),
                "home_team_name": TEAM_NAME_MAP.get(home_name, home_name),
                "away_team_name": TEAM_NAME_MAP.get(away_name, away_name),
                "home_score": home_score,
                "away_score": away_score,
                "finished": finished,
                "matchday": int(g.get("matchday", 0) or 0),
                "group": g.get("group", ""),
                "type": g.get("type", ""),
                "local_date": g.get("local_date", ""),
                "stadium_id": str(g.get("stadium_id", "")),
            })
        return normalised

    def fetch_game(self, game_id: str) -> dict[str, Any] | None:
        """Fetch a single game by ID from /get/game/{id}."""
        try:
            data = self._get(f"/get/game/{game_id}")
        except RuntimeError:
            return None
        game = data.get("game", data)
        if not game:
            return None
        finished = str(game.get("finished", "FALSE")).upper() == "TRUE"
        home_score = int(game.get("home_score", 0)) if finished else None
        away_score = int(game.get("away_score", 0)) if finished else None
        home_name = game.get("home_team_name_en", "")
        away_name = game.get("away_team_name_en", "")
        return {
            "wc26_id": str(game.get("id", "")),
            "home_team_id": str(game.get("home_team_id", "")),
            "away_team_id": str(game.get("away_team_id", "")),
            "home_team_name": TEAM_NAME_MAP.get(home_name, home_name),
            "away_team_name": TEAM_NAME_MAP.get(away_name, away_name),
            "home_score": home_score,
            "away_score": away_score,
            "finished": finished,
            "matchday": int(game.get("matchday", 0) or 0),
            "group": game.get("group", ""),
            "type": game.get("type", ""),
            "local_date": game.get("local_date", ""),
        }