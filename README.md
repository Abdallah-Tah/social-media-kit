# 📡 Social Media Agent

**An autonomous AI agent that researches a topic, writes a high-quality article, and publishes it — plus native posts — across every channel you use. From one command.**

Point it at a topic. It searches the web, reads sources, writes a real article in your brand voice, adapts a native post for each platform, and publishes everywhere. Runs on **Claude, OpenAI, or a local model (Ollama)** — your choice, your keys. Plugs into **[OpenClaw](https://github.com/openclaw/openclaw)** and Claude Code as a drop-in skill.

```bash
smkit run --topic "Laravel 13 new features" --dry-run     # rehearse safely
smkit run --topic "Laravel 13 new features" --yes         # go live
```

---

## Why this is different

Most "social media tools" are dumb schedulers — *you* still write everything. This is an **agent**: it runs the full routine the way an expert content marketer would, and decides what to do at each step.

```
        ┌─────────────────────────────────────────────────────┐
        │                  THE ROUTINE (per run)               │
        │                                                      │
  topic →  🔍 research  →  📝 write  →  🎯 adapt  →  📢 publish  → ✅ report
        │   web search     full          per-platform   blog +     summary of
        │   + extract      article       native posts   socials    what shipped
        └─────────────────────────────────────────────────────┘
```

- 🧠 **Provider-agnostic brain** — Claude (`claude-opus-4-8` / `claude-sonnet-4-6`), any OpenAI-compatible API (OpenAI, OpenRouter, …), or **local Ollama** with no API key.
- 🌐 **Publishes anywhere** — Blog (Laravel/WordPress/Ghost), X, LinkedIn, Facebook, Slack, Discord, Telegram, Mastodon, Bluesky, Threads, **Reddit, Pinterest**, and a **generic webhook** for *any* other platform (Zapier, Make, n8n, Buffer…). Images attach on X, LinkedIn, Facebook, Mastodon & Bluesky.
- 🖼️ **Auto cover images** — generates a hero image per article via **FAL.ai** (flux-pro) or **OpenAI Images**, with a free branded-card fallback, and attaches it on publish.
- 🎭 **Brand profiles** — run it for multiple brands/clients, each with its own voice, audience, hashtags, and allowed channels.
- 🧬 **Brand DNA** — `smkit learn <your-site>` reads your site and auto-writes a profile in your voice. No manual setup.
- ♻️ **Repurpose Studio** — `smkit repurpose <url|file>` turns one existing article, transcript, or note into native posts for every channel in your voice. *Create once, distribute everywhere* — the thing schedulers can't do.
- 🖥️ **Web dashboard** — `smkit dashboard` opens a browser control panel (trigger runs, repurpose, preview drafts, browse history). Zero extra dependencies.
- 📜 **Track record + dedupe** — every run is logged; the agent won't re-publish a topic you've already shipped.
- 🧪 **Dry-run first** — rehearse a complete run with zero side effects, see exactly what *would* post, then go live.
- ⏰ **Scheduled & autonomous** — a topic queue + GitHub Action publishes on a cron without you lifting a finger.
- 🔌 **OpenClaw / Claude Code skill** — ships as a `SKILL.md` so your existing agent can call it, plus a Python adapter for custom runtimes.
- 🔒 **You own everything** — your keys, your data, plain HTTP calls. No SaaS, no middleman, no per-post fees.

---

## Requirements

You need **one working LLM** — the agent uses it to research and write. Pick any:

- A **Claude** (`BWA_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY`) or **OpenAI** (`OPENAI_API_KEY`) key, **or**
- **Ollama Cloud** — set `OLLAMA_BASE_URL` + `OLLAMA_API_KEY` and use a `:cloud` model, **or**
- **Local Ollama** — free/offline, but the model needs enough RAM (an 8B model wants ~8 GB; small boxes/Raspberry Pi should use Ollama Cloud or a tiny model).

> **Note:** `--dry-run` skips *publishing* (no posts go live), **not** *generation* —
> it still calls your LLM to write the content. So a fake/empty key returns a 401.
> Use a real key, Ollama Cloud, or a local model that fits in memory.

## Quick Start

```bash
# 1. Install (a virtualenv avoids PEP 668 "externally-managed" errors)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .            # gives you the `smkit` command
npm install                 # optional: HTML→PNG social cards

# 2. Configure (interactive)
smkit wizard                # pick provider, paste a key, set your brand voice

# 3. Check everything
smkit doctor                # shows which providers + channels are ready

# 4. Run — rehearse, then ship
smkit run --topic "Your topic" --dry-run
smkit run --topic "Your topic" --yes
```

**No API key? Use Ollama Cloud** (cheap, no local RAM needed):

```bash
export OLLAMA_BASE_URL=https://ollama.com/v1
export OLLAMA_API_KEY=your_ollama_cloud_key
smkit run --topic "Your topic" --provider ollama --model deepseek-v4-flash:cloud --dry-run
```

No `smkit` command? Use `python -m agent ...` — identical.

---

## Usage

```bash
# Learn your brand voice from your site (writes config/profiles/default.yaml)
smkit learn https://yoursite.com

# Research + write + publish to the channels in your profile
smkit run --topic "Python asyncio in production"

# Free-form goal instead of a topic
smkit run --goal "Compare Postgres vs SQLite for small apps; post to X and LinkedIn"

# Use a specific brand profile
smkit run --topic "..." --profile client-acme

# Run on a local Ollama model (free; needs enough RAM for the model)
smkit run --topic "..." --provider ollama --model llama3.1 --dry-run

# Pull the next topic from the queue (for scheduled jobs)
smkit queue config/topics.txt --yes
```

| Command | What it does |
|---------|--------------|
| `smkit run` | Run the full routine on a `--topic` or `--goal` |
| `smkit repurpose <url\|file>` | Turn one existing piece into native posts for every channel |
| `smkit dashboard` | Launch the local web control panel (no CLI needed) |
| `smkit learn <url>` | Build a brand profile by reading your website |
| `smkit queue <file>` | Run the next topic from a queue file (scheduling) |
| `smkit history` | List previously published runs (with dedupe) |
| `smkit wizard` | Interactive setup (provider, keys, brand profile) |
| `smkit doctor` | Report configured providers and channel credentials |
| `smkit profiles` | List your brand profiles |
| `smkit install-skill` | Register as a permanent OpenClaw / Claude Code skill |

Key flags: `--dry-run` (simulate), `--yes` (skip live confirmation), `--provider`, `--model`, `--profile`, `--max-steps`, `--verbose`.

---

## Choose your brain

Set it in `config/agent.yaml` or per-run with `--provider`.

| Provider | Best for | Key |
|----------|----------|-----|
| `anthropic` | Highest-quality writing | `BWA_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY` |
| `openai` | OpenAI / OpenRouter / compatible | `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`) |
| `ollama` (local) | Free & offline; needs RAM for the model | none — runs at `localhost:11434` |
| `ollama` (cloud) | No local RAM; cheap hosted models | `OLLAMA_API_KEY` + `OLLAMA_BASE_URL=https://ollama.com/v1`, use a `:cloud` model |

