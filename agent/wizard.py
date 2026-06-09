"""Interactive first-run setup wizard.

Writes three files:
  * config/agent.yaml         — provider + model defaults
  * config/secrets.env        — API keys (gitignored)
  * config/profiles/<name>.yaml — a brand profile

Designed to fail gracefully in non-interactive shells (e.g. CI): if input
isn't available it prints guidance and exits without clobbering anything.
"""
from __future__ import annotations

import getpass
import re
import sys

import yaml

from .config import CONFIG_DIR, PROFILES_DIR, SECRETS_CANDIDATES

PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "ollama": None,  # no key needed
}
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "nvidia": "openai/gpt-oss-120b",
    "ollama": "llama3.1",
}
ALL_CHANNELS = [
    "blog", "facebook", "x", "linkedin", "slack", "discord", "telegram",
    "mastodon", "bluesky", "threads", "reddit", "pinterest", "webhook",
]


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return val or default


def run_wizard() -> int:
    print("=" * 60)
    print("📡 Social Media Agent — Setup Wizard")
    print("=" * 60)
    if not sys.stdin.isatty():
        print(
            "Non-interactive shell detected. Copy config/secrets.env.example "
            "to config/secrets.env and edit config/profiles/default.yaml by hand."
        )
        return 0

    # ── Provider ────────────────────────────────────────────────────────
    print("\n1) Which LLM provider should drive the agent?")
    print("   [1] anthropic (Claude)   [2] openai / openrouter   [3] nvidia NIM   [4] ollama")
    choice = _ask("Choose 1/2/3/4", "1")
    provider = {
        "1": "anthropic",
        "2": "openai",
        "3": "nvidia",
        "4": "ollama",
    }.get(choice, "anthropic")
    model = _ask("Model id", DEFAULT_MODELS[provider])

    agent_yaml = {"provider": provider, "max_steps": 20, "dry_run": False,
                  provider: {"model": model}}
    if provider == "ollama":
        base = _ask("Ollama base URL", "http://localhost:11434/v1")
        agent_yaml[provider]["base_url"] = base
    elif provider == "openai":
        base = _ask("API base URL (blank = OpenAI)", "https://api.openai.com/v1")
        agent_yaml[provider]["base_url"] = base
    elif provider == "nvidia":
        base = _ask("NVIDIA NIM base URL", "https://integrate.api.nvidia.com/v1")
        agent_yaml[provider]["base_url"] = base

    # ── Secrets ─────────────────────────────────────────────────────────
    secrets: dict[str, str] = {}
    key_name = PROVIDER_KEYS[provider]
    if key_name:
        try:
            api_key = getpass.getpass(f"\n2) Paste your {key_name} (hidden): ").strip()
        except EOFError:
            api_key = ""
        if api_key:
            secrets[key_name] = api_key

    # ── Brand profile ───────────────────────────────────────────────────
    print("\n3) Brand profile")
    pname = _ask("Profile name", "default")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pname):
        print("❌ Profile names may only contain letters, numbers, '-' and '_'.")
        return 1
    brand = _ask("Brand / author name", "My Brand")
    tone = _ask("Voice / tone", "clear, practical, and friendly")
    audience = _ask("Target audience", "developers and tech builders")
    link = _ask("Canonical link to promote (optional)", "")
    hashtags = _ask("Default hashtags (space-separated, optional)", "")

    print("\n   Enabled channels (comma-separated). Options:")
    print("   " + ", ".join(ALL_CHANNELS))
    chans = _ask("Channels", "blog, x, linkedin")
    platforms = [c.strip() for c in chans.split(",") if c.strip() in ALL_CHANNELS]

    profile = {
        "name": brand,
        "tone": tone,
        "audience": audience,
        "language": "English",
        "link": link,
        "cta": "",
        "hashtags": hashtags.split() if hashtags else [],
        "platforms": platforms or ["blog", "x", "linkedin"],
        "branding": {"bg_color": "#0f172a", "accent_color": "#2563eb"},
        "blog": {"category_id": None, "tags": []},
    }

    # ── Write files ─────────────────────────────────────────────────────
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    (CONFIG_DIR / "agent.yaml").write_text(
        yaml.safe_dump(agent_yaml, sort_keys=False), encoding="utf-8"
    )
    prof_path = PROFILES_DIR / f"{pname}.yaml"
    prof_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    secrets_path = SECRETS_CANDIDATES[0]  # config/secrets.env
    existing = ""
    if secrets_path.exists():
        existing = secrets_path.read_text(encoding="utf-8")
    with secrets_path.open("a", encoding="utf-8") as f:
        if not existing:
            f.write("# Social Media Agent secrets — NEVER commit this file\n")
        for k, v in secrets.items():
            if f"{k}=" not in existing:
                f.write(f"{k}={v}\n")

    print("\n✅ Setup complete!")
    print(f"   • config/agent.yaml         (provider: {provider} / {model})")
    print(f"   • {prof_path.relative_to(CONFIG_DIR.parent)}")
    print(f"   • config/secrets.env        (add channel keys here)")
    print("\nNext steps:")
    print("   smkit doctor")
    print(f'   smkit run --topic "your first topic" --profile {pname} --dry-run')
    return 0
