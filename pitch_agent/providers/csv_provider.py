"""CSV data provider — guaranteed offline/demo data source.

Reads sample CSV files from the ``pitch_agent/data/`` directory and
normalises them into the internal database format.  This provider always
sets ``data_quality_level = "basic"`` and ``provider_name = "csv"``.
Missing advanced fields are set to 0.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pitch_agent.config import ALL_FIELDS, BASIC_FIELDS
from pitch_agent.providers import DataProvider


class CSVProvider(DataProvider):
    """Offline/demo provider reading from local CSV files."""

    def __init__(self, data_dir: str | Path | None = None):
        if data_dir is None:
            from pitch_agent.config import ROOT
            data_dir = ROOT / "pitch_agent" / "data"
        self.data_dir = Path(data_dir)

    # ── Public API ───────────────────────────────────────────────────────

    def fetch_competitions(self) -> list[dict[str, Any]]:
        rows = self._read_csv("competitions.csv")
        return [dict(r) for r in rows]

    def fetch_matches(self, competition_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._read_csv("matches.csv")
        if competition_id:
            rows = [r for r in rows if r.get("competition_id") == competition_id]
        return [dict(r) for r in rows]

    def fetch_match_stats(self, match_id: str | None = None) -> list[dict[str, Any]]:
        """Return normalised stat dicts ready for ``upsert_player_match_stats``."""
        rows = self._read_csv("stats.csv")
        if match_id:
            rows = [r for r in rows if r.get("match_id") == match_id]

        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(self._normalise_row(row))
        return result

    # ── Helpers ──────────────────────────────────────────────────────────

    def _normalise_row(self, row: dict[str, str]) -> dict[str, Any]:
        """Convert a CSV row (all strings) to a typed stat record."""
        # Type conversions
        int_fields = {
            "goals", "assists", "minutes", "yellow_cards", "red_cards",
            "own_goals", "clean_sheet", "shots_on_target", "key_passes",
            "successful_dribbles", "big_chances_created", "big_chances_missed",
            "tackles_won", "interceptions", "blocked_shots",
            "aerial_duels_won", "saves", "penalty_saves", "shots_faced",
            "possession_lost", "duels", "pressures", "matchday",
        }
        float_fields = {
            "pass_accuracy", "xg", "distance_covered_km",
        }

        record: dict[str, Any] = {}
        present_fields: list[str] = []

        for key in ALL_FIELDS:
            if key in row and row[key].strip():
                if key in int_fields:
                    record[key] = int(row[key])
                elif key in float_fields:
                    record[key] = float(row[key])
                else:
                    record[key] = row[key]
                present_fields.append(key)
            elif key == "team_result":
                record[key] = row.get(key, "")
            else:
                # Missing field → default to 0
                record[key] = 0

        # Copy identity fields directly
        for key in ("match_id", "player_id", "player_name", "team_id",
                     "team_name", "position", "competition_id", "season",
                     "matchday", "stage"):
            if key in row:
                if key == "matchday":
                    record[key] = int(row[key]) if row[key].strip() else 0
                else:
                    record[key] = row[key]

        # Metadata
        record["data_quality"] = "basic"
        record["data_quality_level"] = "basic"
        record["provider_name"] = "csv"
        record["available_fields"] = json.dumps(sorted(present_fields))
        record["raw_json"] = json.dumps({k: record.get(k) for k in present_fields})

        return record

    def _read_csv(self, filename: str) -> list[dict[str, str]]:
        path = self.data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)