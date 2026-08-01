#!/usr/bin/env python3
"""Article format registry — the cure for every post having identical bones.

Before this module, `auto_publish` + `enforce_published_quality` hardcoded ONE
tutorial skeleton and `news_publish` hardcoded ONE news skeleton, and the
quality gates *rejected* anything shaped differently. Every article on the site
came out as the same eight headings with a different noun.

Here each format owns its own angle, title style, section skeleton, and writer
brief. The pipelines pick a format per run (least-recently-used rotation,
persisted in `content/format_history.json`), write to that format, and gate
against *that format's* sections instead of one global template.

Adding a format = adding one dict entry. Nothing else needs to change.
"""
from __future__ import annotations

import json
import os
import random
import re
import datetime

KIT = os.path.expanduser("~/social-media-kit")
HISTORY_PATH = os.path.join(KIT, "content", "format_history.json")

# How many recent runs a format must sit out before it can be picked again.
# Capped in _pick so a small registry can never deadlock.
COOLDOWN = 4

# Hype/filler that reads as AI-written regardless of format. Kept in sync with
# the banned list in agent/prompts.py — the two used to disagree, which is how
# "robust" and "seamlessly" kept reaching published posts.
FORBIDDEN_PHRASES = [
    "revolutionary", "game-changing", "game changer", "cutting-edge",
    "transformative", "industry-leading", "next-generation", "groundbreaking",
    "unprecedented", "world-class", "future-proof", "robust", "seamlessly",
    "seamless", "supercharge", "unlock the power", "dive into", "dive deep",
    "harness the power", "take it to the next level", "in today's fast-paced",
    "time will tell", "stay tuned", "the future looks bright",
    "this changes everything", "exciting times ahead",
]

# Plain-English swap for each banned phrase, so the news lane can repair a draft
# instead of failing the whole run. Every FORBIDDEN_PHRASES entry needs one.
FORBIDDEN_REPLACEMENTS = {
    "revolutionary": "important",
    "game-changing": "important",
    "game changer": "big shift",
    "cutting-edge": "new",
    "transformative": "useful",
    "industry-leading": "widely used",
    "next-generation": "new",
    "groundbreaking": "important",
    "unprecedented": "unusual",
    "world-class": "strong",
    "future-proof": "easier to maintain",
    "robust": "reliable",
    "seamlessly": "without extra work",
    "seamless": "direct",
    "supercharge": "speed up",
    "unlock the power": "get the most out",
    "dive into": "look at",
    "dive deep": "look closely",
    "harness the power": "make use",
    "take it to the next level": "improve it further",
    "in today's fast-paced": "in the current",
    "time will tell": "the practical results still need evidence",
    "stay tuned": "watch the next release notes",
    "the future looks bright": "the useful part depends on real adoption",
    "this changes everything": "this changes the tradeoffs",
    "exciting times ahead": "the next few releases matter",
}


def clean_forbidden(text):
    """Swap banned hype for plain wording (longest phrase first, so multi-word
    entries win over the single words nested inside them)."""
    cleaned = text or ""
    for phrase in sorted(FORBIDDEN_REPLACEMENTS, key=len, reverse=True):
        cleaned = re.sub(re.escape(phrase), FORBIDDEN_REPLACEMENTS[phrase], cleaned, flags=re.I)
    return cleaned


# Title openers that made the archive look like one long listicle. The topic
# picker is told to avoid these outright.
BANNED_TITLE_OPENERS = [
    "building", "implementing", "creating", "mastering", "exploring",
    "getting started", "understanding", "introduction to", "a guide to",
    "the ultimate", "a comprehensive", "how to build", "leveraging",
    "unlocking", "harnessing", "everything you need",
]

# Shared voice for every writer call. Format-specific instructions go in the
# format's own brief.
VOICE = (
    "You are a senior developer writing for the Build With Abdallah blog. Sound like an "
    "experienced software engineer talking to peers — not AI content, not marketing copy, "
    "not a corporate blog, not a docs summary. Clear simple English beats polished prose. "
    "Be specific and a little opinionated: name versions, numbers, file paths, error messages. "
    "Real, complete, copy-pasteable code in fenced blocks with language labels — actual "
    "commands and full files, never prose descriptions of code. State tradeoffs and "
    "limitations honestly, including where the approach is a bad fit. "
    "Never use hype words: revolutionary, game-changing, cutting-edge, transformative, "
    "industry-leading, next-generation, groundbreaking, unprecedented, world-class, "
    "future-proof. Never end with filler like 'Time will tell', 'Stay tuned', 'The future "
    "looks bright', 'This changes everything', or 'Exciting times ahead'. Minimal emojis. "
    "No invented benchmarks, versions, quotes, or dates."
)


# --------------------------------------------------------------------------
# Tutorial formats
# --------------------------------------------------------------------------
# Each entry:
#   angle       — what kind of topic the picker should hunt for
#   title_hint  — how the headline should read
#   sections    — the H2 skeleton the quality gate enforces for THIS format
#   split       — index into `sections` where part A ends and part B begins
#   brief_a/b   — extra instructions for each half of the two-pass writer
#   min_words   — publish floor
#   min_code    — fenced-code-block floor

