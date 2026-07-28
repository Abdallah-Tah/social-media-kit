# Phase 1 — Professional Publishing Slots: design for review

**Status: DESIGN ONLY. No production code until this is locked.**

Everything here is dormant behind `EDITORIAL_SLOTS_ENABLED=false`. Nothing in this
document changes current production publishing until the final cadence cutover,
which is a separate, approval-gated step.

Terminology note carried from Phase 0.5: the feed's current model
(`kimi-k2.7-code:cloud`) is unpriced, so its cost is reported as
`provider_api_cost: unknown` — never as `$0.00`.

---

## 1. What already exists (compose, do not rebuild)

| Need | Existing module | Phase 1 work |
|---|---|---|
| Domain authority | `agent/feed_authority.py` (`item_authority`, `AuthorityBreakdown`) | Becomes **one component of five** in source confidence |
| Clustering / corroboration | `agent/feed_clustering.py` | Supplies independent-domain counts |
| Opportunity scoring | `agent/feed_opportunity.py` | Feeds candidate ranking, not admission |
| Format registry + LRU rotation + quality gate | `scripts/content_formats.py` | Extended by a **separate** dormant registry |
| Decision ledger | `content/content_decisions.jsonl` (Phase 0) | Becomes the source of truth for saturation |
| Forbidden-phrase blocklist | `content_formats.FORBIDDEN_PHRASES` | Reused — no second blocklist |

Genuinely new: slot policy, source-confidence composition, saturation windows,
publication-readiness records, and the Intelligence Brief artifact.

---

## 2. Module layout

```
config/publishing_slots.yaml     # editable policy — thresholds, schedules, pools
agent/editorial/
    __init__.py
    slots.py                     # loads + validates the YAML into frozen dataclasses
    source_confidence.py         # 5-component explainable score
    editorial_quality.py         # 5-component explainable score (separate concern)
    saturation.py                # windows + material-change classification
    admission.py                 # composes the above into an Admission verdict
    readiness.py                 # PublicationReadiness record -> content_decisions.jsonl
    brief.py                     # SMKit Intelligence Brief assembly
    simulate.py                  # dry full-day schedule runner (shadow mode)
```

`agent/editorial/slots.py` only **loads and validates**. Editable policy lives in
YAML so thresholds can change without a code deploy. There is no
`scripts/publishing_slots.py`.

---

## 3. Final YAML slot schema — `config/publishing_slots.yaml`

