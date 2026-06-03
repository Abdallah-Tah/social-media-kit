# Changelog

## 2.4.1 — Honest docs + dashboard polish (pre-market QA fixes)

From an external validation pass:
- **Docs corrected**: `--dry-run` skips *publishing*, not *generation* — it
  still needs a working LLM, so a fake/empty key returns 401. README and the
  Gumroad kit now say this plainly and list the LLM requirement up front.
- **Install**: recommend a **virtualenv** (`python -m venv`) to avoid PEP 668
  "externally-managed" errors on modern Python.
- **Ollama Cloud quickstart** documented (no local RAM needed) in README,
  provider table, and the Gumroad requirements.
- **Dashboard**: a busy port now prints a friendly "already in use → try
  --port 8801" message instead of a traceback.

## 2.4.0 — Web dashboard, Repurpose Studio, Reddit + Pinterest

### Added
- **Web dashboard** (`smkit dashboard`) — a local browser control panel built on
  Python's stdlib (zero new dependencies): trigger runs, repurpose a URL,
  preview drafts, and browse history. Binds to localhost.
- **Repurpose Studio** (`smkit repurpose <url|file>`) — turn one existing
  article/transcript/note into platform-native posts for every channel in your
  voice, without fresh research. The "create once, distribute everywhere"
  workflow schedulers don't offer.
- **Reddit** (script-app OAuth, self posts) and **Pinterest** (API v5 Pins)
  publishers, wired into the agent, doctor, wizard, and secrets template.

### Notes
- Test suite now 40 cases (incl. a live dashboard HTTP test), all green.
- Dockerfile exposes 8800 for the dashboard.

## 2.3.0 — Brand DNA, dedupe, native blogs, pro polish

### Added
- **`smkit learn <url>`** — reads your website and writes a brand profile in
  your voice (the "ingest my site to learn my brand" capability buyers want).
- **Published-posts log + dedupe** — every real run is recorded to
  `content/published.json`; the agent won't re-publish a topic you've already
  shipped (override with `--force`). View with **`smkit history`**.
- **Native WordPress + Ghost adapters** for the blog publisher (set
  `BLOG_PLATFORM`); Ghost JWT is generated with no extra dependency. The
  generic Laravel/custom adapter is unchanged.
- **Docker**: a `Dockerfile` + `.dockerignore` to run the whole agent in a
  container.
- **CONTRIBUTING.md**, **SECURITY.md**, and a **demo recipe** (`scripts/demo.sh`)
  for recording the Gumroad GIF.
- More tests (brand-learn JSON extraction, history dedupe, Ghost JWT, blog
  platform dispatch).

## 2.2.0 — More platforms, images everywhere, tests + CI

### Added
- **Bluesky** (AT Protocol, app password) and **Threads** (Meta API) publishers
  — both wired into the agent with character-limit enforcement. Closes the
  biggest 2026 platform gap.
- **Image attachment across channels**: X, LinkedIn, Mastodon, and Bluesky now
  upload the generated cover (Facebook already did). Threads uses the cover
  URL. The routine attaches covers automatically.
- **Test suite + CI**: a `pytest` suite (`tests/`) covering the agent loop,
  provider abstraction, security guards (allowlist, draft-path sandbox,
  base_url scoping), search parsers, and the doctor heuristic — run by a GitHub
  Actions workflow (`.github/workflows/ci.yml`) on Python 3.10–3.12.

### Changed
- `doctor`, the wizard, and `secrets.env.example` now list Bluesky + Threads.
- Gumroad kit: positioning guidance (don't compete with free schedulers) plus
  a trust-builders section (demo, support channel, 14-day refund).

## 2.1.0 — Cover image generation

### Added
- **Cover images**: a `generate_cover` agent tool + `scripts/image_generator.py`
  that creates a hero image per article. Provider chain: **FAL.ai (flux-pro) →
  OpenAI Images → a free branded Pillow card** (no key required for the
  fallback). Force one with `IMAGE_PROVIDER`.
- The routine now generates a cover and **attaches it on publish** — the hosted
  URL goes to `publish_blog` (`cover_image_url` → `cover_image`/`featured_image`)
  and the local path to `post_facebook` (posts as a photo).
- **`smkit doctor` secret-health check**: warns when a credential looks
  truncated (contains a `…` ellipsis, ends in `...`, or is implausibly short) —
  catches copy-paste truncation like a masked-token paste.

### Changed
- `blog_publisher.publish_article` accepts `cover_image_url`; the Facebook tool
  accepts an optional `image` path.

## 2.0.6 — Re-review fixes (round 2)

- `ToolBox`: register a `finish` handler and allow it through the channel
  allowlist, so a direct `dispatch("finish")` terminates cleanly (the loop
  itself still intercepts `finish` upstream).
- `install_skill`: validate the skills directory before `mkdir` — return a
  clean error instead of an uncaught traceback when the path is a file.

## 2.0.5 — Re-review fixes

- **🔴 Workflow script-injection hardening**: `scheduled-run.yml` now passes
  `workflow_dispatch` inputs through the `env:` block instead of expanding
  `${{ github.event.inputs.* }}` directly in the shell `run:` script.
- **Release guard**: `make_release.sh` deletes the archive if the secrets
  leak-check ever trips, so a compromised zip can't be uploaded by mistake.
- **Skill manifest**: installer uses `python3 -m pip` (bound to the declared
  runtime), and the `metadata` block is rewritten as plain block YAML.

## 2.0.4 — Review hardening (security + robustness)

Addresses the automated code review on PR #1.

### Security
- **Profile allowlist is now enforced at execution** (`ToolBox.dispatch`), not
  just suggested in the prompt — a misaligned/injected model can no longer post
  to a channel the brand profile didn't enable.
- **`publish_blog` draft_path is sandboxed** to `content/drafts/` — model output
  can no longer make the agent read arbitrary local files.
- **Wizard hides the API key** (`getpass`) and **validates the profile name**
  against path traversal.
- **SearXNG binds to loopback** (`127.0.0.1`) by default instead of all
  interfaces.
- **Release builder packages from `git archive HEAD`**, so untracked local
  secrets can never leak into the Gumroad zip.

### Robustness
- `base_url` is scoped to the active provider (an `OPENAI_BASE_URL` no longer
  bleeds into Anthropic/Ollama runs).
- All channel posters (Slack, Discord, Telegram, Mastodon, webhook) now catch
  `requests.RequestException` instead of crashing.
- Telegram no longer defaults to HTML parse mode (plain text by default), so
  messages with `<`, `>`, `&` don't fail to send.
- Mastodon char-limit env parsing and the webhook `--extra` JSON parsing are
  guarded against bad input.
- Bumped `Pillow>=11.0.0` to avoid known 10.x advisories; removed an unused
  import; workflow only stages the (non-ignored) topic queue and uses clearer
  dry-run logic.

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
