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
        "min_words": 800,
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
        "min_words": 800,
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
        "min_words": 800,
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


REGISTRY = {"tutorial": TUTORIAL_FORMATS, "news": NEWS_FORMATS}


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
