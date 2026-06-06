"""API-Football provider — paid/richer provider path.

This provider is **not** required for the MVP.  It is included to show
the upgrade path and will raise ``NotImplementedError`` until fully
implemented with a paid API-Football key.
"""
from __future__ import annotations

from typing import Any

from pitch_agent.providers import DataProvider


class APIFootballProvider(DataProvider):
    """Paid/richer provider path — not yet implemented for v1.0 Lite.

    API-Football (api-football.com) provides live match data and richer
    per-player statistics.  This stub marks the upgrade path for Form
    Index v2.
    """

    def fetch_competitions(self) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "API-Football provider is a paid/richer upgrade path and is "
            "not yet implemented.  Use --provider csv or --provider football-data."
        )

    def fetch_matches(self, competition_id: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "API-Football provider is a paid/richer upgrade path and is "
            "not yet implemented.  Use --provider csv or --provider football-data."
        )

    def fetch_match_stats(self, match_id: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "API-Football provider is a paid/richer upgrade path and is "
            "not yet implemented.  Use --provider csv or --provider football-data."
        )