TUTORIAL_FORMATS = {
    "build_along": {
        "label": "Build-along project",
        "angle": (
            "one specific thing worth building end to end — a small but genuinely "
            "useful working project, not a feature tour"
        ),
        "title_hint": (
            "name the thing being built and the stack, e.g. "
            "'A rate limiter for Laravel queues that survives a restart'"
        ),
        "sections": [
            "## What You'll Build", "## Why This Matters", "## Architecture Overview",
            "## Step-by-Step Implementation", "## Common Mistakes",
            "## How I Would Use This", "## Lessons Learned", "## Next Steps",
            "## Sources",
        ],
        "split": 4,
        "brief_a": (
            "In Step-by-Step Implementation include the first three numbered steps, each "
            "building one real working project with COMPLETE code blocks and a short "
            "explanation under each."
        ),
        "brief_b": (
            "Finish Step-by-Step Implementation with the remaining two or three numbered "
            "steps and complete code. Common Mistakes must be real failure modes with the "
            "actual error text. How I Would Use This covers when to use it, when to avoid "
            "it, and production/cost/maintenance considerations."
        ),
        "min_words": 1100,
        "min_code": 5,
    },
    "debug_story": {
        "label": "Debugging post-mortem",
        "angle": (
            "a specific, reproducible failure mode developers actually hit in production — "
            "a bug, a silent data loss, a timeout, a memory leak, a race condition"
        ),
        "title_hint": (
            "lead with the symptom or the wrong assumption, e.g. "
            "'The queue job that ran twice: Redis locks and the 30-second gap'"
        ),
        "sections": [
            "## The Symptom", "## Reproducing It", "## What I Assumed Was Wrong",
            "## What Was Actually Wrong", "## The Fix", "## Why It Happens",
            "## How To Catch It Earlier", "## Sources",
        ],
        "split": 4,
        "brief_a": (
            "Open with the observable symptom — logs, error text, or the wrong output — "
            "before any explanation. Reproducing It must be a minimal runnable repro the "
            "reader can paste and watch fail. What I Assumed Was Wrong walks the plausible "
            "wrong diagnosis honestly, and shows the check that ruled it out."
        ),
        "brief_b": (
            "What Was Actually Wrong explains the real mechanism (quote docs or source when "
            "the material supports it). The Fix is complete corrected code plus the command "
            "that proves it now passes. How To Catch It Earlier gives a concrete test, "
            "assertion, log line, or monitor — with code."
        ),
        "min_words": 1000,
        "min_code": 5,
    },
    "benchmark": {
        "label": "Measured comparison",
        "angle": (
            "a performance or cost question with a real answer — two approaches to the same "
            "job where the winner is not obvious until measured"
        ),
        "title_hint": (
            "state the question or result, e.g. "
            "'Does Pydantic v2 validation actually cost you anything? I measured it'"
        ),
        "sections": [
            "## The Question", "## How I Measured It", "## The Numbers",
            "## Reading The Results", "## Where It Flips", "## What I'd Actually Ship",
            "## Reproduce This Yourself", "## Sources",
        ],
        "split": 2,
        "brief_a": (
            "The Question states the decision at stake in one paragraph. How I Measured It "
            "gives the complete benchmark script, the hardware/version details, and the "
            "methodology — including what you controlled for and what you did not."
        ),
        "brief_b": (
            "The Numbers presents results as a Markdown table. Label every figure you did "
            "not measure yourself as vendor-reported and attribute it. Where It Flips "
            "identifies the input size or condition that reverses the conclusion. "
            "Reproduce This Yourself is the exact commands to re-run the benchmark."
        ),
        "min_words": 1000,
        "min_code": 4,
    },
    "migration_diary": {
        "label": "Migration diary",
        "angle": (
            "moving a real codebase from one version, library, or platform to another — "
            "where the upgrade guide leaves gaps"
        ),
        "title_hint": (
            "name both sides and the friction, e.g. "
            "'Moving a 40k-line Laravel app to PHP 8.5: the four things that broke'"
        ),
        "sections": [
            "## What I Migrated And Why", "## The Plan", "## What The Upgrade Guide Covers",
            "## What Broke Anyway", "## The Fixes", "## What I'd Do Differently",
            "## Should You Migrate Yet", "## Sources",
        ],
        "split": 4,
        "brief_a": (
            "Describe the starting state concretely — versions, rough size, what the app "
            "does. The Plan is the actual ordered steps with commands. What Broke Anyway "
            "lists each breakage with its real error message."
        ),
        "brief_b": (
            "The Fixes gives complete before/after code for each breakage. Should You "
            "Migrate Yet must give a clear recommendation with the conditions attached — "
            "who should wait, and what signal to wait for."
        ),
        "min_words": 1000,
        "min_code": 5,
    },
    "head_to_head": {
        "label": "Head-to-head decision",
        "angle": (
            "two credible tools or approaches competing for the same job, where the right "
            "pick depends on constraints the docs never mention"
        ),
        "title_hint": (
            "frame it as a decision, not a versus listicle, e.g. "
            "'Meilisearch or Typesense for a 200k-row Laravel app'"
        ),
        "sections": [
            "## The Decision", "## The Test Case", "## Option A In Practice",
            "## Option B In Practice", "## Side By Side", "## Where Each One Wins",
            "## My Rule Of Thumb", "## Sources",
        ],
        "split": 4,
        "brief_a": (
            "The Test Case is one identical task implemented both ways — same data, same "
            "goal. Each 'In Practice' section shows the real setup and working code, "
            "including the parts that were annoying."
        ),
        "brief_b": (
            "Side By Side is a Markdown table across the dimensions that actually decide it "
            "(setup cost, ops burden, failure modes, price at scale) — not a feature "
            "checklist. My Rule Of Thumb must be a one-line decision rule someone can apply "
            "without reading the rest."
        ),
        "min_words": 1000,
        "min_code": 4,
    },
    "from_scratch": {
        "label": "Build a tiny version to understand it",
        "angle": (
            "a piece of magic developers use daily without understanding — reimplemented in "
            "under 150 lines to expose the mechanism"
        ),
        "title_hint": (
            "promise the mechanism, e.g. "
            "'Writing a 120-line dependency injection container to see what Laravel does'"
        ),
        "sections": [
            "## The Magic We're Removing", "## What It Has To Do", "## The Naive Version",
            "## Making It Actually Work", "## Comparing To The Real Thing",
            "## What The Real One Does That Mine Doesn't", "## What This Taught Me",
            "## Sources",
        ],
        "split": 4,
        "brief_a": (
            "Show the familiar magic first as normal usage code. What It Has To Do is the "
            "contract in plain terms. The Naive Version is a genuinely working simplest "
            "implementation, even if it is limited."
        ),
        "brief_b": (
            "Making It Actually Work adds the cases the naive version drops, with complete "
            "code. Comparing To The Real Thing should point at the actual upstream source "
            "file or class name. Be honest and specific about what production handles that "
            "yours does not."
        ),
        "min_words": 1000,
        "min_code": 6,
    },
    "hardening": {
        "label": "Production hardening pass",
        "angle": (
            "taking something that already works in development and listing what it needs "
            "before real traffic touches it"
        ),
        "title_hint": (
            "name the thing and the gap, e.g. "
            "'Nine things your FastAPI service needs before it takes real traffic'"
        ),
        "sections": [
            "## The Starting Point", "## What Breaks Under Load", "## The Checklist",
            "## Working Through It", "## Verifying Each Fix", "## What I'd Skip",
            "## Ongoing Maintenance", "## Sources",
        ],
        "split": 3,
        "brief_a": (
            "The Starting Point is real working-but-naive code. What Breaks Under Load names "
            "concrete failure modes with the symptom each produces. The Checklist is a "
            "numbered list, ordered by what bites first."
        ),
        "brief_b": (
            "Working Through It implements each checklist item with complete code. Verifying "
            "Each Fix gives the command or test that proves it. What I'd Skip must honestly "
            "name items that are cargo-cult for small deployments."
        ),
        "min_words": 1000,
        "min_code": 6,
    },
    "refactor": {
        "label": "Before-and-after refactor",
        "angle": (
            "real code that works but is hard to change, and the specific restructuring that "
            "fixes it without a rewrite"
        ),
        "title_hint": (
            "name the smell and the payoff, e.g. "
            "'Cutting a 400-line controller to 60 without touching a test'"
        ),
        "sections": [
            "## The Code As It Was", "## Why It Hurt", "## The Constraint",
            "## Step By Step Refactor", "## The Code As It Is Now", "## What I Measured",
            "## When Not To Do This", "## Sources",
        ],
        "split": 3,
        "brief_a": (
            "The Code As It Was must be a realistic full example, not a strawman. Why It "
            "Hurt names the concrete cost (the change that took hours, the test that could "
            "not be written). The Constraint states what could not change — usually the "
            "public API or the tests."
        ),
        "brief_b": (
            "Step By Step Refactor makes one behaviour-preserving move at a time with code "
            "at each stage. What I Measured covers lines, cyclomatic complexity, test time, "
            "or whatever is honestly measurable. When Not To Do This must be real."
        ),
        "min_words": 1000,
        "min_code": 5,
    },
}