```yaml
version: 1

# Master switch. Env EDITORIAL_SLOTS_ENABLED always wins over this value.
# MUST remain false until the approved cadence cutover.
enabled: false

# Shadow mode runs the complete decision pipeline and writes decision records
# and brief artifacts, but never publishes and never touches live rotation
# history. This is what produces the required full-day simulation.
shadow_mode: false

timezone: America/New_York

# ── Policy shared by every slot unless a slot overrides it ──────────────────
defaults:
  fallback:
    max_backup_candidates: 5      # ranked candidates evaluated after the lead
    on_no_candidate: skip_slot    # never relax thresholds to fill the schedule
    record_rejections: true       # every rejection reason is persisted

  saturation:
    rolling_days: 14
    recent_items: 12
    max_entity_share_recent: 0.25 # >25% of last 12 items = entity is saturated
    # A saturated entity is still admissible when the development_type is
    # material (see section 6). Saturation never rejects on entity alone.
    material_types_always_allowed: true

  claims:
    # Vendor/first-party claims must be labelled, not silently presented as fact.
    require_claim_labelling: true
    label_unverified_as: "unverified or vendor-provided"

  limits:
    linkedin_per_day: 1           # per slot; total 3/day after cutover

# ── Slots ───────────────────────────────────────────────────────────────────
slots:

  intelligence_brief:
    order: 1
    publish_at: "08:00"
    label: "SMKit Intelligence Brief"
    purpose: >
      Expose SMKit's intelligence process and select the highest-value
      development from the previous 24 hours.

    lookback_hours: 24

    format_pool:
      - intelligence_brief
      - signal_vs_noise
      - one_story_that_matters

    # Sections the artifact MUST contain. Missing section = not publishable,
    # regardless of scores.
    required_sections:
      - sources_scanned
      - opportunities_discovered
      - opportunities_rejected
      - duplicates_prevented
      - selected_lead_opportunity
      - selection_rationale
      - confirmed_facts
      - unverified_or_vendor_claims
      - source_confidence_score
      - primary_sources

    admission:
      source_confidence_min: 75
      editorial_quality_min: 75
      # Either an official primary source, or >= 2 independent credible sources.
      evidence:
        require_any_of:
          - primary_source: true
          - independent_sources_min: 2
      duplicate_policy: reject_unchanged_topic

  midday_authority:
    order: 2
    publish_at: "12:00"
    label: "Midday Authority"

    # Day-of-week content type. Each type maps to its own format pool.
    weekly_schedule:
      monday:    long_form_tutorial
      tuesday:   technical_analysis
      wednesday: long_form_tutorial
      thursday:  technical_analysis
      friday:    long_form_tutorial
      saturday:  github_roundup
      sunday:    weekly_trend_analysis

    format_pool_by_type:
      long_form_tutorial:    [tutorial_deep_dive, build_along, from_scratch]
      technical_analysis:    [technical_analysis, architecture_teardown, tradeoff_study]
      github_roundup:        [github_roundup]          # single, existing pillar
      weekly_trend_analysis: [weekly_trends, signal_review]

    admission:
      source_confidence_min: 70
      editorial_quality_min: 80
      require_practical_developer_value: true
      # Technical claims must be grounded in verifiable material.
      grounding:
        require_any_of:
          - primary_documentation
          - source_code
          - repository_data
          - reproducible_evidence
      duplicate_policy: reject_unchanged_topic

  practical_takeaway:
    order: 3
    publish_at: "17:00"
    label: "Practical Takeaway"

    weekly_schedule:
      monday:    practical_takeaway
      tuesday:   practical_takeaway
      wednesday: practical_takeaway
      thursday:  practical_takeaway
      friday:    practical_takeaway
      saturday:  practical_takeaway
      sunday:    weekly_intelligence_report

    format_pool_by_type:
      practical_takeaway:         [takeaway_checklist, migration_note, compatibility_brief]
      weekly_intelligence_report: [weekly_intelligence_report]

    # At least one of these must be present, or the draft adds no value.
    required_value_any_of:
      - test_procedure
      - implementation_guidance
      - compatibility_impact
      - migration_advice
      - architecture_implication
      - security_action
      - cost_implication
      - decision_checklist

    admission:
      source_confidence_min: 65
      editorial_quality_min: 75
      require_actionable_value: true

      # Reusing a topic already published earlier the same day is allowed only
      # under all three conditions. Any one missing = reject.
      same_day_reuse:
        allowed: true
        require_all_of:
          - explicit_link_to_earlier_item
          - materially_different_practical_angle
          - passes_saturation_and_duplicate_independently
```

### Validation rules enforced at load

1. Every `format_pool` / `format_pool_by_type` id must exist in the dormant
   editorial registry (section 7). Unknown id = hard failure at load, not at
   publish time.
2. Every weekday key must be present for a slot that declares `weekly_schedule`.
3. `publish_at` values must be unique and ordered consistently with `order`.
4. Any pool used on more than one weekday must hold **>= 2** formats, or the
   slot repeats its shape every occurrence. (`github_roundup` and
   `weekly_intelligence_report` are exempt — once weekly.)
5. Thresholds must be `0 <= x <= 100`.

---

## 4. Source confidence (0–100) — about the *evidence*

Deterministic, no LLM. Returns a `SourceConfidence` with a per-component
breakdown, mirroring the existing `AuthorityBreakdown` pattern.

| Component | Max | Rule |
|---|---:|---|
| `primary_source_availability` | 30 | official docs / changelog / repo / RFC = 30; official vendor blog = 24; press release = 18; none = 0 |
| `independent_corroboration` | 25 | distinct registrable domains in the story cluster: 1 → 0, 2 → 15, 3 → 21, 4+ → 25 |
| `domain_authority` | 20 | `feed_authority.item_authority()` normalized to 0–20 |
| `recency` | 15 | <6h = 15, <24h = 12, <72h = 7, <168h = 3, else 0 |
| `claim_traceability` | 10 | `10 × (claims with a resolvable source URL ÷ total extracted claims)`; 0 claims extracted → 0 |

```
source_confidence = sum(components)          # 0–100, integer
```

Deliberate consequences:
- A single high-authority outlet with no primary source and no corroboration
  tops out at **35+15 = 50** — below every slot's floor. Rewriting one
  publication's scoop cannot pass admission on its own.
- An official vendor changelog alone scores **30 + 0 + auth + recency + trace**,
  which can clear 65–75. That is intended: primary sources are the point.

Vendor-provided claims are **labelled, not scored away** — `claim_traceability`
measures whether a claim is traceable, and the Intelligence Brief separates
`confirmed_facts` from `unverified_or_vendor_claims`.

---

## 5. Editorial quality (0–100) — about the *draft*

