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

## Publishing cadence

The blog + LinkedIn are a live demonstration of what the bot produces, so news
throughput is deliberate — the volume IS the demo. Format rotation is what keeps
five posts a day from reading as five copies of the same post.

- News: **5×/day** at 08:00, 11:00, 14:00, 17:00, 20:00 (`bwa-news-publish.sh`)
- Tutorials: **Mon/Wed/Fri 09:00** (`bwa-cron-publish.sh`)
- GitHub roundup: weekly, not yet on cron
- LinkedIn: `DAILY_LIMITS` in `scripts/linkedin_policy.py` — news 5, tutorial 1, roundup 1

**The registry must stay larger than the daily post count.** With 8 news formats and
5 posts/day, each day draws a different subset; if the two numbers ever match, every
day would run the identical format sequence.

## Feed LLM enrichment (`agent/feed.py`) — bounded on purpose

`feed_run` is **not** a cron job. It runs on the in-process scheduler thread in
`agent/automation.py::_scheduler_loop`, started by `smkit dashboard`, configured in
`content/automations.json` (currently `enabled: true`, `dry_run: false`,
`interval_hours: 3` → **8 runs/day**). It only runs while a dashboard process is
alive, and **a running dashboard holds the imported module in memory** — a fix to
`feed.py` does not take effect until that process restarts.

Each enriched item costs **two** LLM calls (`_llm_summary` + `_llm_reason`), and
`build_feed(include_seen=True)` deliberately re-surfaces the same top stories every
run. That combination is how a background job silently becomes the biggest line on
the bill, so enrichment is bounded:

| Setting | Default | Effect |
|---|---|---|
| `FEED_LLM_ENRICHMENT_ENABLED` | `true` | Kill switch. `false` → **zero** provider calls. |
| `FEED_LLM_MAX_ITEMS_PER_RUN` | `5` | Items that may hit the provider per run → **≤10 calls/run, ≤80/day**. |
| `FEED_LLM_DAILY_BUDGET_USD` | `0.50` | Stops the run once today's recorded `feed_llm` spend reaches it. |

Resolution order is **env var > `config/feed.yaml` `llm:` block > default**; env wins
so a runaway job can be stopped without a commit.

- **The cache, not the seen store, is what prevents re-summarizing.** `content/feed/enrichment_cache.json`
  is keyed by a sha256 of the exact prompt inputs (canonical URL + title + source +
  matched interests). A hit reuses the stored summary and makes no call; cache hits do
  **not** consume the per-run cap because they cost nothing. Attempts do — including
  failed ones, since a failure still burns quota.
- **The budget only binds when the model is priced.** The live config runs ollama
  `kimi-k2.7-code:cloud`, which has no entry in `llm_ops.PRICING`, so cost is recorded
  as unknown. Counting unknown as `$0` would let unlimited calls pass a budget check,
  so `EnrichmentStats.budget_enforceable` reports `false` instead of pretending. The
  run stays bounded by the item cap. Add the model to `PRICING` to make the budget real.
- **An empty completion is a failure, not an empty summary.** A 200 with blank content
  raises `EnrichmentEmpty`; nothing empty is ever cached or written to `item.summary`.
- **One bad item never ends a run.** Failures are caught per item, the deterministic
  ranker `reason` survives, and every skip is logged to `content/feed/enrichment_log.jsonl`
  with a reason (`unchanged` / `item_limit` / `budget` / `disabled` / `error`).
  Per-run totals: `feed.last_enrichment_stats()`, also echoed in the automation log line.

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