# --------------------------------------------------------------------------
# News formats
# --------------------------------------------------------------------------
# News is single-pass (`brief`), grounded strictly in fetched source material.

NEWS_FORMATS = {
    "whats_new": {
        "label": "Release analysis",
        "angle": "a concrete release, API change, or platform update developers can act on",
        "title_hint": "name the actual technologies and the change, not 'key announcements'",
        "sections": [
            "## What Happened", "## Why Developers Should Care", "## Real-World Example",
            "## Builder's Take", "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "What Happened: brief factual summary, primary source first.\n"
            "Why Developers Should Care: practical impact, the problem it solves, who "
            "benefits, and the drawbacks.\n"
            "Real-World Example: at least one concrete Laravel, Python, AI, DevOps, "
            "Raspberry Pi, or full-stack example with code.\n"
            "Builder's Take: short and opinionated — what looks useful, what may be hype, "
            "what you would test first, what is still unanswered.\n"
            "What I'll Be Watching: 2-4 specific dates, benchmarks, APIs, or adoption "
            "signals worth monitoring."
        ),
        "min_words": 800,
    },
    "upgrade_impact": {
        "label": "Upgrade impact report",
        "angle": (
            "a release that forces work on existing codebases — breaking changes, "
            "deprecations, security patches with a migration cost"
        ),
        "title_hint": "lead with what it costs the reader, e.g. 'what breaks' or 'who must upgrade'",
        "sections": [
            "## What Changed", "## Who Has To Act", "## What Breaks",
            "## The Upgrade Path", "## If You Can't Upgrade Yet", "## Sources",
            "## What I'll Be Watching",
        ],
        "brief": (
            "Who Has To Act: be specific about versions and configurations affected — say "
            "plainly if most readers are unaffected.\n"
            "What Breaks: itemise each breaking change from the source material only. Never "
            "invent a breakage.\n"
            "The Upgrade Path: the real commands and config diffs from the official notes.\n"
            "If You Can't Upgrade Yet: honest mitigations, or say clearly that there are "
            "none.\n"
            "What I'll Be Watching: follow-up patches or ecosystem support to monitor."
        ),
        "min_words": 800, "min_code": 2,
    },
    "first_look": {
        "label": "Hands-on first look",
        "angle": "something newly available that can be installed and tried today",
        "title_hint": "signal that you actually ran it and what came out",
        "sections": [
            "## What It Is", "## Getting It Running", "## What Worked",
            "## What Didn't", "## Compared To What I Use Now", "## Builder's Take",
            "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "Getting It Running: the real install commands and prerequisites from the "
            "official docs, with version numbers.\n"
            "What Worked / What Didn't: concrete observations only. If the source material "
            "does not support a hands-on claim, describe what the documented behaviour is "
            "and say explicitly that it is documented rather than tested.\n"
            "Compared To What I Use Now: a direct, named comparison to the incumbent tool.\n"
            "Builder's Take: would you adopt it, and what would have to be true first."
        ),
        "min_words": 800, "min_code": 2,
    },
    "claim_check": {
        "label": "Claim versus documentation",
        "angle": (
            "an announcement carrying big performance, capability, or cost claims worth "
            "checking against the actual documentation"
        ),
        "title_hint": "name the claim and that you checked it — never sneering, just precise",
        "sections": [
            "## The Claim", "## What The Documentation Actually Says",
            "## What's Genuinely New", "## What's Marketing", "## What This Means For You",
            "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "The Claim: quote the vendor's own words and attribute them.\n"
            "What The Documentation Actually Says: cite specific docs, changelogs, or "
            "release notes. Every number that came from the vendor must be labelled "
            "vendor-reported.\n"
            "What's Genuinely New: give real credit where the change is substantive.\n"
            "What's Marketing: be factual and fair, not cynical — say what is repackaged or "
            "unproven and why.\n"
            "What This Means For You: concrete guidance for a working developer."
        ),
        "min_words": 800,
    },
    "who_should_care": {
        "label": "Reader triage",
        "angle": (
            "a change whose relevance varies sharply by stack — big for one kind of "
            "developer, irrelevant to another"
        ),
        "title_hint": "name who it's for, so the wrong reader can skip it honestly",
        "sections": [
            "## The Short Version", "## If You Ship Production Services",
            "## If You Build Side Projects", "## If You're Just Watching",
            "## What Nobody Should Do Yet", "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "The Short Version: two sentences, the whole story.\n"
            "Each audience section: what this specific reader should do, concretely, with "
            "a command or config where the source material supports one. If a group is "
            "genuinely unaffected, say exactly that instead of manufacturing relevance.\n"
            "What Nobody Should Do Yet: the premature move people will make anyway — "
            "rewriting on a beta, adopting an unstable API — and why to wait."
        ),
        "min_words": 800,
    },
    "under_the_hood": {
        "label": "How it actually works",
        "angle": (
            "an announcement where the interesting part is the mechanism, not the feature "
            "list — a new algorithm, protocol, caching layer, or execution model"
        ),
        "title_hint": "promise the mechanism, e.g. 'how X actually does Y'",
        "sections": [
            "## What Was Announced", "## The Mechanism", "## Why This Design",
            "## What It Costs", "## Where It Breaks Down", "## Sources",
            "## What I'll Be Watching",
        ],
        "brief": (
            "The Mechanism: explain how it works using only what the docs, spec, or source "
            "actually state. Cite the specific document. If the vendor has not explained "
            "the mechanism, say so plainly rather than speculating about internals.\n"
            "Why This Design: the tradeoff the designers chose, and what they gave up.\n"
            "What It Costs: latency, memory, money, or complexity — attributed.\n"
            "Where It Breaks Down: the workload this design is wrong for."
        ),
        "min_words": 800, "min_code": 2,
    },
    "ecosystem_ripple": {
        "label": "Downstream consequences",
        "angle": (
            "a change at the platform or framework layer that forces work on everything "
            "built on top of it"
        ),
        "title_hint": "lead with the knock-on effect, not the announcement",
        "sections": [
            "## The Change", "## Who Has To Follow", "## What Already Moved",
            "## What's Still Stuck", "## If You Maintain A Package", "## Sources",
            "## What I'll Be Watching",
        ],
        "brief": (
            "Who Has To Follow: name the specific downstream libraries or tools affected, "
            "only where the source material names them.\n"
            "What Already Moved / What's Still Stuck: cite real issues, PRs, or release "
            "notes. Never characterise a maintainer's position without a link.\n"
            "If You Maintain A Package: the concrete steps, with commands.\n"
            "What I'll Be Watching: which downstream release unblocks the rest."
        ),
        "min_words": 800,
    },
    "context": {
        "label": "How we got here",
        "angle": (
            "a change that only makes sense against its history — a reversal, a standard "
            "converging, a long-running argument being settled"
        ),
        "title_hint": "frame the arc or the reversal, not the press release",
        "sections": [
            "## The News", "## How We Got Here", "## What Actually Changed",
            "## Who This Helps", "## The Open Question", "## Builder's Take",
            "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "How We Got Here: only history supported by the source material or that is "
            "uncontroversial public record. Do not invent dates.\n"
            "What Actually Changed: separate the technical substance from the framing.\n"
            "The Open Question: the thing nobody has answered yet, stated precisely.\n"
            "Builder's Take: what a working developer should do this month, if anything."
        ),
        "min_words": 800,
    },
}

