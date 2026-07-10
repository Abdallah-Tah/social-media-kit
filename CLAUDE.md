# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Two products share one codebase:

1. **`smkit` — the social-media agent** (`agent/`): provider-agnostic (Claude / OpenAI / Ollama) routine that researches a topic → writes an article → adapts native posts per platform → publishes. Entry: `agent.cli:main`. The README documents this product.
2. **The Pitch Agent / World Cup video pipeline** (`pitch_agent/` + `scripts/` + `remotion/`): an independent football-analytics model that predicts matches, grades itself, and renders branded vertical videos (YouTube Shorts + cross-posts). This is the **BuildWithAbdallah** channel content and is where most active work happens.

A third piece, **Taco** (`agent_journal/`), is a self-improvement loop: it proposes rule changes that get applied to `config/taco_rules.md` (loaded into the agent system prompt via `agent/prompts.py`).

## Console scripts (from `pyproject.toml`)

- `smkit` → `agent.cli:main` (content agent: `smkit run --topic ... --dry-run|--yes`, `smkit repurpose`, `smkit dashboard`)
- `pitch-agent` → `pitch_agent.cli:main` (the football model — see subcommands below)
- `taco-journal` → `agent_journal.cli:main`

`pitch-agent` subcommands: `init-db migrate-db sync-data compute-index leaderboard fixtures render-chart generate-content predict recompute accuracy load-priors validate-priors record-result sync-results transparency`.

## Common commands

```bash
# Tests (pytest; testpaths=tests, addopts=-q already set)
/usr/bin/python3 -m pytest                       # whole suite
/usr/bin/python3 -m pytest tests/test_pitch_agent.py -q
/usr/bin/python3 -m pytest tests/test_pitch_agent.py -k draw   # single test by name

# Model record (the LIVE ledger — single source of truth, never recompute by hand)
/usr/bin/python3 -m pitch_agent.cli accuracy

# Render+publish a prediction Short (todays_upcoming, auto-skips already-posted)
/usr/bin/python3 scripts/football_prediction_shorts.py --dry-run            # rehearse
/usr/bin/python3 scripts/football_prediction_shorts.py --privacy public --max 1

# Render+publish a post-match recap
/usr/bin/python3 scripts/recap_publish.py --match <id>            # build only (no upload)
/usr/bin/python3 scripts/recap_publish.py --latest --publish      # publish newest finished

# Render a Remotion composition directly (props.json drives it; --audio optional)
node remotion/render.mjs --id Prediction --props <props.json> --out out.mp4 [--audio vo.mp3]
```

**Always invoke Python with `/usr/bin/python3`** for these scripts — the modules expect that interpreter (the shell default differs). Node for Remotion/Playwright is `/home/linuxbrew/.linuxbrew/bin/node`.

## Video pipeline architecture (the part that needs multiple files to understand)

Data → props → render → upload, in this flow:

1. **Model** (`pitch_agent/`): `predict()` reads the `pitch_agent.db` SQLite (`matches`, `predictions`, `prediction_results`), blends Elo priors + Poisson scorelines, and writes an immutable journaled prediction. `accuracy` reads `prediction_results` for the ledger.
2. **Pillar builders** (`scripts/`): each content type is its own script that turns model output into Remotion props and drives rendering + publishing:
   - `football_prediction_shorts.py` — pre-match prediction Short. `build_props()` shapes the props; `compute_ledger()` derives the on-screen record from `pitch-agent accuracy` (never fabricated); `voiceover()` calls `reel_generator.tts`.
   - `recap_publish.py` — post-match recap; builds dialogue scenes for `worldcup_atmosphere_short` and includes a prediction-vs-result accountability scene.
   - `daily_wc_short.py`, `news_publish.py`, `explainer_short.py`, `worldcup_survival_lab.py`, `worldcup_deep_dive.py` — other pillars.
3. **Renderers** (two separate engines — know which one a pillar uses):
   - **Remotion** (`remotion/`, React/TSX): full-screen compositions in `remotion/src/` (e.g. `Prediction.tsx`, `DailySlate.tsx`), all wrapped by the shared `remotion/src/brand/BrandFrame.tsx`. Brand tokens are centralized in `remotion/src/brand/tokens.ts` / `theme.ts` — **change brand values in one place**. `remotion/render.mjs` bundles + renders.
   - **`scripts/record_frames.mjs`** (Playwright): screenshots an HTML template (`templates/shorts/*.html`) frame-by-frame for the recap/dialogue/atmosphere pillars; ffmpeg stitches + composites.
4. **Publish**: `youtube_shorts_publisher.py` (OAuth) uploads; `football_crosspost.py` cross-posts FB/LinkedIn; `telegram_poster.py` posts samples for review.

## Hard project rules (from `config/taco_rules.md` — enforced, do not violate)

- **One theme only:** every Pitch Agent / World Cup video uses the white `light_brand` via the shared `BrandFrame`. Never a dark or alternate theme.
- **Voice:** all voiceover uses the ElevenLabs **"Jarnathan"** voice (`reel_generator.tts` default). edge-tts is emergency fallback only — a video shipped with edge-tts FAILED the bar; re-render it.
- **No betting/gambling framing — ever.** This is an AI/automation/analytics channel. No betting, odds, bookies, "locks", or guaranteed-win language. (Meta/3rd-party growth advice that suggests "beat the bookies" must be reworded.)
- **Prediction ledger is immutable.** Never backfill, invent, or "recompute from memory" a prediction. Report the record only from `pitch-agent accuracy`. Predictions are journaled pre-kickoff and frozen after kickoff.
- **No real match footage** (copyright-flagged) — original animation only. Keep the "Not affiliated with FIFA" footer.
- **YouTube publish honesty:** never report a post as live without the returned `youtube.com/shorts/<id>` URL. `invalid_grant` = YouTube refresh token expired (uploads down across all pillars) — stop and re-mint via `youtube_shorts_publisher.py auth-url`; `uploadLimitExceeded` = daily cap, back off.
- **Publishing is live and irreversible.** `--publish` / `--privacy public` post to real YouTube + FB + LinkedIn. Use `--dry-run` to rehearse; only go live on explicit instruction.

## Environment gotchas

- **Headless Chromium hangs on this Pi** (no GPU compositor surface) — both render engines were affected. Fixes are in place and must be preserved: `record_frames.mjs` captures via CDP `Page.captureScreenshot({ fromSurface:false })` (not `page.screenshot()`); `remotion/render.mjs` sets `chromiumOptions.enableMultiProcessOnLinux: true`. If a new Chromium-screenshot path hangs, apply the same pattern.
- **Secrets** live in `config/secrets.env` (gitignored), loaded by `agent.config.load_env()`. The `TELEGRAM_TOKEN` there can drift from the live bot token — the valid bot token is also kept at `~/.telegram-bot-token`.
- `remotion/public/` is gitignored; the committed brand logo lives in `remotion/assets/` and `render.mjs` copies it into `public/` at render time.
- Posted-state dedupe files (`content/*_posted.json`, `content/recap_posts.json`) prevent re-posting — the pipelines filter against them.
