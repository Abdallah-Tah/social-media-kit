# Changelog

## 2.0.3 — Permanent OpenClaw install

### Added
- **`smkit install-skill`** — one command to register the kit as a permanent,
  auto-discovered OpenClaw / Claude Code skill (auto-detects the skills root,
  symlink or `--copy`, idempotent, `--force` to replace).

### Changed
- The skill is now **provider-agnostic**: it only requires `python3` (dropped
  the hard `ANTHROPIC_API_KEY` gate) so it stays available on Ollama/OpenAI too.

## 2.0.2 — Search self-hosting, safe live profile, Gumroad kit

### Added
- **Self-hosted SearXNG** (`deploy/searxng/`) for free, no-key, high-quality
  web search, with a setup guide (`docs/SEARCH.md`).
- **`live-fb-x` profile** — a channel-locked profile that publishes ONLY to
  Facebook + X, for safe first live runs.
- **Release builder** (`scripts/make_release.sh`) that produces a clean,
  secrets-free `dist/*.zip`, plus a full Gumroad launch kit (`docs/GUMROAD.md`)
  with copy, pricing, and a pre-launch checklist.

## 2.0.1 — Field-test fixes (Ollama + search)

Fixes from real-world testing with an OpenClaw agent.

### Fixed
- **Web search returned no results**: the DuckDuckGo fallback dropped every
  result because DDG wraps target URLs in `duckduckgo.com/l/?uddg=` redirects.
  We now decode those redirects, strip/unescape titles, dedupe, and fall back
  across HTML + lite endpoints.
- **Ollama tool calls ignored**: Ollama returns tool-call `arguments` as a JSON
  *object* (OpenAI sends a string) — the parser now accepts both, and
  synthesizes a tool-call id when one isn't provided.
- **Thinking models looked empty**: responses with an empty `content` but a
  `reasoning` / `reasoning_content` field now surface that text instead of a
  blank turn.

### Added
- **Two free, no-key search providers**: SearXNG (`SEARXNG_URL`) and Wikipedia
  (always-on fallback). Search order is Brave → SearXNG → DuckDuckGo →
  Wikipedia; force one with `SEARCH_PROVIDER`.
- **Ollama Cloud** docs/config: `base_url: https://ollama.com/v1` +
  `OLLAMA_API_KEY`, using base model names (no `:cloud` suffix), with guidance
  to choose tool-calling-capable models.

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