# --------------------------------------------------------------------------
# Social post shapes
# --------------------------------------------------------------------------
# Same problem, one layer down: every LinkedIn/Facebook post used to follow the
# identical "Hook / What it covers / Why it matters / Link / Hashtags" skeleton.
# These rotate on the same history mechanism.

SOCIAL_SHAPES = {
    "problem_first": {
        "label": "Problem first",
        "structure": (
            "1) Open with the practical problem the article solves, stated concretely.\n"
            "2) One line on what the article does about it — the value, never the table of contents.\n"
            "3) Why it matters in a real project.\n"
        ),
        "fallback": (
            "Following a tutorial is easy. Knowing when the pattern is worth using is the hard part.\n\n"
            "{value}\n\nThe useful part is understanding the tradeoffs before this reaches production."
        ),
    },
    "one_lesson": {
        "label": "Single takeaway",
        "structure": (
            "1) State ONE opinionated takeaway from the article as a flat claim. No preamble.\n"
            "2) Two sentences of evidence or reasoning for it.\n"
            "3) One line noting the article has the full working detail.\n"
            "Do not summarise the article. The post should stand on its own even unclicked.\n"
        ),
        "fallback": (
            "One thing from this one is worth keeping even if you never read the rest.\n\n"
            "{value}\n\nThat is the part most write-ups skip, and it is the part that decides whether "
            "this survives contact with production."
        ),
    },
    "before_after": {
        "label": "What changed in my workflow",
        "structure": (
            "1) What I used to do, concretely, and what it cost me.\n"
            "2) What I do now instead.\n"
            "3) The one condition where the old way is still correct.\n"
            "Write it as personal experience, first person, no hedging.\n"
        ),
        "fallback": (
            "I used to reach for the obvious approach here and pay for it later in maintenance.\n\n"
            "{value}\n\nThe old way still wins on very small projects. Everywhere else it does not."
        ),
    },
    "common_mistake": {
        "label": "The mistake I keep seeing",
        "structure": (
            "1) Name a specific mistake developers repeatedly make in this area.\n"
            "2) What actually goes wrong when they make it — the symptom, not the theory.\n"
            "3) The correction, in one line.\n"
        ),
        "fallback": (
            "The most common mistake here is treating the happy path as the whole problem.\n\n"
            "{value}\n\nIt works in development and fails the first time real traffic touches it."
        ),
    },
    "concrete_number": {
        "label": "Lead with a number",
        "structure": (
            "1) Open with a specific number, measurement, or version from the article. "
            "Only use a figure that genuinely appears in the article — never invent one. "
            "If the article has no usable number, open with the single most specific fact in it.\n"
            "2) What that number means in practice.\n"
            "3) What you would do with that information.\n"
        ),
        "fallback": (
            "I measured this instead of guessing at it.\n\n{value}\n\nThe numbers matter more than "
            "the framing here — they change which approach is actually cheaper to run."
        ),
    },
    "open_question": {
        "label": "Scenario and a real question",
        "structure": (
            "1) Describe one concrete scenario from the article in two sentences.\n"
            "2) State how you handled it.\n"
            "3) End on a genuine question to other developers about how they handle it — "
            "a real question you would want answered, not engagement bait.\n"
        ),
        "fallback": (
            "A question I have not fully settled.\n\n{value}\n\nI picked one approach, but I am not "
            "certain it is the right call at larger scale. How are you handling this one?"
        ),
    },
}


