# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**`smkit` — the social-media content agent** (`agent/`): provider-agnostic
(Claude / OpenAI / Ollama) routine that researches a topic → writes an article →
adapts native posts per platform → publishes. Entry: `agent.cli:main`. The README
documents this product.

The public face is the **BuildWithAbdallah** blog + LinkedIn, and the editorial
goal is that both read as *an engineer's*, not a publisher's. Three content lanes
feed it, all sharing one format registry (see below): evergreen tutorials, developer
news, and a weekly GitHub open-source roundup.

A second piece, **Taco** (`agent_journal/`), is a self-improvement loop: it proposes
rule changes that get applied to `config/taco_rules.md` (loaded into the agent
system prompt via `agent/prompts.py`).

> The Pitch Agent / World Cup video pipeline was removed after the tournament
> ended. `remotion/` and `scripts/record_frames.mjs` remain — they still serve the
> dev-content Shorts driven by `agent/shorts.py`.

## Console scripts (from `pyproject.toml`)

- `smkit` → `agent.cli:main` (content agent: `smkit run --topic ... --dry-run|--yes`, `smkit repurpose`, `smkit dashboard`)
- `taco-journal` → `agent_journal.cli:main`

## Common commands

```bash
# Tests (pytest; testpaths=tests, addopts=-q already set)
/usr/bin/python3 -m pytest                          # whole suite
/usr/bin/python3 -m pytest tests/test_content_formats.py -q

# The three publishing lanes — all support a rehearsal before anything goes live
/usr/bin/python3 scripts/auto_publish.py                       # tutorial (cron: Mon/Wed/Fri 09:00)
/usr/bin/python3 scripts/news_publish.py --dry-run             # news (cron: daily 12:00)
/usr/bin/python3 scripts/github_roundup.py --dry-run           # GitHub roundup
/usr/bin/python3 scripts/github_roundup.py --topic ai --publish # LIVE: blog + FB + LinkedIn

# Quality enforcement pass (runs right after a tutorial publish)
/usr/bin/python3 scripts/enforce_published_quality.py --latest

# Render a Remotion composition directly (props.json drives it; --audio optional)
node remotion/render.mjs --id Short --props <props.json> --out out.mp4 [--audio vo.mp3]
```

**Always invoke Python with `/usr/bin/python3`** for these scripts — the modules expect that interpreter (the shell default differs). Node for Remotion/Playwright is `/home/linuxbrew/.linuxbrew/bin/node`.

## Blog content pipeline — article formats (`scripts/content_formats.py`)

The cron lanes (`auto_publish.py` for evergreen tutorials, `news_publish.py` for
developer news) both draw their article shape from one registry. **Never hardcode a section skeleton in a publisher again** — that
is what made every post on the site read identically.

- `TUTORIAL_FORMATS` (8) / `NEWS_FORMATS` (5) / `SOCIAL_SHAPES` (6): each owns its
  angle, title style, H2 skeleton, and writer brief.
- `pick_format(kind)` rotates least-recently-used against `content/format_history.json`;
  the publisher calls `CF.record(...)` after a successful publish. Consecutive posts
  therefore never share a shape.
- `quality_issues(kind, body, format_id)` gates a draft against **its own** format.
  `enforce_published_quality.py --latest` resolves the format by slug from the history
  file, falling back to `detect_format()` on the headings for older posts.
- Adding a format = one dict entry. Every format must end news pieces on
  `## What I'll Be Watching` and carry `## Sources`.
- `FORBIDDEN_PHRASES` + `FORBIDDEN_REPLACEMENTS` are the single hype blocklist, kept in
  sync with the banned list in `agent/prompts.py`. The news lane repairs matches via
  `clean_forbidden()` rather than binning the draft.
- A slug already in the sitemap means the **topic** is a duplicate: repick it. Never
  suffix the slug with a date to force it through — that shipped the same article twice.

## GitHub roundup pillar (`scripts/github_roundup.py`)

Weekly ranked list of repos by **star gain in the last seven days**, published as a
blog article + cover + Facebook/LinkedIn post (`post_kind="roundup"`).

- Every figure is scraped from GitHub's own `trending?since=weekly` page, which
  publishes the weekly delta directly. A row with no scrapeable number is **dropped,
  never estimated** (taco rule #0001).
- `--topic ai|devtools|all`. If fewer than `MIN_ITEMS` on-topic repos are trending,
  it falls back to `all` and **relabels the headline** — never pad an "AI" list with
  unrelated repos, which would make the title describe contents that aren't there.
- `content/github_roundups.json` tracks the last 30 runs so you can see repeats.
- Not on cron yet. `--dry-run` prints the article + the exact social post.

## Hard project rules (from `config/taco_rules.md` — enforced, do not violate)

- **Voice:** all voiceover uses the ElevenLabs **"Jarnathan"** voice (`reel_generator.tts` default). edge-tts is emergency fallback only — a video shipped with edge-tts FAILED the bar; re-render it.
- **YouTube publish honesty:** never report a post as live without the returned `youtube.com/shorts/<id>` URL. `invalid_grant` = YouTube refresh token expired (uploads down across all pillars) — stop and re-mint via `youtube_shorts_publisher.py auth-url`; `uploadLimitExceeded` = daily cap, back off.
- **Publishing is live and irreversible.** `--publish` / `--privacy public` post to real YouTube + FB + LinkedIn. Use `--dry-run` to rehearse; only go live on explicit instruction.

## Environment gotchas

- **Headless Chromium hangs on this Pi** (no GPU compositor surface) — both render engines were affected. Fixes are in place and must be preserved: `record_frames.mjs` captures via CDP `Page.captureScreenshot({ fromSurface:false })` (not `page.screenshot()`); `remotion/render.mjs` sets `chromiumOptions.enableMultiProcessOnLinux: true`. If a new Chromium-screenshot path hangs, apply the same pattern.
- **Secrets** live in `config/secrets.env` (gitignored), loaded by `agent.config.load_env()`. The `TELEGRAM_TOKEN` there can drift from the live bot token — the valid bot token is also kept at `~/.telegram-bot-token`.
- `remotion/public/` is gitignored; the committed brand logo lives in `remotion/assets/` and `render.mjs` copies it into `public/` at render time.
- Posted-state dedupe files (`content/*_posted.json`, `content/recap_posts.json`) prevent re-posting — the pipelines filter against them.
