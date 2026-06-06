"""Configuration: secrets loading, agent settings, and brand profiles.

No hard dependency on python-dotenv — we ship a tiny, dependable .env
parser so buyers can run the agent with the standard library + requests
+ PyYAML only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Project root = parent of the `agent/` package directory.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROFILES_DIR = CONFIG_DIR / "profiles"
OPENCLAW_SECRETS_PATH = Path(os.path.expanduser("~/.config/openclaw/secrets.env"))

# Where secrets live, in priority order. The first existing file wins for
# loading, but all are loaded (later files do not override earlier keys).
SECRETS_CANDIDATES = [
    CONFIG_DIR / "secrets.env",
    Path(os.path.expanduser("~/.config/social-media-kit/secrets.env")),
    OPENCLAW_SECRETS_PATH,
]


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
        # Real environment variables take precedence over file values.
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
class AgentConfig:
    """Resolved runtime settings for the orchestrator + LLM client."""

    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.4
    max_steps: int = 20
    dry_run: bool = False
    auto_confirm: bool = False

    # Sensible per-provider defaults if agent.yaml omits a model.
    DEFAULT_MODELS = {
        "anthropic": "claude-sonnet-4-6",
        "openai": "gpt-4o",
        "ollama": "llama3.1",
    }

    @classmethod
    def load(
        cls,
        provider: str | None = None,
        model: str | None = None,
        dry_run: bool = False,
        max_steps: int | None = None,
        auto_confirm: bool = False,
    ) -> "AgentConfig":
        """Build config from agent.yaml + environment + CLI overrides."""
        load_env()
        settings = _read_yaml(CONFIG_DIR / "agent.yaml")

        prov = (
            provider
            or os.environ.get("AGENT_PROVIDER")
            or settings.get("provider")
            or "anthropic"
        ).lower()

        prov_settings = settings.get(prov, {}) if isinstance(settings, dict) else {}

        chosen_model = (
            model
            or os.environ.get(f"{prov.upper()}_MODEL")
            or prov_settings.get("model")
            or cls.DEFAULT_MODELS.get(prov, "")
        )

        api_key = _provider_api_key(prov, prov_settings)
        # Only consult the env base URL for the *active* provider, so an
        # OPENAI_BASE_URL can't silently redirect an Anthropic/Ollama run.
        env_base_urls = {
            "anthropic": os.environ.get("ANTHROPIC_BASE_URL"),
            "openai": os.environ.get("OPENAI_BASE_URL"),
            "ollama": os.environ.get("OLLAMA_BASE_URL"),
        }
        base_url = prov_settings.get("base_url") or env_base_urls.get(prov)

        return cls(
            provider=prov,
            model=chosen_model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=int(prov_settings.get("max_tokens", settings.get("max_tokens", 4096))),
            temperature=float(prov_settings.get("temperature", settings.get("temperature", 0.4))),
            max_steps=int(max_steps if max_steps is not None else settings.get("max_steps", 20)),
            dry_run=dry_run or bool(settings.get("dry_run", False)),
            auto_confirm=auto_confirm,
        )


def _provider_api_key(provider: str, prov_settings: dict) -> str:
    """Resolve the API key for a provider from env (preferred) or yaml."""
    env_names = {
        "anthropic": ["BWA_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
        "openai": ["OPENAI_API_KEY", "OPENROUTER_API_KEY"],
        "ollama": ["OLLAMA_API_KEY"],  # optional; Ollama needs none
    }.get(provider, [])
    for name in env_names:
        if os.environ.get(name):
            return os.environ[name]
    # Allow an api_key in agent.yaml as a fallback (discouraged but handy).
    return str(prov_settings.get("api_key", ""))


# ── Brand profiles ──────────────────────────────────────────────────────
def load_profile(name: str = "default") -> dict[str, Any]:
    """Load a brand profile YAML (tone, audience, platforms, branding…)."""
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        available = list_profiles()
        hint = f" Available: {', '.join(available)}." if available else ""
        raise FileNotFoundError(
            f"Profile '{name}' not found at {path}.{hint} "
            "Create one with `smkit wizard`."
        )
    data = _read_yaml(path)
    data.setdefault("name", name)
    return data


def list_profiles() -> list[str]:
    if not PROFILES_DIR.exists():
        return []
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}