# --------------------------------------------------------------------------
# Editorial formats (Phase 1) — DORMANT until the approved cadence cutover.
# --------------------------------------------------------------------------
# These belong to the three professional publishing slots and are deliberately
# NOT members of NEWS_FORMATS or TUTORIAL_FORMATS. `pick_format('news')` runs
# live 5x/day on cron and rotates least-recently-used over its table, so
# appending here would change which shape every production post takes today.
#
# The isolation is structural rather than flag-conditional: there is no value of
# EDITORIAL_SLOTS_ENABLED that merges these into a production pool, because they
# are a separate registry kind. See tests/test_editorial_dormancy.py, whose
# expected sequences were captured before this table existed.
#
# Ids are disjoint from every live id. `guided_build` and `ground_up_build` are
# named that way because `build_along` and `from_scratch` are already taken by
# TUTORIAL_FORMATS — a collision would make get()/detect_format() ambiguous.
EDITORIAL_FORMATS = {

    # ── Slot 1: intelligence_brief (08:00) ─────────────────────────────────
    # Deterministic artifacts. Every section is filled from ContentDecision
    # records; the brief text below says which fields, not how to write prose.
    # No LLM narration (resolution 5) — nothing may appear here that is not
    # already in a decision record.
    "intelligence_brief": {
        "label": "SMKit Intelligence Brief",
        "angle": (
            "expose the selection process itself: what was scanned, what was "
            "rejected and why, and which single development won"
        ),
        "title_hint": "name the lead development and the date, not 'daily briefing'",
        "sections": [
            "## What I Scanned", "## What Surfaced", "## What I Rejected",
            "## Duplicates Prevented", "## The Lead Story", "## Why This One",
            "## Confirmed Facts", "## Unverified Or Vendor Claims",
            "## Source Confidence", "## Primary Sources",
        ],
        "brief": (
            "Generated from decision records only. No claim may appear that is "
            "not traceable to a record field.\n"
            "What I Scanned: source names and candidate counts.\n"
            "What Surfaced / What I Rejected: candidate titles with their "
            "rejection reason verbatim from the record.\n"
            "Duplicates Prevented: topics blocked by the duplicate or saturation "
            "check, with which rule fired.\n"
            "The Lead Story / Why This One: the admitted candidate and its "
            "ranking rationale.\n"
            "Confirmed Facts vs Unverified Or Vendor Claims: split strictly by "
            "claim traceability. A vendor statement is never listed as confirmed.\n"
            "Source Confidence: the five components and the total, not just the total.\n"
            "Primary Sources: resolvable URLs only."
        ),
        "min_words": 500,
    },
    "signal_vs_noise": {
        "label": "Signal vs noise",
        "angle": "what cleared the bar versus what looked important and did not",
        "title_hint": "contrast the thing that mattered with the thing that didn't",
        "sections": [
            "## The Signal", "## The Noise", "## How I Told Them Apart",
            "## What I Scanned", "## What I Rejected", "## Duplicates Prevented",
            "## Confirmed Facts", "## Unverified Or Vendor Claims",
            "## Source Confidence", "## Primary Sources",
        ],
        "brief": (
            "Same record set as intelligence_brief, framed as a comparison.\n"
            "The Signal: the admitted candidate.\n"
            "The Noise: the highest-scoring rejected candidates — name them and "
            "give the exact reason each failed.\n"
            "How I Told Them Apart: the threshold that separated them, quoted "
            "with its numeric value.\n"
            "Never imply a rejected item was low quality when it was rejected for "
            "saturation or duplication."
        ),
        "min_words": 500,
    },
    "one_story_that_matters": {
        "label": "One story that matters",
        "angle": "a single development, with the full evidence trail behind it",
        "title_hint": "state the development plainly; no 'the only story you need'",
        "sections": [
            "## The One Story", "## Why It Beat The Rest", "## What I Scanned",
            "## What I Rejected", "## Duplicates Prevented", "## Confirmed Facts",
            "## Unverified Or Vendor Claims", "## Source Confidence",
            "## Primary Sources",
        ],
        "brief": (
            "The narrowest of the three brief shapes: one candidate, examined "
            "closely.\n"
            "The One Story: what happened, from the primary source.\n"
            "Why It Beat The Rest: the score gap to the runner-up, with both "
            "numbers.\n"
            "Everything else as in intelligence_brief. If the lead's confidence "
            "came mostly from corroboration rather than a primary source, say so."
        ),
        "min_words": 500,
    },

    # ── Slot 2: midday_authority — long-form tutorial (Mon/Wed/Fri) ────────
    "tutorial_deep_dive": {
        "label": "Deep-dive tutorial",
        "angle": "one capability taught thoroughly, from first principles to production",
        "title_hint": "name the capability and the end state, not 'a complete guide'",
        "sections": [
            "## What You'll Be Able To Do", "## The Mental Model",
            "## Setting Up", "## The Core Implementation", "## Handling The Edge Cases",
            "## Testing It", "## Taking It To Production", "## What I'd Do Differently",
            "## Sources",
        ],
        "brief": (
            "The Mental Model: explain the underlying idea before any code, so the "
            "reader can adapt it rather than copy it.\n"
            "The Core Implementation: real, runnable code with versions pinned.\n"
            "Handling The Edge Cases: the failures that actually happen — empty "
            "input, auth expiry, rate limits, partial writes.\n"
            "Testing It: an actual test, not a description of testing.\n"
            "Taking It To Production: config, monitoring, and the failure mode you "
            "would page on.\n"
            "What I'd Do Differently: honest limitations of the approach shown."
        ),
        "min_words": 1200,
        "min_code": 5,
    },
    "guided_build": {
        "label": "Guided build",
        "angle": "build one working thing end to end, in order, with the reader following along",
        "title_hint": "name the artifact being built and what it does",
        "sections": [
            "## What We're Building", "## Before You Start", "## Step 1: The Skeleton",
            "## Step 2: Making It Work", "## Step 3: Making It Correct",
            "## Where It Breaks", "## Running The Finished Thing", "## Sources",
        ],
        "brief": (
            "Each step must leave the reader with something that runs. Never show a "
            "step whose output cannot be checked.\n"
            "Before You Start: exact prerequisites with versions.\n"
            "Step 2 vs Step 3: separate 'it works' from 'it is correct' — error "
            "handling and validation belong in step 3, not sprinkled through step 2.\n"
            "Where It Breaks: the mistakes you actually hit building it.\n"
            "Running The Finished Thing: the command and the expected output, "
            "verbatim."
        ),
        "min_words": 1200,
        "min_code": 6,
    },
    "ground_up_build": {
        "label": "Ground-up rebuild",
        "angle": "reimplement something normally taken as given, to show what it does",
        "title_hint": "name the thing being rebuilt and how small the rebuild is",
        "sections": [
            "## What We're Replacing", "## What It Actually Has To Do",
            "## The Smallest Version That Works", "## Making It Honest",
            "## Measuring It Against The Real One", "## What The Real One Earns",
            "## Sources",
        ],
        "brief": (
            "The point is understanding, not replacement. Say so explicitly.\n"
            "What It Actually Has To Do: derive the requirements before writing code.\n"
            "Making It Honest: add the correctness the naive version skipped.\n"
            "Measuring It Against The Real One: real numbers from a real comparison, "
            "or state plainly that you did not measure.\n"
            "What The Real One Earns: end by crediting what the production library "
            "does that the rebuild does not. Never conclude that the toy is enough."
        ),
        "min_words": 1100,
        "min_code": 6,
    },

    # ── Slot 2: midday_authority — technical analysis (Tue/Thu) ────────────
    "technical_analysis": {
        "label": "Technical analysis",
        "angle": "how a system actually works, grounded in its documentation or source",
        "title_hint": "name the system and the specific mechanism examined",
        "sections": [
            "## The Question", "## How It Actually Works", "## Reading The Source",
            "## What The Docs Don't Say", "## What This Means In Practice",
            "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "Every technical claim must be grounded in primary documentation, source "
            "code, repository data, or a reproducible measurement. Cite the file, "
            "section, or commit.\n"
            "Reading The Source: quote the actual code and say where it lives.\n"
            "What The Docs Don't Say: only gaps you verified, never speculation "
            "dressed as insight. If you inferred something, label it an inference.\n"
            "What This Means In Practice: the decision this changes for a reader."
        ),
        "min_words": 900,
        "min_code": 2,
    },
    "architecture_teardown": {
        "label": "Architecture teardown",
        "angle": "the shape of a real system and why it was built that way",
        "title_hint": "name the system and the structural choice under examination",
        "sections": [
            "## The System", "## The Shape Of It", "## The Decision That Drove It",
            "## What It Costs", "## Where It Would Fall Over",
            "## What I'd Borrow", "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "Describe only structure you can evidence from docs, source, or published "
            "design notes. Never reconstruct an architecture from a product page.\n"
            "The Decision That Drove It: the constraint that made this shape "
            "reasonable — not 'best practice'.\n"
            "What It Costs: the concrete tradeoff accepted, in latency, complexity, "
            "or operational burden.\n"
            "Where It Would Fall Over: the load or requirement change that breaks it.\n"
            "What I'd Borrow: the transferable part, scoped to who it suits."
        ),
        "min_words": 900,
    },
    "tradeoff_study": {
        "label": "Tradeoff study",
        "angle": "two defensible options compared on evidence, with the conditions that pick each",
        "title_hint": "name both options and the axis they differ on",
        "sections": [
            "## The Choice", "## Option A", "## Option B", "## How They Compare",
            "## When A Wins", "## When B Wins", "## What Would Change My Mind",
            "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "Both options must be presented as genuinely defensible. A comparison "
            "with a straw man is worthless.\n"
            "How They Compare: measured or documented differences with numbers and "
            "their source. If no measurement exists, say so rather than estimating.\n"
            "When A Wins / When B Wins: name the conditions — team size, scale, "
            "latency budget, existing stack.\n"
            "What Would Change My Mind: the evidence that would flip the "
            "recommendation. Never conclude 'it depends' without saying on what."
        ),
        "min_words": 900,
    },

    # ── Slot 3: practical_takeaway (17:00, Mon–Sat) ────────────────────────
    # Each must deliver at least one of the slot's required_value_any_of
    # categories. These run six days a week, so three shapes is the minimum
    # variation that avoids a visible weekly pattern.
    "takeaway_checklist": {
        "label": "Decision checklist",
        "angle": "turn a development into the specific checks a reader should run",
        "title_hint": "state the decision the checklist resolves",
        "sections": [
            "## What Changed", "## Does This Affect You",
            "## The Checklist", "## How To Verify Each Item",
            "## If You Find A Problem", "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "Delivers: decision_checklist, test_procedure.\n"
            "Does This Affect You: a filter the reader can answer in one minute — "
            "versions, flags, configurations. Say plainly if most readers are "
            "unaffected.\n"
            "The Checklist: numbered, each item independently checkable.\n"
            "How To Verify Each Item: the actual command or query, with the output "
            "that means 'fine' and the output that means 'act'.\n"
            "Must add value beyond the morning brief and midday piece — link them "
            "and state the different angle explicitly."
        ),
        "min_words": 700,
        "min_code": 2,
    },
    "migration_note": {
        "label": "Migration note",
        "angle": "the work a change forces on an existing codebase, and the order to do it in",
        "title_hint": "lead with what must be migrated and roughly what it costs",
        "sections": [
            "## What Forces The Move", "## Who Has To Act", "## The Migration Path",
            "## What Breaks On The Way", "## Rolling Back",
            "## If You're Staying Put", "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "Delivers: migration_advice, compatibility_impact, implementation_guidance.\n"
            "Who Has To Act: exact versions and configurations. Never widen the blast "
            "radius to make the piece feel more urgent.\n"
            "The Migration Path: real commands and config diffs from the official "
            "notes, in execution order.\n"
            "What Breaks On The Way: itemised from source material only — never "
            "invent a breakage.\n"
            "Rolling Back: the actual reverse procedure, or an explicit statement "
            "that rollback is not possible.\n"
            "If You're Staying Put: honest mitigations, or say there are none."
        ),
        "min_words": 700,
    },
    "compatibility_brief": {
        "label": "Compatibility brief",
        "angle": "what a change means for the versions, platforms, and dependencies in use",
        "title_hint": "name the change and the compatibility boundary it moves",
        "sections": [
            "## The Change", "## The Compatibility Matrix", "## What Still Works",
            "## What Stops Working", "## Security And Cost Implications",
            "## What To Do This Week", "## Sources", "## What I'll Be Watching",
        ],
        "brief": (
            "Delivers: compatibility_impact, security_action, cost_implication, "
            "architecture_implication.\n"
            "The Compatibility Matrix: a real table of versions and support status, "
            "sourced. Drop any cell you cannot source — never estimate one.\n"
            "Security And Cost Implications: only where the source material supports "
            "them; omit the section content and say so if it does not.\n"
            "What To Do This Week: one concrete action, scoped to who should take it.\n"
            "Must add value beyond the morning brief and midday piece — link them "
            "and state the different angle explicitly."
        ),
        "min_words": 700,
    },
}