The LLM layer talks plain HTTP — **no SDK required** for any provider.

---

## Brand profiles

A profile (`config/profiles/<name>.yaml`) defines the voice and the rules:

```yaml
name: My Brand
tone: clear, practical, and friendly
audience: developers and founders
hashtags: ["#dev", "#AI"]
platforms: [blog, x, linkedin, slack]   # the ONLY channels it may post to
branding: { bg_color: "#0f172a", accent_color: "#2563eb" }
blog: { category_id: 3, tags: [2, 5] }
```

Duplicate it per client and pass `--profile client-name`.

---

## Use it from OpenClaw or Claude Code

This kit ships as a skill at `skills/social-media-agent/SKILL.md` (the same
skill format OpenClaw and Claude Code use). Drop the repo under your agent's
skills root and it's discovered automatically. There's also a Python adapter
(`agent/openclaw_skill.py`) to register the tools programmatically. See
**[docs/OPENCLAW.md](docs/OPENCLAW.md)**.

---

## Documentation

- **[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)** — how the agent works, providers, profiles, scheduling, dry-run
- **[docs/OPENCLAW.md](docs/OPENCLAW.md)** — OpenClaw / Claude Code skill integration
- **[docs/SEARCH.md](docs/SEARCH.md)** — search providers + free self-hosted SearXNG setup
- **[docs/PLATFORM_SETUP.md](docs/PLATFORM_SETUP.md)** — getting API keys for every channel
- **[docs/API_REFERENCE.md](docs/API_REFERENCE.md)** — every script and flag
- **[docs/GUMROAD.md](docs/GUMROAD.md)** — packaging & launch kit for selling

