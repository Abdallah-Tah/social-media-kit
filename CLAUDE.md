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
/usr/bin/python3 scripts/github_roundup.py --topic ai --publish # LIVE: blog + FB + LinkedIn + X
/usr/bin/python3 scripts/github_roundup.py --publish --thread    # LIVE: X as a thread — billed PER POST

# Quality enforcement pass (runs right after a tutorial publish)
/usr/bin/python3 scripts/enforce_published_quality.py --latest

# Render a Remotion composition directly (props.json drives it; --audio optional)
node remotion/render.mjs --id Short --props <props.json> --out out.mp4 [--audio vo.mp3]
```

**Always invoke Python with `/usr/bin/python3`** for these scripts — the modules expect that interpreter (the shell default differs). Node for Remotion/Playwright is `/home/linuxbrew/.linuxbrew/bin/node`.

## Publishing cadence

The blog + LinkedIn are a live demonstration of what the bot produces, so the bar
is depth per piece, not throughput. Format rotation keeps consecutive posts from
reading as copies of each other.

- News: **2×/day** at 08:00 and 17:00 (`bwa-news-publish.sh`)
- Tutorials: **Mon/Wed/Fri 09:00** (`bwa-cron-publish.sh`)
- GitHub roundup: **Sundays 10:00** (`bwa-roundup-publish.sh`) — the only
  scheduled job that posts to X
- LinkedIn: `DAILY_LIMITS` in `scripts/linkedin_policy.py` — news 2, tutorial 1,
  roundup 1. **Keep this in step with the cron cadence**: a limit above it does
  nothing, below it silently drops posts.

**News was 5×/day until 2026-08-01.** The volume was the demo, and it stopped
demonstrating competence: measured across 111 articles, the news lane averaged
~1,000 words, **1.2 source hosts, and zero code blocks**, while the tutorial lane
(which enforces `min_code` 4-6) produced 2,000-word articles with real code. Five
slots a day is more than any pipeline can source, verify, and write well. The cut
to 2 buys depth per piece; do not raise it without raising `min_code`,
`NEWS_MIN_SOURCES`, and checking the block rate in `logs/smkit-news.log`.

**The registry must stay larger than the daily post count.** With 8 news formats and
2 posts/day, each day draws a different subset; if the two numbers ever match, every
day would run the identical format sequence.

## Feed LLM enrichment (`agent/feed.py`) — bounded on purpose

`feed_run` is **not** a cron job. It runs on the in-process scheduler thread in
`agent/automation.py::_scheduler_loop`, started by `smkit dashboard`, configured in
`content/automations.json` (currently `enabled: true`, `dry_run: false`,
`interval_hours: 3` → **8 runs/day**). It only runs while a dashboard process is
alive, and **a running dashboard holds the imported module in memory** — a fix to
`feed.py` does not take effect until that process restarts.

`build_feed(include_seen=True)` deliberately re-surfaces the same top stories every
run. That is how a background job silently becomes the biggest line on the bill, so
enrichment is bounded and cached.

**Feed enrichment runs its own model, deliberately not `AgentConfig`.** The agent loop
uses `kimi-k2.7-code:cloud` — a *reasoning* model whose reasoning tokens are drawn from
the same completion budget as its content. At 256 `max_tokens` it returned
`finish_reason=length` with truncated or empty content on **6 of 10** live attempts.
Feed enrichment is a small structured-extraction job and wants a small non-reasoning
model. Never point feed enrichment at a reasoning model; raise nothing to compensate.

**One request per item.** `_llm_enrich` makes a single `response_format=json_object`
call returning `{"summary": ..., "reason": ...}`. The structured response is what makes
validation possible at all — with free text there was no way to tell a complete answer
from one the provider cut off.

| Setting | Default | Effect |
|---|---|---|
| `FEED_LLM_ENRICHMENT_ENABLED` | `true` | Kill switch. `false` → **zero** provider calls. |
| `FEED_LLM_MAX_ITEMS_PER_RUN` | `5` | Items that may hit the provider per run → **≤5 requests/run, ≤40/day**. |
| `FEED_LLM_DAILY_BUDGET_USD` | `0.50` | Stops the run once today's recorded `feed_llm` spend reaches it. |
| `FEED_LLM_PROVIDER` | `openai` | Feed-only provider. |
| `FEED_LLM_MODEL` | `gpt-4o-mini` | Feed-only model. Priced, so the budget actually binds. |
| `FEED_LLM_BASE_URL` / `FEED_LLM_API_KEY` | provider default / `config/secrets.env` | Credentials come from the environment via `load_env()`; never hardcoded. |
| `FEED_LLM_MAX_TOKENS` / `FEED_LLM_TEMPERATURE` / `FEED_LLM_TIMEOUT` / `FEED_LLM_JSON_MODE` | `400` / `0.4` / `60` / `true` | Turn `JSON_MODE` off for providers without `response_format`. |

Resolution order for **every** setting above is **env var > `config/feed.yaml` `llm:`
block > default**; env wins so a runaway job can be stopped without a commit.

A response is rejected — never stored, never cached — when it fails to parse, is
missing a key, has a blank field, arrives with `finish_reason=length`, ends
mid-sentence, exceeds the length caps, or whose `reason` is a stub or an echo of the
summary. Each raises a distinct `EnrichmentError` subclass so the decision log records
what actually went wrong.

- **The cache, not the seen store, is what prevents re-summarizing.** `content/feed/enrichment_cache.json`
  is keyed by a sha256 of the exact prompt inputs (schema version + canonical URL +
  title + source + matched interests). A hit reuses the stored answer and makes no call;
  cache hits do **not** consume the per-run cap because they cost nothing. Attempts do —
  including failed ones, since a failure still burns quota. **Bump
  `ENRICHMENT_SCHEMA_VERSION` whenever the prompt or response schema changes**, or
  stale answers from a prompt that no longer exists will be served forever.
- **The budget only binds when the model is priced.** `gpt-4o-mini` is in
  `llm_ops.PRICING`, so it binds today. If you repoint the feed at an unpriced model
  (ollama, gemini, alibaba) cost is recorded as unknown; counting unknown as `$0` would
  let unlimited calls pass a budget check, so `EnrichmentStats.budget_enforceable`
  reports `false` instead of pretending, and the run stays bounded by the item cap only.
- **An empty or truncated completion is a failure, not a result.** Nothing blank or
  cut off is ever written to `item.summary` or cached — it would read as a complete
  answer once stored and suppress every future retry.
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
- **Rendering is per-platform** (`scripts/social_formatters.py`): LinkedIn gets the
  full post, X gets its own renderer. Rank, star delta, total and repo count are
  computed in Python and the headline is derived from the list it prints, so they
  cannot drift; the model only writes prose, and a rewritten summary may replace
  an existing description but never fill a blank one.
- **X posts once, as a single post.** `--thread` is opt-in because every post in a
  thread is billed separately — a 7-post thread costs seven times a single post.
  `MAX_THREAD_POSTS` (8) caps it; over the cap it falls back to one post.
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