# Once-weekly artifacts generated from records rather than rotated as article
# shapes. Declared here so slot validation can reference them by name; their
# generators land in Stage 7. `github_roundup` reuses the existing roundup
# pillar (scripts/github_roundup.py) rather than a new format.
EDITORIAL_ARTIFACTS = (
    "github_roundup",
    "weekly_trend_analysis",
    "weekly_intelligence_report",
)

REGISTRY = {
    "tutorial": TUTORIAL_FORMATS,
    "news": NEWS_FORMATS,
    # Separate kind on purpose — never merged into the two above.
    "editorial": EDITORIAL_FORMATS,
}


def formats_for(kind):
    try:
        return REGISTRY[kind]
    except KeyError:
        raise ValueError(f"unknown content kind: {kind}")


def get(kind, format_id):
    """Return one format spec, falling back to the registry's first entry."""
    table = formats_for(kind)
    if format_id in table:
        return dict(table[format_id], id=format_id)
    first = next(iter(table))
    return dict(table[first], id=first)


# --------------------------------------------------------------------------
# Rotation history
# --------------------------------------------------------------------------

def load_history():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_history(data):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    tmp = HISTORY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, HISTORY_PATH)


def record(kind, format_id, slug, title=""):
    """Append a run to the history so the next pick can rotate away from it."""
    data = load_history()
    entries = data.get(kind) or []
    entries.append({
        "format": format_id,
        "slug": slug,
        "title": title,
        "date": datetime.date.today().isoformat(),
    })
    data[kind] = entries[-60:]
    _save_history(data)


def recent_formats(kind, n=COOLDOWN):
    entries = (load_history().get(kind) or [])[-n:]
    return [e.get("format") for e in entries if e.get("format")]


def _pick_least_recent(kind, table, exclude=None):
    """Least-recently-used rotation, so consecutive posts never share a shape.

    Options never used before win outright; otherwise the one used longest ago
    wins, with ties broken randomly so the cycle isn't perfectly predictable.
    """
    ids = [f for f in table if f not in (exclude or ())]
    if not ids:
        ids = list(table)

    history = [e.get("format") for e in (load_history().get(kind) or [])]

    # Distance back in history where each option last appeared; unused = infinity.
    def last_used(fid):
        for offset, used in enumerate(reversed(history)):
            if used == fid:
                return offset
        return len(history) + 1

    best = max(last_used(f) for f in ids)
    return random.choice([f for f in ids if last_used(f) == best])


def pick_format(kind, exclude=None):
    return _pick_least_recent(kind, formats_for(kind), exclude)


def pick_social_shape(exclude=None):
    """Rotate the shape of the social post itself, independently of the article."""
    return _pick_least_recent("social", SOCIAL_SHAPES, exclude)


def social_shape(shape_id):
    if shape_id in SOCIAL_SHAPES:
        return dict(SOCIAL_SHAPES[shape_id], id=shape_id)
    first = next(iter(SOCIAL_SHAPES))
    return dict(SOCIAL_SHAPES[first], id=first)


def format_for_slug(kind, slug):
    """Which format a published slug was written to (for the enforcement pass)."""
    for entry in reversed(load_history().get(kind) or []):
        if entry.get("slug") == slug:
            return entry.get("format")
    return None


def detect_format(kind, body):
    """Best-effort format identification from an article's headings.

    Used for posts published before the registry existed, or when the history
    file has been lost.
    """
    headings = {h.strip().lower() for h in re.findall(r"^##\s+.+$", body or "", re.M)}
    best, best_hits = None, 0
    for fid, spec in formats_for(kind).items():
        hits = sum(1 for s in spec["sections"] if s.strip().lower() in headings)
        if hits > best_hits:
            best, best_hits = fid, hits
    # Two matching headings is weak evidence; below that, don't guess.
    return best if best_hits >= 3 else None


# --------------------------------------------------------------------------
# Quality gating
# --------------------------------------------------------------------------

