# Selling on Gumroad — launch kit

Everything you need to package and list the Social Media Agent.

## 1. Build the downloadable

```bash
bash scripts/make_release.sh
# → dist/social-media-agent-<version>.zip
```

The script strips `.git`, secrets, caches, generated content, and
`node_modules`, and **aborts if a `secrets.env` would leak**. Upload that zip
as the Gumroad product file.

## 2. Product name & tagline

**Name:** Social Media Agent — Autonomous AI Content Publisher

**Tagline:** *Point it at a topic. It researches, writes, and publishes across
every channel — on Claude, OpenAI, or your own local model.*

## 3. Product description (paste & trim)

> **Stop scheduling. Start shipping.**
>
> Social Media Agent is an autonomous AI agent — not another scheduler. Give it
> a topic and it runs the full routine an expert marketer would: searches the
> web, reads real sources, writes a genuine article in your brand voice, adapts
> a native post for each platform, and publishes everywhere. From one command.
>
> **Bring your own brain.** Runs on Claude (`claude-opus-4-8`/`sonnet-4-6`),
> any OpenAI-compatible API (OpenAI, OpenRouter…), or a **fully local model via
> Ollama — no API key, no cloud, $0 per run.**
>
> **Publishes anywhere.** Blog (Laravel/WordPress/Ghost), X, LinkedIn,
> Facebook, Slack, Discord, Telegram, Mastodon, and a generic webhook for *any*
> other platform (Zapier, Make, n8n, Buffer…).
>
> **Built for agencies.** Brand profiles let you run unlimited clients, each
> with its own voice and channel allowlist. A topic queue + GitHub Action
> publishes on a schedule without you lifting a finger.
>
> **Plugs into your stack.** Ships as an OpenClaw / Claude Code skill, plus a
> Python adapter for any agent framework.
>
> **You own everything** — your keys, your data, plain auditable HTTP. No SaaS,
> no per-post fees, no middleman.
>
> **What's included:** the full agent + CLI, 9 publishing channels, 4 search
> backends (incl. free no-key options), brand profiles, scheduling, setup
> wizard, OpenClaw/Claude-Code skill, and complete docs. MIT-licensed source —
> use it, modify it, run it for clients.

## 4. "What's included" bullet list (for the sidebar)

- 🧠 Provider-agnostic agent (Claude / OpenAI / local Ollama)
- 📢 9 channels + generic webhook for anything else
- 🔍 4 search providers (Brave, self-hosted SearXNG, DuckDuckGo, Wikipedia)
- 🎭 Multi-brand profiles (agency-ready)
- 🧪 Dry-run mode (rehearse before publishing)
- ⏰ Scheduling (topic queue + GitHub Action)
- 🪄 Setup wizard + `doctor` diagnostics
- 🔌 OpenClaw / Claude Code skill + Python adapter
- 📚 Full docs + commercial license

## 5. Requirements (list these on the page)

- Python 3.10+
- An LLM: a Claude/OpenAI key **or** local Ollama (free)
- Optional: Node.js (for HTML→PNG cards), Docker (for self-hosted SearXNG)

## 6. Screenshots / GIF to capture

Record a terminal (e.g. with `asciinema` or a screen recorder) running:

```bash
smkit doctor
smkit run --topic "Laravel 13 new features" --dry-run --verbose
```

Capture these frames:
1. `smkit doctor` — the green channel checklist.
2. The agent's tool calls scrolling (🔧 web_search → 📝 save_article → 📢 …).
3. The final dry-run summary with the per-platform posts.
4. The generated article open in an editor.

A 20-30s GIF of the dry-run loop is your single best converting asset.

## 7. Pricing (suggested)

| Tier | Price | Positioning |
|------|-------|-------------|
| Solo | $39-49 | Indie devs / creators, single brand |
| Pro | $79-99 | Agencies — emphasize multi-brand profiles + scheduling |
| Founder's launch | -30% | First 100 sales to seed reviews |

One-time purchase, free updates. (Buyers pay their own model/API costs — state
this clearly; it's a selling point for the Ollama/local path.)

## 8. License / EULA hookup

Attach the EULA snippet from
[`docs/COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md) in Gumroad's product
"License" field. The code is MIT (resale-friendly); the EULA sets buyer terms.

## 8b. Positioning (don't compete with free schedulers)

Free self-hosted tools (Postiz, Mixpost) already own "social media dashboard."
**Do not sell this as another scheduler** — you'll lose on UI and price. Sell
the wedge they don't have:

> **The autonomous content agent for developers & AI agents.** It researches,
> writes, illustrates, and publishes on *your* infrastructure and *your* LLM
> (Claude, OpenAI, or free local Ollama) — and plugs into OpenClaw / Claude Code
> as a skill. Not a dashboard you babysit; an agent that ships content for you.

Target buyers: indie devs, AI-agent builders, and small agencies who want a
self-hosted, scriptable, multi-brand pipeline — not marketers who want a GUI.

**Your wedge vs free schedulers (lead with these):**
- **Repurpose Studio** — drop in a blog post / YouTube transcript / PDF and get
  native posts for every channel in your voice. Schedulers make you write first;
  this *writes for you*. This is the headline demo.
- **Runs on your own LLM** — Claude, OpenAI, or **free local Ollama ($0/run)**.
- **Web dashboard *and* CLI/skill** — a GUI for the casual path, automation for
  the power user. You're not CLI-only anymore.

## 9. Trust builders (buyers of code expect these)

Reports on selling code on Gumroad are consistent — at $39–79 buyers expect:

- **A demo.** Record a 20–30s terminal cast (asciinema or a screen recorder) of
  `smkit doctor` → `smkit run --topic "..." --dry-run --verbose`. Embed the GIF.
- **Real docs + Quick Start.** ✅ Already shipped (README + `docs/`).
- **Tests + CI.** ✅ `tests/` + `.github/workflows/ci.yml` — mention "CI-tested"
  on the page; it converts.
- **A support channel.** Create a Discord (or a support email) and link it in
  the README and the product page. Buyers helping each other lowers your load.
- **A refund policy.** A **14-day, no-questions money-back guarantee** measurably
  lifts conversion on digital products and costs little (downloads are low-churn).

## 9b. Pre-launch checklist

- [ ] `bash scripts/make_release.sh` runs clean; archive has **no** secrets.
- [ ] Fresh-machine test: unzip → `pip install -r requirements.txt && pip install -e .` → `smkit wizard` → `smkit run --dry-run`.
- [ ] README's Quick Start works verbatim.
- [ ] Dry-run GIF + 3 screenshots uploaded.
- [ ] EULA attached; price + tiers set.
- [ ] Support contact / link in the README and product page.
