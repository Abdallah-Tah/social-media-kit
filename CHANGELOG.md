# Changelog

## 2.0.0 — The Agent Release

The kit graduates from a set of standalone scripts into a complete, sellable
**orchestrated agent**.

### Added
- **Orchestrated agent** (`agent/`) — a Claude Code-style tool-use loop that
  runs the full routine: research → write → adapt per platform → publish → report.
- **`smkit` CLI** — `run`, `queue`, `wizard`, `doctor`, `profiles`
  (also `python -m agent`).
- **Provider-agnostic LLM layer** — Anthropic (Claude), OpenAI-compatible
  (OpenAI/OpenRouter/…), and **local Ollama** (no API key), all over plain HTTP.
- **New channels** — Slack, Discord, Telegram, Mastodon, and a **generic
  webhook** for any other platform (joining Blog, Facebook, X, LinkedIn).
- **Brand profiles** (`config/profiles/*.yaml`) — per-brand voice, audience,
  hashtags, branding, and a channel allowlist.
- **Dry-run mode** — rehearse a full run with zero side effects; hard limits
  (e.g. 280-char tweets) are still enforced.
- **Scheduling** — topic queue (`config/topics.txt`) + `smkit queue` + a
  GitHub Action (`.github/workflows/scheduled-run.yml`).
- **Setup wizard** — `smkit wizard` writes `agent.yaml`, a brand profile, and
  `secrets.env`.
- **OpenClaw / Claude Code skill** — `skills/social-media-agent/SKILL.md`
  plus a programmatic adapter (`agent/openclaw_skill.py`).
- **Packaging** — `pyproject.toml` with a `smkit` console script.
- **Docs** — Agent Guide, OpenClaw integration, commercial/resale license.

### Changed
- README rewritten around the agent.
- `requirements.txt` trimmed — no SDLK/SDK or `python-dotenv` dependency; a
  tiny built-in `.env` loader ships in `agent/config.py`.
- `secrets.env.example` expanded to cover all providers and channels.

### Notes
- The original standalone scripts still work exactly as before — the agent
  uses them as its tools.