def quality_issues(kind, body, format_id):
    """Gate an article against ITS OWN format, not one global skeleton."""
    spec = get(kind, format_id)
    text = body or ""
    low = text.lower()
    issues = []
    for section in spec["sections"]:
        if section.lower() not in low:
            issues.append(f"missing section: {section}")
    for phrase in FORBIDDEN_PHRASES:
        if phrase in low:
            issues.append(f"forbidden phrase: {phrase}")
    if len(text.split()) < spec.get("min_words", 800):
        issues.append(f"below {spec['min_words']} words")
    if "min_code" in spec and text.count("```") // 2 < spec["min_code"]:
        issues.append(f"fewer than {spec['min_code']} code blocks")
    return issues


# ── substance gate ───────────────────────────────────────────────────────────
#
# quality_issues() above measures SHAPE: sections present, word count, banned
# phrases. A 900-word article of confident generalities passes it exactly as
# well as a 900-word teardown. These checks measure whether the article is
# actually about something — they exist because a piece titled "Python 3.14.6
# Release: Key Security Updates" shipped naming zero CVEs, with the Wikipedia
# page for "Python (programming language)" as its only source.

# Encyclopedic or aggregator hosts. Fine as supporting colour, never as the
# sole authority for a news claim.
BACKGROUND_ONLY_HOSTS = (
    "wikipedia.org", "wikimedia.org", "britannica.com",
    "news.google.com", "reddit.com", "quora.com", "medium.com",
)

# Hosts that publish authoritative vulnerability data.
ADVISORY_HOSTS = (
    "nvd.nist.gov", "cve.org", "cve.mitre.org", "security.snyk.io",
    "ghsa", "security-advisories", "/security/advisories",
    "openssl.org", "kb.cert.org",
)

SECURITY_MARKERS = (
    "security update", "vulnerability", "vulnerabilities", "cve-",
    "exploit", "security fix", "security patch", "security release",
)

# LLM tells the FORBIDDEN_PHRASES list does not catch. Not banned outright —
# any one of them can be legitimate — so this is scored as a density instead.
WEAK_PHRASES = [
    "ever-evolving", "landscape", "it's worth noting", "it is worth noting",
    "promise to redefine", "pivotal", "delve", "myriad", "plethora",
    "in conclusion", "as we move forward", "significant milestone",
    "comprehensive", "empowering", "streamline", "compelling",
    "paradigm", "underscore", "testament", "crucial", "vital",
]
# Calibrated against real output: the worst offender ran 11.5/1000 while sound
# vendor-sourced pieces sat at 4-8. Set to catch the tail, not the median.
MAX_WEAK_PER_1000 = 10

# Distinct source hosts a news article must cite. Measured 2026-08-01: 83% of
# the existing corpus cites exactly one, so raising this to 2 before the writer
# reliably produces two would block most runs. The story picker and writer
# prompts now ask for corroboration; once `sources cited` in the cron log shows
# 2+ consistently, set NEWS_MIN_SOURCES=2 to enforce it.
MIN_SOURCES = int(os.environ.get("NEWS_MIN_SOURCES", "1"))

_URL_IN_MD = re.compile(r"https?://[^\s)\]]+")
_VERSION = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")
_CVE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.I)

# Headlines that promise a shipped artifact. "alpha/beta/preview" are excluded
# deliberately: they appear inside product names ("Realtime API Beta") far more
# often than they announce a release, and matching them read a *deprecation*
# notice as a release story.
RELEASE_TITLE_RE = (r"\brelease[sd]?\b|\blaunch(?:e[sd])?\b|\bship(?:s|ped)?\b"
                    r"|\bnow available\b|\bgenerally available\b|\brolls? out\b")
# A headline about removing something is not a release announcement.
_NOT_A_RELEASE_RE = r"\bdeprecat|\bsunset|\bshut(?:ting)? down\b|\bremov(?:es|ed|ing)\b|\bend of life\b|\bEOL\b"

API_TITLE_RE = r"\bAPI\b|\bSDK\b|\bendpoints?\b"

# A release is often identified by a bare major ("Next.js 15", "Claude Fable 5"),
# which the dotted _VERSION pattern misses. Four-digit numbers are excluded so a
# conference year ("Google I/O 2026") is never mistaken for a version.
_RELEASE_VERSION_RE = re.compile(
    r"\b\d+\.\d+(?:\.\d+)?\b"
    r"|\bv\d+(?:\.\d+)*\b"
    r"|\bversion\s+\d+\b"
    r"|[A-Za-z][A-Za-z.]*\s+(?!\d{4}\b)\d+(?:\.\d+)*\b",
    re.I,
)


def _is_official_source(url, title):
    """The vendor's own channel, or the code host where the artifact lives.

    Deliberately not restricted to ``/docs/`` paths. A vendor's release blog
    (``blog.google``, ``openai.com``) is an official source for its own API, and
    demanding a documentation path rejected fourteen correctly-sourced articles.
    What this still rejects is the aggregator and the unrelated personal blog.
    """
    return _looks_authoritative(_host(url), title)


# Words that can precede "API" without naming one.
_NON_NAMING_WORDS = {
    "the", "this", "that", "these", "those", "a", "an", "its", "our", "their",
    "new", "old", "same", "whole", "entire", "public", "main", "core", "full",
    "one", "another", "each", "every", "any", "some", "such", "both", "his",
    "her", "your", "my", "current", "latest", "existing", "updated", "improved",
}


def _names_an_api(text):
    """Is a concrete API surface named, rather than 'the API' in the abstract?"""
    if "```" in text:                                  # a call you can run
        return True
    if re.search(r"/v\d+[/\w.-]*", text):              # /v1/chat/completions
        return True
    if re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/", text):
        return True
    if re.search(r"\b\w+\([^)]*\)", text):             # someMethod(arg)
        return True
    # "Responses API", "Assistants API" — a proper noun attached to the surface.
    # The leading word must not be a determiner: sentence-initial "The API has
    # been improved" is exactly the vagueness this rule exists to catch.
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9]+)(?:\s+([A-Z][A-Za-z0-9]+))?\s+(?:API|SDK)\b",
                             text):
        lead = (match.group(2) or match.group(1)).lower()
        if lead not in _NON_NAMING_WORDS:
            return True
    return False


def source_urls(body):
    """URLs listed under the article's own ## Sources heading."""
    match = re.search(r"^##\s+Sources\s*$(.*?)(?=^##\s|\Z)", body or "",
                      flags=re.M | re.S)
    if not match:
        return []
    return _URL_IN_MD.findall(match.group(1))


def _host(url):
    return re.sub(r"^www\.", "", (url.split("//", 1)[-1].split("/", 1)[0] or "").lower())


# Subdomains vendors publish their own announcements and docs under.
_OFFICIAL_PREFIXES = ("docs.", "developers.", "developer.", "learn.", "blog.",
                      "blogs.", "devblogs.", "devblog.", "investor.", "press.",
                      "news.", "support.", "help.", "engineering.", "security.",
                      "release.", "releases.", "changelog.", "status.")


