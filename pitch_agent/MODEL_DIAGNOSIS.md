# Pitch Agent — prediction model diagnosis & fix plan
_Written overnight 2026-06-14. Nothing live was changed. All edits are default-off or read-only._

## TL;DR
The model isn't "wrong" so much as **structurally unable to predict draws**, and we **grade/present it in a way that makes an honest forecast look broken**. Current public record (2/4) is within pure noise at n=4 — there is not enough data to "tune" anything yet, and tuning to 4 games would be overfitting. I fixed the one *principled* flaw (draw under-count) in a way that is OFF by default, and built the honest scoreboard so we can decide with evidence as the group stage fills in.

## What the data actually shows (read-only, ledger untouched)
4 finished matches, 4 graded predictions:

| Match | Actual | Predicted (argmax) | Probs H/D/A | Result |
|---|---|---|---|---|
| Canada vs Bosnia | 1-1 (draw) | home | .58/.23/.19 | ✗ |
| USA vs Paraguay | 4-1 (home) | home | .40/.26/.34 | ✓ |
| Korea vs Czechia | 2-1 (home) | away | .35/.28/.38 | ✗ |
| Mexico vs S.Africa | 2-0 (home) | home | .63/.22/.15 | ✓ |

- Outcome accuracy 2/4 = 50%. Avg 3-class Brier ≈ 0.59, log-loss ≈ 0.97.
- **Predicted draws: 0/4. Actual draws: 1/4.** Both losses involve the draw blind spot: one was an actual draw (Canada-Bosnia), the other a near-coin-flip the model leaned the wrong way by 3 pts (Korea-Czechia .35/.38).

## ⚡ Real-tournament evidence (updated 2026-06-14, 8 games in)
Of the **8 finished World Cup matches so far, 3 were draws = 38%** (Canada-Bosnia, Qatar-Switzerland, Brazil-Morocco). The live model's argmax predicts a draw **0% of the time**, so it is structurally blind to ~38% of actual results. This is no longer a theoretical concern at n=4 — it's the dominant, most-fixable error source. It is the strongest argument for enabling the draw handling below.

## Root cause #1 — the model can never say "draw"
Independent Poisson under-counts draws. Even at perfectly even xG (1.2 vs 1.2):
`Home .362 / Draw .276 / Away .362` → 1-1 is the single most likely **scoreline**, but "draw" is never the **argmax of the 3-way split**. WC group draws run ~25-30%, so we eat a guaranteed wrong label on every drawn game.

**Fix (done, OFF by default): Dixon-Coles low-score correction** in `poisson.py`.
`scoreline_distribution / top_scorelines / match_outcome_probs` now take `rho` (default `0.0` = identical to the old model — verified byte-for-byte). A small negative rho lifts 0-0 and 1-1:
- rho 0.00: even game draw = .276
- rho -0.10: draw = .303
- rho -0.15: draw = .316

This improves **probability calibration** (Brier/log-loss on drawish games). It does NOT, by itself, make argmax output "draw" — see #2.

## Root cause #2 — we grade/present probabilities as binary right/wrong
Argmax is mathematically optimal for raw hit-rate, so it will *correctly* keep under-predicting draws. The problem is that publishing "Predicted: Home win → ✗" on a 41/27/31 game frames a well-calibrated forecast as a failure. A forecaster should be judged on **calibration (Brier/log-loss) vs a baseline**, and present **confidence tiers**, not coin-flip verdicts.

**Recommended (NOT yet wired — needs your OK because it changes public text + the record):**
1. Confidence tiers in the preview/recap copy:
   - top prob ≥ ~0.50 → "Pick: X"
   - 0.40-0.50 → "Lean X"
   - top two within ~6 pts → "Toss-up (X / Y)"
   (The football pipeline already says "Lean" in places — make it consistent and threshold-driven.)
2. Public scoreboard leads with **calibration vs baselines** ("our probabilities beat always-favorite / coin-flip") instead of a noisy "2/4". Keep the hit-rate as a secondary line.
3. When we flip Dixon-Coles on, **bump MODEL_VERSION** (e.g. 1.1.0 → 1.2.0, label "Pitch Model v1.2 — draw-calibrated"). The v1.1 record stays as-is (honest); v1.2 starts a clean ledger. This respects the never-backfill accountability rule.

## Root cause #3 — Elo→xG compression (lower priority, do NOT tune yet)
`elo_to_xg` maps expected score linearly to xG (`0.4 + 1.6*e`). It's serviceable but compresses favorites (a 200-pt gap → only ~1.44 vs 0.96 xG). A cleaner, more interpretable replacement is a **supremacy model**: pick a WC group total-goals prior (~2.6) and split it by an Elo-derived supremacy, with explicit host-nation HFA. **Deferred on purpose** — changing this is a calibration choice and we have n=4. Revisit once ~16-24 group games are graded, using the harness below.

## How we'll decide with evidence (not vibes)
`pitch_agent/backtest.py` (read-only, never writes the ledger) reports, over all graded predictions:
- outcome accuracy, 3-class Brier, log-loss
- draw calibration (mean predicted draw prob vs actual draw rate)
- comparison vs baselines: always-favorite, always-home, uniform 1/3
As the group stage fills in, this tells us honestly whether Dixon-Coles (and later a supremacy Elo→xG) actually improves the forecast before anything goes live.

## Status
- [x] Dixon-Coles implemented, default-off, default verified identical to old model.
- [x] Diagnosis written.
- [x] Read-only backtest/calibration harness (`backtest.py`).
- [x] **SHIPPED 2026-06-14 (Abdallah approved): model v1.2** — Dixon-Coles `DRAW_RHO=-0.13` + draw-aware decision `DRAW_PREF_EPS=0.06` live in `content.py` + `predict` CLI. MODEL_VERSION 1.1.0→1.2.0 (record reset honestly; old v1.1 record preserved). Even matches now predict "draw"; display shows "Lean: Draw … too even to split". 169 tests pass.
- [ ] (Deferred) supremacy Elo→xG once data supports it — tune `DRAW_RHO`/`DRAW_PREF_EPS` via `backtest.py` as the group stage fills in.
