"""Data provider base class and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DataProvider(ABC):
    """Abstract base class for data providers."""

    @abstractmethod
    def fetch_competitions(self) -> list[dict[str, Any]]:
        """Return a list of competition dicts."""

    @abstractmethod
    def fetch_matches(self, competition_id: str) -> list[dict[str, Any]]:
        """Return a list of match dicts for a competition."""

    @abstractmethod
    def fetch_match_stats(self, match_id: str) -> list[dict[str, Any]]:
        """Return a list of player-match-stat dicts for a match."""


# ── Registry ────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, type[DataProvider]] = {}


def register_provider(name: str, cls: type[DataProvider]) -> None:
    _PROVIDERS[name] = cls


def get_provider(name: str) -> DataProvider:
    """Instantiate and return a provider by name."""
    if name not in _PROVIDERS:
        raise ValueError(
            f"Unknown provider '{name}'. "
            f"Available: {', '.join(sorted(_PROVIDERS))}"
        )
    return _PROVIDERS[name]()


# ── Lazy imports (avoid heavy deps at top level) ─────────────────────────────

def _auto_register() -> None:
    from pitch_agent.providers.csv_provider import CSVProvider
    from pitch_agent.providers.football_data_provider import FootballDataProvider
    from pitch_agent.providers.api_football_provider import APIFootballProvider

    register_provider("csv", CSVProvider)
    register_provider("football-data", FootballDataProvider)
    register_provider("api-football", APIFootballProvider)


_auto_registered = False


def ensure_registered() -> None:
    global _auto_registered
    if not _auto_registered:
        _auto_register()
        _auto_registered = True