# Where software is published and specified. Primary for a release story
# regardless of whether the project name appears in the host.
CODE_AND_SPEC_HOSTS = (
    "github.com", "gitlab.com", "codeberg.org", "sourceforge.net",
    "git.kernel.org", "arxiv.org", "ietf.org", "rfc-editor.org", "w3.org",
    "pypi.org", "npmjs.com", "crates.io", "packagist.org", "hub.docker.com",
)

# Short headline words that carry no brand identity. Without this, prefix
# matching on three letters reads "The new API..." as endorsing theverge.com.
_SHORT_STOPWORDS = {
    "the", "and", "for", "you", "are", "but", "not", "its", "our", "out",
    "can", "get", "has", "was", "who", "why", "how", "all", "one", "two",
    "now", "top", "big", "new", "old", "use", "via", "per", "off", "let",
    "see", "api", "app", "web", "dev", "run", "add", "set", "may", "did",
}

# Labels that carry no identity — never match these against a headline.
_GENERIC_LABELS = {
    "com", "org", "net", "io", "dev", "ai", "co", "uk", "gov", "edu", "app",
    "cloud", "tech", "info", "www", "en",
}


def _looks_authoritative(host, title):
    """Is this host a defensible sole source for the story?

    Three ways to qualify: it is a code/spec host where software is actually
    published; it is the vendor's own channel (``learn.microsoft.com``,
    ``blog.google``); or a label of the host matches a word in the headline — a
    Workday story citing workday.com. What this rejects is the case that
    shipped: a personal blog standing alone behind claims about OpenAI.

    Every label is checked, not just one. Taking a single label read
    ``ai.google.dev`` as "ai" and blocked a Gemini story sourced from Google's
    own developer site.
    """
    if any(bad in host for bad in BACKGROUND_ONLY_HOSTS):
        return False
    if any(host == h or host.endswith("." + h) for h in CODE_AND_SPEC_HOSTS):
        return True
    if host.startswith(_OFFICIAL_PREFIXES):
        return True
    tokens = set(re.findall(r"[a-z0-9]+", (title or "").lower()))
    labels = [l.replace("-", "") for l in host.split(".")
              if l and l not in _GENERIC_LABELS]
    # Long tokens may match loosely (workday → investor.workday.com). Short ones
    # must match a label exactly: "php" is a real vendor token, but substring
    # matching on three letters would read "the" as endorsing theverge.com.
    for label in labels:
        for token in tokens:
            if len(token) >= 4 and (token in label or label in token):
                return True
            if len(token) >= 2 and token not in _SHORT_STOPWORDS and (
                label == token or label.startswith(token)
            ):
                return True
    return False


def substance_issues(title, body):
    """Reasons this article should not go out, beyond its structural shape."""
    text = body or ""
    low = text.lower()
    issues = []

    urls = source_urls(text)
    hosts = {_host(u) for u in urls if u}
    if not urls:
        issues.append("no sources listed")
    elif len(hosts) < MIN_SOURCES:
        issues.append(
            f"cites {len(hosts)} source host(s); NEWS_MIN_SOURCES requires {MIN_SOURCES}"
        )
    else:
        real = {h for h in hosts
                if not any(bad in h for bad in BACKGROUND_ONLY_HOSTS)}
        if not real:
            issues.append(
                "no primary source — only background/aggregator hosts: "
                + ", ".join(sorted(hosts))
            )
        elif not any(_looks_authoritative(h, title) for h in real):
            # One unofficial source is fine alongside a second opinion; alone it
            # is a single unverified voice.
            if len(real) < 2:
                issues.append(
                    f"sole source {', '.join(real)} is neither the vendor nor "
                    "named in the headline; needs corroboration"
                )

    # A security story has to name the thing it is about — but only if it is
    # actually one. A single passing "reduces vulnerabilities" in a model-launch
    # piece held seven unrelated articles to the CVE bar, so the body has to be
    # substantially about security before this applies.
    title_signals = bool(re.search(r"securit|vulnerab|\bcve\b|patch|exploit",
                                   (title or ""), re.I))
    marker_hits = sum(low.count(marker) for marker in SECURITY_MARKERS)
    if title_signals or marker_hits >= 3:
        # Two independent requirements, both necessary.
        #
        # 1. Identify the thing. Not every ecosystem files a CVE promptly, so
        #    the patched version number is an acceptable substitute — but one
        #    of them must be present. Without either, "a security patch was
        #    released" is all the reader gets.
        has_identifier = bool(_CVE.search(text)) or bool(_VERSION.findall(text))
        # 2. Get it from somewhere that would know.
        has_advisory = any(a in u.lower() for u in urls for a in ADVISORY_HOSTS)
        from_authority = has_advisory or any(
            _looks_authoritative(h, title) for h in hosts
        )
        if not has_identifier:
            issues.append(
                "security topic names no CVE and no patched version number"
            )
        elif not from_authority:
            issues.append(
                "security claim rests on no authoritative source or advisory"
            )

    # A version in the headline must be discussed in the body, not just decorate it.
    for version in set(_VERSION.findall(title or "")):
        if version not in text:
            issues.append(f"title claims version {version} but the body never mentions it")

    # A release story must name the exact version and point at the release itself.
    # "Framework 2 is out, here is why it matters" with a link to a marketing
    # page tells a developer nothing they can act on.
    if (re.search(RELEASE_TITLE_RE, title or "", re.I)
            and not re.search(_NOT_A_RELEASE_RE, title or "", re.I)):
        if not _RELEASE_VERSION_RE.search(text):
            issues.append("release story names no exact version number")
        elif not any(_is_official_source(u, title) for u in urls):
            issues.append("release story links no official release source")

    # An API story must name the surface and cite the vendor for it.
    if re.search(API_TITLE_RE, title or "", re.I):
        if not _names_an_api(text):
            issues.append(
                "API story names no specific endpoint, method, or API surface"
            )
        elif not any(_is_official_source(u, title) for u in urls):
            issues.append("API story links no official documentation or vendor source")

    words = max(len(text.split()), 1)
    weak = sum(low.count(p) for p in WEAK_PHRASES)
    per_1000 = weak * 1000 / words
    if per_1000 > MAX_WEAK_PER_1000:
        issues.append(
            f"filler density {per_1000:.1f}/1000 words exceeds {MAX_WEAK_PER_1000} "
            f"({weak} instances)"
        )
    return issues


def outline(spec, start=None, end=None):
    """Render a format's sections as a writer-facing outline."""
    return "\n".join(f"- {s}" for s in spec["sections"][start:end])


def title_rules(spec):
    """Instructions that keep headlines out of the 'Building X with Y' rut."""
    banned = ", ".join(f'"{o}"' for o in BANNED_TITLE_OPENERS)
    return (
        f"Title style for this format: {spec['title_hint']}.\n"
        f"The title MUST NOT start with any of: {banned}. "
        "No colon-subtitle clickbait, no 'A Comprehensive Guide', no year padding. "
        "Prefer a concrete noun, a number, a symptom, or a claim."
    )
