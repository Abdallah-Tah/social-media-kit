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

## Quick Start

```bash
# 1. Install
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

# Run locally with no API key
smkit run --topic "..." --provider ollama --dry-run

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
| `anthropic` | Highest-quality writing | `ANTHROPIC_API_KEY` |
| `openai` | OpenAI / OpenRouter / compatible | `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`) |
| `ollama` | Fully local & free, offline | none — runs at `localhost:11434` |

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

## License

See **[LICENSE](LICENSE)** (MIT) and **[docs/COMMERCIAL_LICENSE.md](docs/COMMERCIAL_LICENSE.md)** for terms when reselling or bundling.

---

Built by [Abdallah Mohamed](https://github.com/Abdallah-Tah).
