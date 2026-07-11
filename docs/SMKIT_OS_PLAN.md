# SMKit → Content Operating System: Implementation Plan

Goal: evolve `smkit` from a set of connected tools into a complete content
operating system — pipeline: intelligence story → content draft → social
drafts → schedule → publish → analytics, with automation, campaigns, media,
and connection health.

## Current state (grounded in code, 2026-07-11)

| Area | Reality |
|---|---|
| **Backend** | Hand-rolled `http.server` (`agent/dashboard.py` 449 L + `agent/dashboard_intelligence.py` 962 L). JSON-file storage in `content/` (no DB). Synchronous request handling — no job queue. |
| **Statuses** | Already exist: content drafts `draft/reviewed/approved/published` (`agent/drafts.py:24`), social drafts add `scheduled/failed` + `scheduled_at` (`agent/social_drafts.py:20`). Guards ("must be approved to schedule/publish") are enforced. |
| **Publishers** | `agent/social_publishers.py` has LinkedIn/FB/Threads/X/Reddit/newsletter/YouTube with per-platform `dry_run`, `published_url`, and `status=failed`+error on failure. `publish_due_social_drafts()` exists — the scheduling engine is done, it just needs a trigger + UI. |
| **Intelligence** | Full engine in `agent/intelligence/`: HN, Reddit, GitHub trending, newsletter sources; scoring; snapshots; briefs; brief→draft API. |
| **Frontend** | React 19 + TanStack Router/Query + Radix + Tailwind SPA in `frontend/`. Real pages: intelligence (843 L), social, drafts, scheduler, dashboard. **Stubs (15 lines each): settings, sources, analytics, assistant.** |
| **Automation** | No cron/scheduler daemon anywhere in `agent/` — the biggest structural gap. |

## Phase 1 — Automation & pipeline spine (enabler for everything else)

1. **`agent/automation.py` — jobs/automations module.**
   - Job registry: `intelligence_run`, `publish_due`, `analytics_sync`,
     `auto_draft` — each with interval, enabled flag, last run, last result,
     next run. Persist to `content/automations.json` +
     `content/automation_log.jsonl` (append-only run log).
   - Background scheduler thread inside the dashboard process (a
     `threading` loop is enough — no Celery on a Pi).
     `publish_due_social_drafts()` finally gets called automatically.
   - The same thread doubles as the **job queue**: POST `/api/jobs`
     enqueues intelligence runs / publishes; GET `/api/jobs/<id>` returns
     progress. Long HTTP handlers (intelligence run currently blocks the
     request) move here.
2. **API:** `/api/automations` (list/update), `/api/automations/<id>/run`,
   `/api/jobs`, `/api/logs`.
3. **Frontend:** build the **Settings → Automations page** (currently a
   stub) — toggle per automation, interval, last/next run, log tail with
   retry buttons. Delivers the "Logs page" requirement too.

## Phase 2 — Campaigns + unified pipeline status

1. **Backend `agent/campaigns.py`:** `create_campaign(brief_item)` fans
   out — content draft (`drafts.py`), social drafts per platform
   (`generate_social_drafts` already takes a source draft), Shorts script
   (`agent/shorts.py`), newsletter blurb, cover image. Store a
   `campaign.json` linking all child IDs → this IS the pipeline tracking:
   one object that knows story → blog → socials → schedule → publish state.
2. **Status vocabulary:** extend `VALID_STATUSES` to add `idea` and
   `needs_review` in both drafts modules (map old `reviewed` →
   `needs_review`), and append a `history: [{ts, from, to, actor}]` entry
   on every `transition_status`/`update_draft` — audit trail is ~15 lines
   since everything funnels through those two functions.
3. **Frontend:** "Create Campaign" button on intelligence cards; campaign
   detail as a **right-side panel** (Radix Dialog/Sheet — deps already
   installed) with per-output approve/edit; pipeline badge
   (idea → drafted → needs review → approved → scheduled →
   published/failed) on every list row.