Kept strictly separate from source confidence: they fail for different reasons
and must be independently diagnosable. Deterministic in Phase 1 (an LLM judge is
a possible Phase 3 addition, deliberately not now — it would add per-draft cost
to every slot).

| Component | Max | Rule |
|---|---:|---|
| `format_conformance` | 25 | starts at 25; −5 per issue from the existing `content_formats.quality_issues(kind, body, format_id)` |
| `specificity` | 20 | density of versions, numbers, API/symbol names, and named entities per 100 words, scaled and capped |
| `actionability` | 20 | fraction of the slot's `required_value_any_of` categories detected; 0 categories = 0 |
| `structure` | 15 | required H2s present, `## Sources` present, no section shorter than a minimum, balanced section lengths |
| `language_discipline` | 20 | starts at 20; −4 per `FORBIDDEN_PHRASES` hit; − hype-ratio penalty; − penalty for low sentence-length variance |

```
editorial_quality = sum(components)          # 0–100, integer
```

`format_conformance` reuses `quality_issues()` rather than reimplementing it, so
the existing per-format gate stays the single definition of format correctness.

---

## 6. Saturation

### Source of truth

**No independent authoritative store.** `content/topic_saturation.json` is *not*
created. Saturation is derived from:

1. `content/content_decisions.jsonl` — append-only decision records (Phase 0)
2. Published-content history — `content/format_history.json`, the sitemap, and
   `content/*_posted.json`

A derived index at `content/feed/.saturation_index.json` is a **cache only**:

- rebuildable at any time via `smkit editorial rebuild-saturation`
- carries a `source_fingerprint` = (decision-record count, last decision ts,
  published-item count, last published slug)
- on fingerprint mismatch it is **discarded and rebuilt**, never reconciled
- a corrupt or missing cache is a rebuild, never an error

This makes drift structurally impossible: the cache can only ever be a
projection of the records.

### Windows

Both are evaluated; a topic must pass **both**.

- **Rolling 14 days** — entity/development history for material-change detection
- **Most recent 12 published items** — near-term repetition and share

### Classification

Each candidate resolves to `(subject_entity, development_type)`.

`MATERIAL_DEVELOPMENT_TYPES` — a new instance of any of these is materially new
even when the entity was covered very recently:

```
new_model            api_availability      pricing_change
version_release      security_issue        benchmark_publication
licensing_change     technical_documentation
deployment_availability                    compatibility_change
```

Everything else (`commentary`, `opinion`, `recap`, `rumor`) is **non-material**.

### Rules

```
R1  REJECT if (subject_entity, development_type) already appears in the
    rolling 14-day window AND development_type is non-material.
        -> the same take on the same thing, twice

R2  ALLOW if subject_entity appeared recently but development_type is
    material AND that (entity, type) pair is not already in the 14-day window.
        -> "OpenAI again" is not a rejection reason

R3  REJECT if subject_entity share of the last 12 published items > 0.25
    AND development_type is non-material.
        -> caps commentary volume without blocking real news

R4  NEVER reject on subject_entity recency alone. R4 overrides R1 and R3
    whenever development_type is material and the pair is new.

R5  Same-day reuse (practical_takeaway only) additionally requires all three
    conditions in `same_day_reuse.require_all_of`.
```

`saturation_score` (0–100, higher = more saturated) is reported for
explainability, but admission is decided by R1–R5, not by a threshold on the
score. A score alone would reintroduce exactly the "company was covered
recently" rejection the rules exist to prevent.

---

## 7. Feature-flag activation design

### Resolution

```
EDITORIAL_SLOTS_ENABLED   env  >  config/publishing_slots.yaml `enabled`  >  False
EDITORIAL_SLOTS_SHADOW    env  >  config/publishing_slots.yaml `shadow_mode` > False
```

Env wins so the flag can be flipped without a commit, matching the
`FEED_LLM_*` precedence established in Phase 0.5.

### The dormancy requirement (constraint 6)

Adding formats must not change live format selection while the flag is false.
`content_formats.pick_format('news')` rotates LRU over `NEWS_FORMATS`, so
appending new entries there would immediately alter live selection.

**Therefore new formats go in a separate registry**, not in `NEWS_FORMATS`:

```python
EDITORIAL_FORMATS = { ... }        # new, dormant

def formats_for(kind, include_editorial=None):
    if include_editorial is None:
        include_editorial = editorial_slots_enabled()
    ...
```

Guaranteed by test, not by inspection:

- `formats_for('news')` with the flag false returns **exactly** the existing 5
  ids in the existing order
- `pick_format('news')` produces an identical sequence with the flag false,
  pinned against a recorded baseline