---

## Security

- `config/secrets.env` is **gitignored** — your keys never leave your machine.
- Tokens are read from env vars / the local secrets file only.
- Every external call is a plain, auditable HTTP request you can read in `scripts/`.

## ⚽ The Pitch Agent

Independent World Cup analytics — Form Index scoring, position leaderboards, and content generation.

**The Pitch Agent is an independent analytics project and is not affiliated with FIFA, FIFA World Cup, or any official tournament organizer.**

### Form Index v1.0 Lite (frozen)

The scoring model is frozen as **Form Index v1.0 Lite**:

> Form Index v1.0 Lite is a simple 0–100 player performance score based on goals, assists, minutes, cards, clean sheet impact, and team result.

This version is deliberately frozen so scores stay comparable day to day. The label `Form Index v1.0 Lite` appears in every score breakdown, leaderboard/content metadata, chart subtitle, and the public methodology (`python -m pitch_agent.cli transparency`). Richer stats are reserved for a future **Form Index v2.0** once a live data source is connected.

See [Content pillars](#content-pillars) below for the launch-ready pillars. It can generate educational match predictions and data-based estimates for content and analytics purposes. It does not provide betting advice, odds, gambling picks, or certainty claims, and prediction posts must include clear disclaimers.

```bash
python -m pitch_agent.cli init-db
python -m pitch_agent.cli sync-data --provider csv
python -m pitch_agent.cli compute-index --all
python -m pitch_agent.cli leaderboard --scope daily --limit 10
python -m pitch_agent.cli leaderboard --scope player-match --limit 10
python -m pitch_agent.cli leaderboard --scope tournament --limit 10
python -m pitch_agent.cli leaderboard --scope daily --position DEF --limit 10
python -m pitch_agent.cli render-chart --type leaderboard --scope daily
python -m pitch_agent.cli render-chart --type position_leaderboard --position DEF
python -m pitch_agent.cli generate-content --pillar form_index_update --mode fan_mode --dry-run
python -m pitch_agent.cli generate-content --pillar form_index_update --mode fan_mode --dry-run --send-telegram-review
python -m pitch_agent.cli generate-content --pillar form_index_update --mode fan_mode --dry-run --send-telegram-review --strict-telegram
python -m pitch_agent.cli generate-content --pillar position_leaderboard --mode fan_mode --dry-run
python -m pitch_agent.cli generate-content --pillar builder_update --mode builder_mode --dry-run
python -m pitch_agent.cli transparency
python -m pitch_agent.cli test-anthropic
```

### Two World Cup phases

The Pitch Agent works in two phases depending on whether matches have been played.

**Phase 1 — Pre-tournament / before kickoff.** Use real fixtures from football-data.org. There are **no Form Index grades yet because matches have not been played** — so the agent generates matchday previews and fixture charts instead.

```bash
python -m pitch_agent.cli sync-data --provider football-data --competition WC
python -m pitch_agent.cli fixtures --competition WC --limit 10
python -m pitch_agent.cli render-chart --type fixtures --limit 10
python -m pitch_agent.cli generate-content --pillar matchday_preview --mode fan_mode --dry-run
python -m pitch_agent.cli generate-content --pillar matchday_preview --mode fan_mode --dry-run --send-telegram-review
```

- Use football-data.org fixtures
- Generate matchday previews
- Generate fixture charts
- No Form Index grades yet because matches have not been played

**Phase 2 — After matches are played.** Re-sync to pull results, then compute and publish Form Index content.

```bash
python -m pitch_agent.cli sync-data --provider football-data --competition WC --max-matches 10
python -m pitch_agent.cli compute-index --all
python -m pitch_agent.cli leaderboard --scope daily --limit 10
python -m pitch_agent.cli render-chart --type leaderboard --scope daily
python -m pitch_agent.cli generate-content --pillar form_index_update --mode fan_mode --dry-run
python -m pitch_agent.cli generate-content --pillar post_match_grades --mode fan_mode --dry-run
```

- Sync results
- Compute Form Index v1.0 Lite
- Generate daily leaderboard
- Generate position leaderboards
- Generate post-match grades

`sync-data` against a per-match provider only fetches stats for **finished** matches (most recent first), capped by `--max-matches` (default 10) to protect free-tier API rate limits. Before kickoff this is a no-op: fixtures sync, results pending.

### Content pillars

The four launch-ready, result-based pillars are `form_index_update`, `position_leaderboard`, `player_spotlight`, and `post_match_grades` (see above). Two pillars support the pre-tournament phase:

- **`matchday_preview`** (`fan_mode`) — a short, estimate-free preview of the next few fixtures with group/stage context and a call to follow for Form Index updates once matches are played.
- **`real_data_connected`** (`builder_mode`) — a structured update confirming real World Cup fixtures are connected and the agent is ready to grade results once they exist.

### Provider metadata

Telegram review and content metadata label the data source so a reviewer always knows what they are looking at.

**football-data** (real fixtures, pre-tournament):

- provider: `football-data`
- quality: `fixture-only` before matches (becomes `basic` once results are graded)
- status: `real fixtures, no player grades yet`
- No "Demo data only" warning — this is real fixture data.

**csv** (offline demo data):

- provider: `csv`
- quality: `basic`
- warning: **Demo data only — not live tournament data.** (shown in Telegram review, never in the public post)

### Halal / content guardrails

The Pitch Agent is an educational AI/data project for performance analytics, content generation, reusable charts, automation, and portfolio demonstration. It can generate educational match predictions and data-based estimates, but it does **not** provide betting advice, odds, gambling picks, certainty claims, or guaranteed outcomes. Predictions must be framed as model outputs from public data for learning and experimentation, not guarantees. The project is **not affiliated with FIFA**, the FIFA World Cup, or any official tournament organizer. These rules are enforced for fan-mode output and reflected in the public methodology page.

### Data Providers

| Provider              |       Cost | Best for                                 | Live score           | Player stats depth | Works offline | Notes                                          |
| --------------------- | ---------: | ---------------------------------------- | -------------------- | ------------------ | ------------- | ---------------------------------------------- |
| CSV                   |       Free | Local demo/dev                           | No                   | Basic/manual       | Yes           | Guaranteed demo path                           |
| football-data.org     | Free/basic | Fixtures, scores, scorers, cards, squads | Limited/basic        | Basic              | No            | Good launch fallback, not rich analytics       |
| API-Football          |  Free/paid | Live match data and richer stats         | Yes                  | Better on paid     | No            | Treat as upgrade path                          |
| BALLDONTLIE World Cup | Test first | Optional World Cup-specific enrichment   | Unknown until tested | Potentially rich   | No            | Do not depend on it until endpoint is verified  |

### `player_match_stats` Field Coverage by Provider

| Field                | CSV | football-data.org | API-Football |
| -------------------- | :-: | :---------------: | :----------: |
| goals                | ✅  | ✅                | ✅           |
| assists              | ✅  | ✅                | ✅           |
| minutes              | ✅  | ✅                | ✅           |
| yellow_cards         | ✅  | ⚠️ limited        | ✅           |
| red_cards            | ✅  | ⚠️ limited        | ✅           |
| own_goals            | ✅  | —                 | ✅           |
| clean_sheet          | ✅  | —                 | ✅           |
| team_result          | ✅  | ✅                | ✅           |
| pass_accuracy        | ✅  | —                 | ✅           |
| shots_on_target      | ✅  | —                 | ✅           |
| key_passes           | ✅  | —                 | ✅           |
| shots_faced          | ✅  | —                 | ✅           |
| saves                | ✅  | —                 | ✅           |
| *all rich fields*    | ✅  | — (default 0)     | ✅           |

### Group-Stage Content Rule

During the group stage, The Pitch Agent prioritizes per-match and daily Form Index leaderboards. The cumulative tournament index becomes more meaningful after multiple matches, especially around the knockout stage. This is controlled by `content.headline_index_mode` in `config/pitch_agent.yaml`.

### Brand chart template (template-driven, not AI-designed)

**Pitch Agent visuals are template-driven, not AI-designed.** An AI may generate the *narrative text* (post copy), but every chart's layout and styling is produced deterministically in code so all visuals share one BuildWithAbdallah brand system — there is no AI "designing" the picture and no random placement.

The reusable template engine is split across three modules:

- `pitch_agent/chart_themes.py` — named theme palettes (`buildwithabdallah_light` default, `dark` legacy) and `load_theme()`.
- `pitch_agent/brand_template.py` — the layout engine: `load_brand_config()`, `draw_background()`, `draw_watermark()`, `draw_header()`, `draw_title_block()`, `draw_footer()`, `draw_accent_shapes()`, `create_canvas()`, `save_chart()`, plus deterministic `figure_size_for()` / `Layout` geometry.
- `pitch_agent/chart_blocks.py` — content renderers: `draw_fixture_rows()`, `draw_leaderboard_rows()`, `draw_position_rows()`, `draw_player_spotlight()`, `draw_stat_card()`.

Every chart type uses this one engine: fixtures, leaderboard, position_leaderboard, player_spotlight, post_match_grades, stat_of_the_day, and team_form_report.

The `buildwithabdallah_light` theme provides:

- light gray / white background (`#F7F9FC`)
- BuildWithAbdallah logo top-left (falls back to a `BuildWithAbdallah` text header if the logo file is missing — never crashes)
- a large, subtle transparent `A` watermark behind the content
- blue decorative dots in the corners and a header divider
- dark-navy titles, muted-grey subtitles, bright-blue accents
- clean ranked-row / fixture-list layouts with small `FWD/MID/DEF/GK` tags (no crowded legend)
- the shared Pitch Agent prediction footer: **BuildWithAbdallah.com | Educational predictions | Not betting advice | Not affiliated with FIFA**

Layout is deterministic: fixed margins, a fixed-height title block, a fixed footer position, fixed row spacing, fixed font sizing, and safe text wrapping/truncation — the same inputs always produce the same image dimensions. Charts are written to `artifacts/pitch_agent/charts/`. No FIFA logo, no World Cup logo, no trophy mark — original charts, flags, and team colors only.

Configuration lives in `config/pitch_agent.yaml`: identity under `brand:` (`name`, `parent_brand`, `logo_path`, `footer`, `chart_theme`) and palette under `theme:` (`background_color`, `primary_text`, `secondary_text`, `accent_blue`, `divider_color`, `watermark_text`, `watermark_alpha`). Default `chart_theme` is `buildwithabdallah_light`; set it to `dark` for the legacy palette.

Pitch Agent loads secrets from `config/secrets.env`, `~/.config/social-media-kit/secrets.env`, and `~/.config/openclaw/secrets.env`.

## License

See **[LICENSE](LICENSE)** (MIT) and **[docs/COMMERCIAL_LICENSE.md](docs/COMMERCIAL_LICENSE.md)** for terms when reselling or bundling.

---

Built by [Abdallah Mohamed](https://github.com/Abdallah-Tah).
