---
name: social-media-agent
description: The Build With Abdallah content + video engine (smkit). Two halves — (A) research→write→publish articles & native social posts (blog, Facebook, LinkedIn, Telegram, etc.), and (B) The Pitch Agent World Cup 2026 video pillars (full-screen prediction Shorts, a daily "Today at the World Cup" slate, match recaps, and rules explainers) rendered with Remotion and voiced with ElevenLabs. Use when the user wants to create/publish content, run a content routine, or produce/ship football videos.
homepage: https://github.com/Abdallah-Tah/social-media-kit
user-invocable: true
metadata:
  openclaw:
    emoji: "📡"
    requires:
      bins:
        - python3
    install:
      - id: pip
        kind: shell
        command: "python3 -m pip install -r {baseDir}/../../requirements.txt && python3 -m pip install -e {baseDir}/../.."
        label: "Install Social Media Agent dependencies"
---

# Social Media Agent (smkit) — operator guide

The kit lives at `~/social-media-kit` (= `{baseDir}/../..`). Run commands from
there or use absolute paths. It now has **two halves**:

- **A. Content pipeline** — research → write → cover image → publish an article +
  native social posts. (the original capability)
- **B. The Pitch Agent — World Cup 2026 video pillars** — code-rendered vertical
  Shorts (Remotion + ElevenLabs), auto-published. THIS is the current focus.

## Interpreter note (important)
Run kit Python with **`/usr/bin/python3`** (it has the deps). Node for Remotion
is **`/home/linuxbrew/.linuxbrew/bin/node`**. The shell `python`/`node` differ.

---

## BRAND LAW (never violate)
1. **One theme only: the white `light_brand`.** All video chrome comes from the
   shared **`remotion/src/brand/BrandFrame.tsx`** (tokens in `remotion/src/brand/tokens.ts`,
   pulled from `templates/shorts/match_recap_wide.html`). Never dark/alternate themes.
2. **Voice = ElevenLabs "Jarnathan"** (`c6SfcYrb2t09NHXiT80T`) for ALL video VO —
   the default in `scripts/reel_generator.py::tts()`. **Never edge-tts** (robotic;
   emergency fallback only). If a render used edge-tts it FAILED the bar.
3. **Football footer on every video:** "The Pitch Agent by BuildWithAbdallah ·
   Independent analytics · Not affiliated with FIFA". Original animation only —
   **never real match footage** (copyright-flagged).
4. **Outward/publish actions are LIVE + irreversible.** Default to dry-run /
   preview-to-Telegram; only publish after Master confirms (or a cron Master set up).

---

## B. The video pillars (current)

Engine: **Remotion** at `~/social-media-kit/remotion/`. Generic renderer:
`node remotion/render.mjs --id <Composition> --props <json> [--audio <mp3>] --out <mp4>`
(it auto-stretches scene durations to the voiceover). Compositions: `Prediction`,
`DailySlate`, `Explainer`, `Short` — all render inside `BrandFrame`.

| Pillar | Script | Cron | Publishes to |
|--------|--------|------|--------------|
| **Per-match prediction Shorts** (full-screen "MATCH PREDICTION" card, flags, win-prob bars, model call) | `scripts/football_prediction_shorts.py` | `bwa-football.sh live` @ **09:00** (throttled `--max 1/day`) | YouTube (main) + FB |
| **Daily "Today at the World Cup" slate** (today's matches + model picks + yesterday's graded results, image-rich) | `scripts/daily_wc_short.py` | `bwa-wc-daily.sh` (**not armed** — manual for now) | YouTube + FB |
| **Match recaps** ("did the model get it right?") | `scripts/recap_publish.py` via `bwa-football-recap.sh` | **every 2h** | YouTube + FB |
| **Rules explainers** (newcomer "what is offside" etc.) | `scripts/explainer_short.py` / `scripts/rules_daily.py` | `bwa-rules-daily.sh` @ **11:00** (auto-publish) | YouTube (main) |

Common helpers: voice `reel_generator.tts()`; images `wc_images.py` (flags via
flagcdn, Pexels atmosphere b-roll, **free-licensed Wikimedia** photos w/
attribution, AI fallback); upload `youtube_shorts_publisher.py`.
World Cup YouTube uploads should pass a custom thumbnail from
`scripts/worldcup_thumbnail.py`: original pitch artwork, "World Cup 2026"
positioning, pillar label, readable matchup/topic text, and The Pitch Agent /
Build With Abdallah footer. Do not use FIFA logos or copied tournament artwork.

**Crossposting — two different tools, don't conflate them:**
- `football_crosspost.py` posts a Facebook **photo** carrying the **YouTube link**.
  LinkedIn is intentionally skipped for football/video pillars.
- To put the **actual video as a Facebook Reel**, use **`fb_reels_publisher.py`**
  (that is what publishes a real FB video).
- LinkedIn policy is enforced in `scripts/linkedin_policy.py`: **one LinkedIn
  post per local day, news only**. Only `scripts/news_publish.py` passes
  `post_kind="news"`; tutorial/article/football/video posts must not post there.