- `EDITORIAL_FORMATS` ids are disjoint from `NEWS_FORMATS`/`TUTORIAL_FORMATS`

Shadow runs write rotation history to `content/format_history.simulated.json`,
never `content/format_history.json`, so a simulation cannot perturb live
rotation. Same for decision records: shadow records carry `"mode": "shadow"` and
are excluded from saturation windows.

### Stages

| Stage | Flag | Shadow | Cron | Effect |
|---|---|---|---|---|
| 0 — merged dormant | false | false | 5×/day | **Zero** behavior change, test-enforced |
| 1 — shadow | false | true | 5×/day | Full pipeline runs, publishes nothing, emits the full-day simulation |
| 2 — cutover | true | false | 3×/day | Live. Requires approval |

### Cutover preconditions (all required before touching cron)

1. Complete Phase 1 test suite green
2. At least one full-day simulated schedule showing **every** candidate, score,
   decision, and resulting artifact for all three slots
3. Skipped-slot behavior demonstrated (a slot with no passing candidate)
4. No duplicate publishing across the three slots
5. Explicit approval

Cutover changes, all in one reviewable commit: crontab 5 → 3 entries at
08/12/17 America/New_York, `linkedin_policy.DAILY_LIMITS` news 5 → 3, and the
CLAUDE.md cadence section.

### Rollback

Before cutover: set the flag false — instant, no revert needed.
After cutover: restore the crontab entries and set the flag false. The 5×/day
lane is untouched code the whole time, so rollback is configuration, not a
code revert.

---

## 7a. Known limitation — relationship detection depends on excerpt richness

Recorded deliberately rather than fixed now. Fuller excerpt fetching and ingestion
changes are **out of scope**; the current behaviour is the safe fallback and the gap
is to be *measured* during historical replay and shadow mode before anything changes.

Stage 2.6 classifies source relationships from `SourceRef.excerpt`. Feed items today
carry short summaries, so in production the syndication and restatement paths will
fire less often than in tests and more sources will land in `relationship_unknown`.
That errs in the safe direction — an unknown source keeps the benefit of the doubt
and is not excluded from corroboration — but it does mean corroboration stays
somewhat generous until excerpts get richer.

### Observability requirements (to build later, not now)

No dashboard panels are to be implemented yet. The requirement on Stage 3 and the
replay records is only that they **retain enough raw information to derive** these:

| Metric | Derived from |
|---|---|
| `relationship_unknown_rate` | `relationship_unknown_count` / `source_count` |
| `relationship_unknown_rate_by_domain` | `relationship_unknown_by_domain` |
| `relationship_unknown_rate_by_source_kind` | `relationship_unknown_by_source_kind` |
| `relationship_unknown_rate_by_lane` | above, grouped by the record's `slot` |
| `excerpt_presence_rate` | `excerpt_present_count` / `source_count` |
| `excerpt_length_distribution` | `excerpt_length_buckets` |
| source-confidence impact of unknowns | `source_confidence_score`, `corroboration_score` alongside the counts |

`saturation.relationship_observability(candidate, relationships, source_confidence)`
emits exactly these, and `SaturationResult.observability` carries them through when
passed in. **Raw counts only, never rates** — a rate is a property of a run, and
computing it per candidate would give a denominator of 1.

The same block also retains what the saturation metrics need:
`saturation_rejection_rate` and `saturation_rejections_by_rule` from `rule_statuses`
and `rejecting_rules`; `most_saturated_entities` / `most_saturated_themes` from
`entity` and `theme`; `material_exception_rate` from `material_exception_applied`;
`exact_topic_repeat_rate` from `exact_topic_repeat`.

## 8. Open questions for review

1. **Timezone vs cron.** Slots are declared in `America/New_York`; the host
   crontab is machine-local. Confirm the Pi's local time is Eastern, or the
   cutover needs `CRON_TZ`.
2. **`midday_authority` Saturday** puts `github_roundup.py` on cron for the
   first time. Confirm that is intended.
3. **Format authoring.** The pools above name 12 format ids that do not exist
   yet. They need writing (angle, title style, H2 skeleton, writer brief) before
   Stage 1 can produce real drafts.
4. **Sunday doubles up** — `weekly_trend_analysis` at 12:00 and
   `weekly_intelligence_report` at 17:00. Confirm both are wanted, and that
   their scopes are distinct enough to survive the duplicate check.
5. **Cost.** Sections 4–6 are deterministic and add no LLM calls. Only the
   Intelligence Brief narration would use one (~1/day), instrumented through
   `llm_ops.chat()` with `job_id="editorial_brief"` so it stays separable.
   Confirm that is acceptable, or the brief can be fully templated.
