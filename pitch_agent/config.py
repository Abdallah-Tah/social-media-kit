"""Configuration for The Pitch Agent.

Mirrors the social-media-kit config pattern: YAML file + env vars + secrets.env.
No hard dependency on python-dotenv — we ship a tiny .env parser.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Project root = parent of the `pitch_agent/` package directory.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "pitch_agent.yaml"
OPENCLAW_SECRETS_PATH = Path(os.path.expanduser("~/.config/openclaw/secrets.env"))

SECRETS_CANDIDATES = [
    CONFIG_DIR / "secrets.env",
    Path(os.path.expanduser("~/.config/social-media-kit/secrets.env")),
    OPENCLAW_SECRETS_PATH,
]

BASIC_FIELDS = [
    "goals", "assists", "minutes", "yellow_cards", "red_cards",
    "own_goals", "clean_sheet", "team_result",
]

RICH_FIELDS = [
    "pass_accuracy", "shots_on_target", "key_passes",
    "successful_dribbles", "big_chances_created", "big_chances_missed",
    "tackles_won", "interceptions", "blocked_shots",
    "aerial_duels_won", "saves", "penalty_saves",
    "shots_faced", "possession_lost", "xg",
    "duels", "distance_covered_km", "pressures",
]

ALL_FIELDS = BASIC_FIELDS + RICH_FIELDS


def load_env() -> None:
    """Load secrets files into os.environ (without clobbering real env vars)."""
    for path in SECRETS_CANDIDATES:
        if path.exists():
            _load_env_file(path)
    _prefer_openclaw_telegram_secrets()
    _normalise_env_aliases()


def _load_env_file(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _normalise_env_aliases() -> None:
    """Support OpenClaw secret names without duplicating values."""
    aliases = {
        "TELEGRAM_BOT_TOKEN": "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID": "CHAT_ID",
        "BWA_ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
    }
    for canonical, alias in aliases.items():
        if not os.environ.get(canonical) and os.environ.get(alias):
            os.environ[canonical] = os.environ[alias]


def _prefer_openclaw_telegram_secrets() -> None:
    """Let OpenClaw's Telegram target override workspace Telegram defaults."""
    if not OPENCLAW_SECRETS_PATH.exists():
        return
    values = _read_env_values(OPENCLAW_SECRETS_PATH)
    for key in ("TELEGRAM_TOKEN", "CHAT_ID", "TELEGRAM_MESSAGE_THREAD_ID"):
        if values.get(key):
            os.environ[key] = values[key]
    if values.get("TELEGRAM_TOKEN"):
        os.environ["TELEGRAM_BOT_TOKEN"] = values["TELEGRAM_TOKEN"]
    if values.get("CHAT_ID"):
        os.environ["TELEGRAM_CHAT_ID"] = values["CHAT_ID"]


def _read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass
class PitchAgentConfig:
    """Resolved runtime settings for The Pitch Agent."""

    db_path: str = "pitch_agent.db"
    data_dir: str = str(ROOT / "pitch_agent" / "data")
    model_version: str = "1.0.0-lite"

    # Content settings
    headline_index_mode: str = "daily"
    cumulative_index_enabled_after_group_stage: bool = True

    # Provider settings
    football_data_api_key: str = ""
    football_data_base_url: str = "https://api.football-data.org/v4"

    @classmethod
    def load(
        cls,
        config_path: Path | str | None = None,
    ) -> "PitchAgentConfig":
        """Build config from pitch_agent.yaml + environment + secrets.env."""
        load_env()

        path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        settings = _read_yaml(path)

        content = settings.get("content", {})

        return cls(
            db_path=os.environ.get("PITCH_AGENT_DB", settings.get("db_path", "pitch_agent.db")),
            data_dir=os.environ.get("PITCH_AGENT_DATA_DIR", settings.get("data_dir", str(ROOT / "pitch_agent" / "data"))),
            model_version=settings.get("model_version", "1.0.0-lite"),
            headline_index_mode=content.get("headline_index_mode", "daily"),
            cumulative_index_enabled_after_group_stage=content.get("cumulative_index_enabled_after_group_stage", True),
            football_data_api_key=os.environ.get("FOOTBALL_DATA_API_KEY", ""),
            football_data_base_url=os.environ.get("FOOTBALL_DATA_BASE_URL", settings.get("football_data_base_url", "https://api.football-data.org/v4")),
        )


DEFAULT_BRAND = {
    "name": "The Pitch Agent",
    "parent_brand": "BuildWithAbdallah",
    "footer": (
        "The Pitch Agent by BuildWithAbdallah | Independent analytics | "
        "Not affiliated with FIFA"
    ),
    "logo_path": "",
    "chart_theme": "buildwithabdallah_light",
}


def read_settings(config_path: Path | str | None = None) -> dict[str, Any]:
    """Return the raw parsed ``pitch_agent.yaml`` settings (or ``{}``)."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    return _read_yaml(path)


def load_brand(config_path: Path | str | None = None) -> dict[str, str]:
    """Return branding settings (name, parent_brand, footer, logo_path).

    Falls back to sensible defaults when the ``brand`` section or individual
    keys are missing.  ``logo_path`` is resolved against the project root and
    only returned when the file actually exists, so callers never have to guard
    against a missing logo.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    settings = _read_yaml(path)
    brand_settings = settings.get("brand", {}) if isinstance(settings, dict) else {}
    if not isinstance(brand_settings, dict):
        brand_settings = {}

    brand = dict(DEFAULT_BRAND)
    for key in DEFAULT_BRAND:
        value = brand_settings.get(key)
        if value:
            brand[key] = str(value)

    logo_path = brand.get("logo_path", "")
    if logo_path:
        resolved = Path(logo_path)
        if not resolved.is_absolute():
            resolved = ROOT / logo_path
        brand["logo_path"] = str(resolved) if resolved.is_file() else ""
    return brand


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}
