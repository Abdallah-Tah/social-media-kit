# Build With Abdallah — Auto‑Publishing Pipeline (A→Z)

> How `smkit` decides what to publish every few hours and runs the whole thing
> from topic choice to a live article + social posts. This is the deterministic
> publisher (`scripts/auto_publish.py`) driven by cron — **no AI autonomy is
> required to pick the steps; the code controls the flow.**

---

## 0. When it runs (the trigger)

A user cron job runs the orchestrator on a schedule:

```cron
0 6-21/3 * * 1-5  /home/abdaltm86/.local/bin/bwa-cron-publish.sh >> /home/abdaltm86/logs/smkit-cron.log 2>&1
```

- **Weekdays (Mon–Fri), 06:00–21:00, every 3 hours** → fires at 06, 09, 12, 15, 18, 21.
- All output is appended to `~/logs/smkit-cron.log`.
- A separate cron runs the **Pitch Agent** review (`bwa-pitch-agent.sh`) — that is a different product and is not part of this pipeline.

Each run produces **at most one** new article (it aborts cleanly if it can't make a good one).

---

## High‑level flow

```
cron ──► bwa-cron-publish.sh  (orchestrator: env, markers, notifications)
            │
            ├─ snapshot "latest post id" (BEFORE)
            │
            ├─ scripts/auto_publish.py   ◄── the brain: decide + create + publish
            │     1 recent_titles()      fetch last 25 titles (dedupe source)
            │     2 pick_cluster()        rotate to the LEAST‑covered topic cluster
            │     3 find_topic()          web search (SearXNG/Brave…) + gpt‑4o picks 1 topic
            │     4 slug_in_sitemap()     reject if already on the live site
            │     5 write_article()       gpt‑4o "two‑halves" writer (~1,500 words, real code)
            │     6 word‑count gate       < 700 words → abort, no publish
            │     7 save draft            prints "Saved draft to <path>"
            │     8 generate_cover()      Gemini → FAL → OpenAI → local card
            │     9 publish_article()     POST to blog REST API (cover rehosted on‑site)
            │    10 Facebook photo        social_copy + fb_poster
            │
            ├─ marker check: did it print "Saved draft to"? no → notify + exit 1
            ├─ detect new post id (AFTER ≠ BEFORE)?  no → stop (nothing new)
            │
            ├─ enforce_published_quality.py   regen thin body / rehost cover, PATCH
            ├─ version_sanity_check.py        wrong release claim? → UNPUBLISH + stop
            ├─ github_gist_from_article.py    public Gist snapshot (code files)
            ├─ linkedin_from_article.py       LinkedIn personal post
            ├─ reel_from_article.py --publish Facebook reel (voiceover video)
            │
            └─ post_telegram summary (what published / posted / skipped / held)
```

---

## 1. Orchestrator — `~/.local/bin/bwa-cron-publish.sh`

The bash wrapper that sequences everything and reports to Telegram.

1. `set -euo pipefail`, `cd` into the kit.
2. Loads the Telegram bot token from `~/.telegram-bot-token` and sets the target
   chat/topic (`TELEGRAM_CHAT_ID`, `TELEGRAM_MESSAGE_THREAD_ID`).
3. Captures **`BEFORE`** = the ID of the newest blog post (via the blog REST API),
   so it can detect whether a *new* post actually went live this run.
4. Runs the deterministic publisher and tees output to a temp file.
5. **Marker gate:** if the output does **not** contain `Saved draft to`, the run
   is declared failed → Telegram notify → `exit 1` (nothing was published).
6. Captures **`AFTER`**. If `AFTER == BEFORE`, no new article → skip all social.
7. If a new post exists, runs the post‑publish chain (quality → version check →
   gist → LinkedIn → reel) and sends one Telegram summary.

> Note: the long English "GOAL" prompt block inside the script is **legacy** —
> it described the old autonomous writing agent. The live path is the
> deterministic `auto_publish.py`; that prompt is no longer the driver.

---

## 2. The brain — `scripts/auto_publish.py`

### 2A. Gather what already exists — `recent_titles()`
`GET {BLOG_API_URL}/posts?per_page=25` → the titles of the last 25 posts. This
list is the **de‑duplication memory** used in the next two steps.

### 2B. Decide the area — `pick_cluster()` (rotation)
There are 8 content **clusters**, each with keywords:

| Cluster | Example keywords |
|---|---|
| Laravel/PHP | laravel, php, eloquent, artisan, symfony, nativephp |
| Python | python, fastapi, django, flask, pydantic, pandas |
| React/Next.js | react, next.js, remix, jsx |
| Vue/Nuxt | vue, nuxt, pinia, vite |
| .NET/C# | .net, c#, asp.net, blazor, dotnet |
| C++ | c++, cpp, cmake |
| AI agents | ai agent, llm, mcp, rag, claude, openai |
| Automation / DevOps | docker, ci/cd, github actions, cron, devops |

It counts how often each cluster's keywords appear across the recent titles and
**picks the cluster with the lowest count** — i.e. the area you've covered least
recently. This is what makes topics rotate instead of repeating.
(Can be overridden with `--cluster "Laravel/PHP"`.)

### 2C. Pick one fresh topic — `find_topic()`
1. Builds search queries for the chosen cluster (e.g. *"Python new release
   features 2026"*, *"Python popular library tutorial 2026"*), plus any
   `CLUSTER_FOCUS` preferred subjects (currently NativePHP for Laravel/PHP).
2. Runs them through **`content_research.web_search()`**, which tries providers
   in order until one returns results: **Brave (needs `BRAVE_API_KEY`) → SearXNG
   (`SEARXNG_URL`, self‑hosted in `deploy/searxng`) → DuckDuckGo → Wikipedia
   (fallback grounding)**. Force one with `SEARCH_PROVIDER=brave|searxng|duckduckgo|wikipedia`.
3. Feeds the live search titles + the "already published" list into **gpt‑4o**
   with a strict instruction: pick **one specific, non‑duplicate** tutorial
   subject and return JSON `{"title": "...", "slug": "..."}`.
4. If the model call fails, it falls back to a generic
   *"Getting Started with <cluster>"* title.
   (Can be overridden entirely with `--topic "Exact Title"`.)

### 2D. Final duplicate guard — `slug_in_sitemap()`
Fetches `https://buildwithabdallah.com/sitemap.xml`. If the slug already exists
on the live site, it appends today's `MMDD` to make it unique (belt‑and‑braces
on top of the title‑level dedupe).

### 2E. Write the article — `write_article()` (in `enforce_published_quality.py`)
Because gpt‑4o caps a single answer near ~700 words, the tutorial is written in
**two halves** for reliable length:

- **Part A (system = "senior dev voice"):** `# Title`, intro, `## Prerequisites`
  (real install commands), `## Project Structure` (a tree), and the first three
  numbered `## Step` sections with complete code. ~850 words.
- **Part B:** continues seamlessly — the remaining steps, a `## Complete Working
  Example`, `## Common Errors and Fixes`, `## Conclusion`, and `## Sources` with
  real URLs. ~750 words.
- Output is de‑fenced (`unwrap_markdown_fence`) so a model that wraps the whole
  answer in ```` ```markdown ```` doesn't render as one big code block.

**Voice rules enforced in the prompt:** clear direct English, real
copy‑pasteable code with language labels, no hype words (*dive into, unlock,
seamlessly, robust, game changer, revolutionary*), minimal emojis, no invented
benchmarks.

### 2F. Quality gate
`len(body.split()) < 700` → print *"article too short — aborting"* and return
without publishing.

### 2G. Save the draft
Writes `content/drafts/<date>_<slug>.md` and prints **`Saved draft to <path>`**
(the marker the orchestrator checks).

### 2H. Generate the cover — `image_generator.generate_cover()`
Provider chain (first one with a key/working wins):
**Gemini `gemini‑2.5‑flash‑image` → FAL `flux‑pro/v1.1‑ultra` → OpenAI
`gpt‑image‑1` → local branded HTML/Playwright card.** Remote images are
downloaded into `content/assets/`. Force one with `IMAGE_PROVIDER=...`.

### 2I. Publish — `blog_publisher.publish_article()`
`POST {BLOG_API_URL}/posts` with `title, slug, body, excerpt, publish=true,
cover_image`. Supports generic / WordPress / Ghost back‑ends (selected by
`BLOG_PLATFORM`). Before sending, **`_ensure_hosted_cover()`** re‑uploads any
local/temporary cover (e.g. an expiring FAL CDN URL) to the site's media library
so the live cover never breaks. Prints **`Published: Post ID <id>`**.

### 2J. Facebook (first social touch)
Builds caption with **`social_copy.make_social_copy()`** (gpt‑4o‑mini, "Abdallah's
voice", 3–5 hashtags, banned hype words) and posts the cover photo (or a link)
to the Page via **`fb_poster`** (Graph API).

---

## 3. Post‑publish chain (only if a new post went live)

| Order | Script | What it does | Failure behaviour |
|---|---|---|---|
| 1 | `enforce_published_quality.py --latest` | If body `< 1100` words or `< 4` code blocks → regenerate with the two‑halves writer; if cover is missing/off‑site → regenerate + host; `PATCH` the post. | Marks `⚠️ Quality check failed`, continues |
| 2 | `version_sanity_check.py --latest` | Deterministic C#/.NET version‑mapping check **+** an LLM/web‑grounded fact check for wrong versions or "preview called stable". | **Exit 2 = HELD:** post is set back to **draft (unpublished)**, Telegram notified, **whole run stops** (no social) to protect credibility. A soft `REVIEW_NOTE` keeps the post live but flags it. |
| 3 | `github_gist_from_article.py --latest` | Creates a public **GitHub Gist** (via `gh` CLI, account Abdallah‑Tah): `TUTORIAL.md` + every fenced code block extracted as a runnable file. | `⚠️ Gist failed`, continues |
| 4 | `linkedin_from_article.py --latest` | Writes a short professional post (gpt‑4o‑mini) and posts to the **LinkedIn personal feed** with the cover. | `⚠️ LinkedIn failed`, continues |
| 5 | `reel_from_article.py --latest --publish` | LLM writes a ~25s narration + 4 caption lines, builds a **voiceover reel**, uploads to the Facebook page (published). | `⚠️ Reel failed`, continues |

### 4. Telegram summary
One message with the title, URL (`/tutorials/<slug>`), and the ✅/⚠️ status of
Quality, Gist (+ URL), LinkedIn, and Reel — plus any version‑review note.

---

## Tools, models & external services

| Concern | Tool / service | Where |
|---|---|---|
| Topic pick + article + quality regen | **OpenAI gpt‑4o** | `auto_publish.py`, `enforce_published_quality.py` |
| Social copy + LinkedIn + reel script | **OpenAI gpt‑4o‑mini** | `social_copy.py`, `linkedin_from_article.py`, `reel_from_article.py` |
| Fresh‑news search | **Brave → SearXNG → DuckDuckGo → Wikipedia** | `content_research.py` |
| Cover image | **Gemini / FAL / OpenAI / local card** | `image_generator.py` |
| Blog publish | **Blog REST API** (generic/WordPress/Ghost) | `blog_publisher.py` |
| Code snapshot | **GitHub Gist** via `gh` CLI | `github_gist_from_article.py` |
| Social channels | **Facebook Graph API**, **LinkedIn API** | `fb_poster.py`, `linkedin_from_article.py`, `reel_from_article.py` |
| Notifications | **Telegram Bot API** | orchestrator + `telegram_poster.py` |
| Dedupe | recent posts list + `sitemap.xml` | `auto_publish.py` |

### Secrets / env (loaded by `agent/config.load_env()` from `secrets.env`)
`OPENAI_API_KEY`, `GEMINI_API_KEY`/`FAL_KEY` (optional cover),
`BLOG_API_URL`, `BLOG_API_TOKEN`, `BLOG_PLATFORM`, `SOCIAL_API_TOKEN`,
`FB_PAGE_ID`, `FB_PAGE_TOKEN`, LinkedIn token (via site endpoint),
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_MESSAGE_THREAD_ID`.

---

## Safety gates (why a run may publish nothing)

1. **Word floor** — article `< 700` words in `auto_publish.py` → abort.
2. **Missing marker** — no `Saved draft to` → orchestrator fails the run.
3. **No new post** — `AFTER == BEFORE` → social steps skipped.
4. **Quality floor** — `< 1100` words / `< 4` code blocks → regenerated before social.
5. **Version sanity** — wrong release claim → post **unpublished** and run halts.
6. **Slug/title dedupe** — recent titles + live sitemap prevent repeats.

Each social step is independent and non‑fatal: one failing channel does not block
the others, and the Telegram summary always reports the real outcome.

---

## Run it manually / test

```bash
cd ~/social-media-kit

# Full deterministic publish (auto‑rotate cluster):
/usr/bin/python3 scripts/auto_publish.py

# Force the area or the exact topic:
/usr/bin/python3 scripts/auto_publish.py --cluster "Laravel/PHP"
/usr/bin/python3 scripts/auto_publish.py --topic "Using Laravel Pennant for Feature Flags"

# Run the whole cron path by hand (publishes + social + Telegram):
bash ~/.local/bin/bwa-cron-publish.sh

# Individual post‑publish steps against the newest post:
/usr/bin/python3 scripts/enforce_published_quality.py --latest
/usr/bin/python3 scripts/version_sanity_check.py --latest
/usr/bin/python3 scripts/github_gist_from_article.py --latest
/usr/bin/python3 scripts/linkedin_from_article.py --latest
/usr/bin/python3 scripts/reel_from_article.py --latest --publish
```

> ⚠️ These hit live services (your blog, Facebook, LinkedIn, GitHub, Telegram).
> Use `--cluster`/`--topic` on a quiet day to test, and watch `~/logs/smkit-cron.log`.