### Prediction model (The Pitch Agent)
- CLI: `/usr/bin/python3 -m pitch_agent.cli {predict,accuracy,sync-results,record-result,generate-content}`.
- The **predictions ledger is the accountability spine** — `predict` journals win
  probs + scoreline distribution; entries are **immutable post-kickoff**.
  **NEVER backfill predictions.** `accuracy` prints the live record (current
  MODEL_VERSION). Draw-calibrated (Dixon-Coles) since v1.2.

### Rules explainers — the hard contract (a daily auto-publishing rules channel)
- Topic bank: `content/explainers/topics.json`. Each topic has vetted `rule_text`
  (IFAB), `source`, `priority`, `visual`, and **pre-written `beats[]` caption
  strings**.
- **Rule-stating captions render VERBATIM from the bank — the LLM NEVER writes
  rule facts** (it only writes the hook + CTA). The engine **refuses to render
  unless `rule_text` is non-empty AND `vetted: true`**.
- **In-force 2025/26 rules only** — never depict proposals/trials as rules.
- Run one: `/usr/bin/python3 scripts/explainer_short.py --topic <id> --approve [--publish]`.
- Daily auto: `scripts/rules_daily.py` (next vetted topic by priority → publish →
  Telegram notice). Channel config: `config/explainer.yaml`.

---

## Publishing surfaces + gotchas
- **YouTube** (`scripts/youtube_shorts_publisher.py upload --profile main`). Token
  = `YOUTUBE_REFRESH_TOKEN` in `config/secrets.env`. **Two real gotchas:**
  (1) **Daily upload cap** — if you see `uploadLimitExceeded`, the channel hit its
  quota; back off and retry (`scripts/retry_daily_youtube.py` pattern). Predictions
  are throttled to ≤1/day so they don't starve the cap.
  (2) **Refresh token expires** (`invalid_grant`) — re-mint with
  `youtube_shorts_publisher.py auth-url` → authorize as the BWA channel →
  `exchange-code --code <code>`. Permanent fix: publish the Google OAuth app to
  **Production** (Testing mode expires tokens every 7 days). Scope is upload-only.
- **Blog** = buildwithabdallah.com is a **Laravel + Sanctum REST API** (NO SSH /
  WordPress). Publish/update: `POST`/`PATCH https://buildwithabdallah.com/api/v1/posts`
  with Bearer; fields `title, slug, body(markdown), excerpt, status(published|draft),
  category_id, tags[], meta_*, cover_image`. **Public URL = `/tutorials/<slug>`**
  (verifying root `/<slug>` falsely 404s). `scripts/blog_publisher.py` wraps it.
- **Facebook** page (`fb_poster.py` photo/text; `fb_reels_publisher.py` for video
  reels). **LinkedIn** personal feed (org page 403s; `linkedin_org_poster.post_org`
  with token+author). **Telegram** preview/review topic 14119 (`telegram_poster.py`).

---

## A. Content pipeline (still active)
```bash
smkit run --topic "<topic>" --profile live-blog-fb-linkedin --dry-run   # rehearse
smkit run --topic "<topic>" --profile live-blog-fb-linkedin --yes       # go live
smkit doctor      # which providers/channels are configured
smkit profiles    # brand voices
```
News pillar: `scripts/news_publish.py` (AI/tech, twice daily). Single steps live
in `scripts/`: `blog_publisher.py`, `fb_poster.py`, `linkedin_*`, `telegram_poster.py`,
`content_research.py`, `image_generator.py` (cover chain Gemini→FAL→OpenAI→Pillow).

---

## Cron map (what runs unattended)
| When | Job | Purpose |
|------|-----|---------|
| 06/09/15 wkdays | `bwa-cron-publish.sh` | article auto-publish (→ smkit-cron.log) |
| 12/17 daily | `bwa-news-publish.sh` | AI/tech news (→ smkit-news.log) |
| 09:00 daily | `bwa-football.sh live` | matchday preview + journal + 1 prediction Short |
| every 2h | `bwa-football-recap.sh` | recap newest finished match |
| 11:00 daily | `bwa-rules-daily.sh` | rules explainer (auto-publish) |
| 02:30 daily | `taco-reflect.sh` | self-improvement (proposals only, human-gated) |

## Hard rules (recap)
1. Never fabricate facts; rule facts ONLY from the vetted bank; ground articles in sources.
2. One light_brand theme; Jarnathan voice; "Not affiliated with FIFA"; no real footage.
3. Never backfill predictions; ledger is immutable post-kickoff.
4. Dry-run / Telegram-preview by default; publish only on Master's OK or a Master-set cron.
5. If a channel/credential is down, skip + report — partial success is fine.

Credentials: `config/secrets.env` (+ `~/.config/social-media-kit/secrets.env`,
`~/.config/openclaw/secrets.env`). `smkit doctor` reports status.
