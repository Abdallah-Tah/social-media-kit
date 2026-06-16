# The Pitch Agent — World Cup growth strategy (views + subscribers)
_Written overnight 2026-06-14. Strategy + one safe tool. Nothing was published._

## The honest situation
- We currently post **text match-previews to Telegram + Facebook**. That's it on a schedule.
- We have **zero scheduled YouTube output**. One recap video has ever been made.
- Highlights/footage are **copyright-flagged** (already learned the hard way) — we can't compete on match clips.
- We have something almost no football channel has: **an AI that publicly predicts every match and then grades itself.**

## The core idea (Apple philosophy: do ONE thing nobody else can, excellently)
Stop trying to be a football channel. Be **"the AI that bets on every World Cup game and keeps the receipts."**
Highlights are saturated and we'd lose. A transparent, self-grading prediction model is a *narrative franchise* — and it's 100% original graphics, so it's copyright-safe forever.

The growth engine is a **two-beat retention loop per match**, the single strongest mechanic on Shorts:
1. **PRE (before kickoff):** "Our AI is calling [Match]. Upset or chalk?" → opens a question.
2. **POST (after the result):** "Did the AI get it right?" → pays it off, and stamps the running record.

Open loop → payoff is what makes people *follow* (subscribe) instead of just watching one clip.

## The franchise that creates subscribers
**"World Cup Report Card"** — a persistent, on-screen running tally the model carries every video:
> 🤖 The Pitch Agent: 9/15 calls correct · Brier 0.21 (beating the coin-flip)

A channel with a *scoreboard that's still being written* is a story people return to. Isolated clips are not. This single recurring element is the difference between views and subscribers. (Data already exists — `pitch_agent/backtest.py` produces these numbers honestly.)

Lean into BOTH outcomes:
- Model right → "Called it. 🤖" (credibility)
- Model wrong → "The AI got cooked 💀" (humility = relatability = comments = reach). A self-aware AI that owns its misses is *more* shareable than one that pretends to be perfect. The accountability ledger (never backfilled) is the brand.

## Format spec (one format, made excellent)
- **Platform priority:** YouTube Shorts FIRST. Don't split focus until it works. Repurpose to TikTok/Reels later (same vertical asset).
- **Length:** 15–25s. One idea per short.
- **Visual:** the single light brand theme (already locked). Big team crests/flags (original vector, not footage), the prediction, the probability bar, the running record. Consistent = recognizable = brand.
- **First 1.5 seconds = the whole game.** Lead with the curiosity gap, not a logo. "Our AI says Spain LOSES today." then explain.
- **Always end with the loop:** "Result drops tonight — follow to see if it nailed it."

## Title / packaging discipline (where most of the views are won)
Formula: **[Stakes/surprise] + [Matchup] + [AI angle]**, curiosity gap, no fluff.
- ✅ "Our AI is calling an upset: Spain vs Morocco 🤖"
- ✅ "The AI went 4/4 yesterday. Today it's scared of this game."
- ❌ "World Cup Matchday 3 Preview" (no curiosity, no stakes)
Thumbnail text (Shorts still shows it in feed/search): ≤4 words, high contrast, one number or one shocked claim.

## Cadence tied to the fixtures (timing is free reach)
- PRE short: **2–3 hours before kickoff** (peak search intent for that fixture).
- POST short: **within ~30 min of full-time** (peak "who won / how" search).
- One running **"Report Card" short** per matchday round-up.
This maps directly onto the existing `matchday_preview` / `match_recap` pillars — we already generate the text; we just need the video + the two-beat scheduling.

## What to STOP doing (focus = saying no)
- Stop spreading the same post across FB + Telegram + X + LinkedIn as the primary play. Pick YouTube Shorts as the growth surface; the others become repurpose targets.
- Don't chase 9 content pillars. Two beats (PRE/POST) + one franchise (Report Card). That's it.
- No highlights, no footage, ever. Original graphics only — it's also our moat.

## Concrete 7-day plan
1. **Day 1:** turn on the POST recap video for every finished match (script exists: `recap_publish.py`). Add the running Report Card line to every video.
2. **Day 2:** add the PRE prediction short (reuse `worldcup_short.py` + the prediction). Schedule 2–3h pre-kickoff off the fixtures table.
3. **Day 3:** ship the title/packaging generator (built tonight — see `promo.py`) into the publish path so every upload gets a curiosity-gap title + thumbnail text.
4. **Day 4–5:** measure with YouTube Studio — retention graph + which titles got impressions→clicks. Keep the top format, kill the rest.
5. **Day 6:** repurpose the 3 best Shorts to TikTok/Reels (only now).
6. **Day 7:** one "Report Card: Group Stage" round-up short — the franchise payoff.

## Success metric (judge honestly, like the model)
Not raw views. Track **subscribers-per-1000-views** and **average-view-percentage** on Shorts. The two-beat loop should lift both. If a format doesn't move those, cut it.

## Built tonight (safe, no publishing)
- `pitch_agent/promo.py` — curiosity-gap **title + thumbnail-text + hook/caption** generator specialized for the prediction-accountability angle, plus the running "Report Card" line from real graded data. Pure text generation; publishes nothing. Tested.
- Decision left to you: wire it + the PRE/POST video scheduling into the football cron (that's outward-facing/live, so it needs your OK).