## Phase 3 — Media panel + draft editor

1. **Media:** the cover generator exists (see commit "generate cover for
   draft blog publishes"). Wrap it: `/api/drafts/<id>/cover` — GET current
   image, POST `{style}` to regenerate, upload custom (endpoint
   `/api/upload` already exists). Style presets (clean tech, editorial,
   diagram, thumbnail, social card) = prompt templates. Platform-crop
   preview (blog/LinkedIn/X/YouTube) is pure CSS aspect-ratio boxes over
   the same image.
2. **Draft editor:** markdown preview (add `react-markdown`), SEO
   title/meta fields (extend `allowed` fields in `agent/drafts.py:199`),
   source links from the originating brief (campaign link from Phase 2
   provides this), and **explicit disabled-state reasons** — the backend
   already returns precise errors ("draft must be approved, current
   status: draft"); surface them as tooltips instead of a dead button.
3. **AI rewrite buttons:** one endpoint
   `/api/drafts/<id>/rewrite {mode: shorter|hook|technical|casual}`
   calling `agent/llm.py` with per-mode prompts in `agent/prompts.py`.
   Also expose `agent/repurpose.py` in the same panel (blog → 5 social
   posts, social → blog outline, short script → newsletter copy).

## Phase 4 — Scheduler calendar, connections, sources & analytics

1. **Scheduler page upgrade:** calendar month/week grid,
   queue-by-platform tabs, drag-drop reschedule → PATCH `scheduled_at`,
   "Retry" on `failed` drafts (re-transition to `approved` → publish).
   Auto-publish toggle per platform lives in the Phase 1 automations
   config.
2. **Connections page:** `/api/connections` probes each publisher's
   credentials (env present? token expiry where knowable? last publish
   result from draft records). Fills the settings stub.
3. **Sources page:** `IntelligenceConfig` already has `enable_reddit`,
   `reddit_subreddits`, etc. — expose as editable config
   (`/api/intelligence/config`), plus per-source last-fetch/health from
   run logs. Add a generic RSS fetcher to `agent/intelligence/sources.py`
   (the only new source type needed; HN/Reddit/GitHub/newsletters exist).
4. **Analytics loop-closing:** `agent/analytics.py` +
   `agent/intelligence/performance.py` exist; the missing link is joining
   published posts back to their source brief — the Phase 2 campaign
   object provides it. "Make more like this" = create-campaign with the
   winning topic pre-seeded.

## Deferred (later, not next)

- **Brand voice profile** — `config/profiles/` exists; formalize a
  `voice.yaml` injected into `agent/prompts.py` (small; can ride along
  with Phase 3).
- **Content memory / dedupe** — `content/published.json` + title-token
  overlap similarity is enough to start.
- **Content scoring, best-time suggestions, backups/export** — export is
  trivial (everything is JSON files — a zip endpoint).

## Hard constraints / flags

1. ⚠️ **`agent/social_publishers.py:60` publishes LinkedIn via
   `linkedin_org_poster.post_org`** — standing rule is personal-feed only,
   org 119694084 off-limits. Fix in Phase 1 *before* wiring auto-publish,
   or the automation will post to the company page.
2. **Auto-publish is live and irreversible** — every automation ships
   defaulting to `dry_run=True` / disabled; the enable toggle is the
   explicit human opt-in. Never enable live publishing by default.
3. Python is **`/usr/bin/python3`** (not shell default); node is
   `/home/linuxbrew/.linuxbrew/bin/node`. Tests: `/usr/bin/python3 -m
   pytest` (backend) and `npm test` in `frontend/` (vitest).
4. Secrets live in `config/secrets.env` (gitignored), loaded by
   `agent.config.load_env()`. Never commit tokens.

## Effort shape

Phases 1–2 are the real work (new backend modules + two frontend
pages/panels). Phases 3–4 are mostly thin API wrappers over existing code
plus frontend build-out of the four stub pages.
