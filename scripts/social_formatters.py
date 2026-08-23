#!/usr/bin/env python3
"""Platform-specific rendering for ranked social posts.

The data model here is platform-neutral: `RoundupContent` holds the repositories,
the totals, and the prose fragments. The formatters below turn it into a LinkedIn
post or an X thread. Nothing in this module talks to an API — publishing stays in
`linkedin_org_poster` / `x_poster` / `fb_poster`.

    scrape → collect → build_roundup_content → LinkedInRoundupFormatter → post_org
                                             → XRoundupFormatter       → post_thread

Every number a reader can check — rank, star delta, total, repository count — is
computed here in Python. The model is only ever asked for prose (hook, intro,
one-line summaries, observations, CTA), and its output is discarded if it fails
validation. Asking an LLM to add up star counts is how a post ends up claiming a
total that does not match the list printed directly beneath it.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from dataclasses import dataclass, field
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

X_LIMIT = 280

# Hooks rotate by ISO week so consecutive roundups do not open identically, even
# when the LLM is unavailable and the deterministic path renders the post.
_FALLBACK_HOOKS = (
    "🚀 These open-source projects are moving fast on GitHub this week.",
    "Open source had another busy week on GitHub.",
    "🚀 A few open-source projects pulled serious attention this week.",
    "These are the repositories developers starred most this week.",
    "🚀 Open source is moving fast this week.",
)

_FALLBACK_CTAS = (
    "Which project are you already using — and which one should I test next?",
    "Which of these are you running already? And which should I try first?",
    "Anything here you have shipped with? Tell me which one to test next.",
)

_HASHTAGS = "#OpenSource #GitHub #DeveloperTools #SoftwareEngineering"

# Language → the phrase used when describing what kind of week it was. Derived
# from the dataset, never asserted without a repo behind it.
_CATEGORY_HINTS = (
    ("self-hosted software", ("self-host", "selfhosted", "self hosted", "homelab")),
    ("AI and LLM tooling", ("ai", "llm", "gpt", "agent", "rag", "model", "prompt")),
    ("developer tooling", ("cli", "sdk", "framework", "editor", "compiler", "devtool")),
    ("automation platforms", ("automation", "workflow", "n8n", "orchestrat", "pipeline")),
    ("infrastructure", ("kubernetes", "docker", "server", "database", "proxy")),
    ("learning resources", ("awesome", "curated", "collection", "guide", "roadmap", "book")),
)

# GitHub descriptions are written for a repo page, not a feed: many open with a
# decorative emoji, and some carry a parenthetical maintainer note that reads as
# noise once the description is quoted out of context.
_LEADING_EMOJI_RE = re.compile(r"^(?:[\U0001F000-\U0001FAFF←-⯿️‍]+\s*)+")
_BRACKET_NOTE_RE = re.compile(r"\s*[\[(](?:NOTE|note)\b[^\])]*[\])]")


def clean_description(text: str) -> str:
    """Normalise a scraped repository description for use as a summary."""
    text = " ".join((text or "").split())
    text = _BRACKET_NOTE_RE.sub("", text)
    text = _LEADING_EMOJI_RE.sub("", text)
    # GitHub truncates long descriptions with a literal ellipsis; a trailing "…"
    # in the middle of a post reads as our own truncation bug. A full stop is
    # ordinary punctuation and must survive.
    return text.rstrip("…").strip()


# ── Platform-neutral content model ──────────────────────────────────────────

@dataclass
class RepoEntry:
    """One ranked repository. `rank` and `weekly_stars` are computed, never LLM."""
    rank: int
    name: str
    full_name: str
    url: str
    weekly_stars: int
    description: str = ""
    language: str = ""
    stars: int = 0
    topics: list = field(default_factory=list)


@dataclass
class RoundupContent:
    entries: list
    total_stars: int
    count: int
    topic: str
    label: str
    article_url: str = ""
    hook: str = ""
    intro: str = ""
    observations: list = field(default_factory=list)
    cta: str = ""

    def headline(self) -> str:
        """The one line that must agree with the list beneath it."""
        noun = "project" if self.count == 1 else "projects"
        return (f"{self.count} {noun} gained {self.total_stars:,} GitHub stars "
                f"in just 7 days.")


def _valid_url(url: str) -> bool:
    """Only absolute http(s) URLs reach a post; a broken link is worse than none."""
    if not url or not isinstance(url, str):
        return False
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _week_index() -> int:
    return datetime.date.today().isocalendar()[1]


def build_roundup_content(items, article_url="", topic="all", label="",
                          use_llm=True, model="gpt-4o-mini") -> RoundupContent:
    """Normalise scraped rows into ranked, de-duplicated, totalled content.

    Dropped here rather than rendered: repositories with no usable URL, and
    duplicates of a `full_name` already seen (GitHub's trending page can repeat
    a row across paginated scrapes, which would double-count the total).
    """
    seen, cleaned = set(), []
    for it in items or []:
        full_name = (it.get("full_name") or "").strip()
        url = (it.get("url") or "").strip()
        if not _valid_url(url):
            continue
        key = full_name.lower() or url.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(it)

    cleaned.sort(key=lambda i: int(i.get("weekly_stars") or 0), reverse=True)

    entries = [
        RepoEntry(
            rank=rank,
            name=(it.get("name") or it.get("full_name") or "").strip(),
            full_name=(it.get("full_name") or "").strip(),
            url=it["url"].strip(),
            weekly_stars=int(it.get("weekly_stars") or 0),
            description=clean_description(it.get("description")),
            language=(it.get("language") or "").strip(),
            stars=int(it.get("stars") or 0),
            topics=list(it.get("topics") or []),
        )
        for rank, it in enumerate(cleaned, 1)
    ]

    content = RoundupContent(
        entries=entries,
        total_stars=sum(e.weekly_stars for e in entries),
        count=len(entries),
        topic=topic,
        label=label or "open-source",
        article_url=article_url if _valid_url(article_url) else "",
    )
    _apply_prose(content, use_llm=use_llm, model=model)
    return content


# ── Prose: LLM with a deterministic floor ───────────────────────────────────

def _categories(content: RoundupContent) -> list:
    """Which categories the dataset actually contains — no invented trends."""
    blob = " ".join(
        f"{e.full_name} {e.description} {' '.join(e.topics)}".lower()
        for e in content.entries
    )
    return [name for name, keys in _CATEGORY_HINTS if any(k in blob for k in keys)]


def _fallback_intro(content: RoundupContent) -> str:
    # Three named categories reads as an observation; six reads as a tag dump.
    cats = _categories(content)[:3]
    if not cats:
        return ("Here are the repositories developers are paying attention to "
                "right now.")
    subject = cats[0] if len(cats) == 1 else ", ".join(cats[:-1]) + f" and {cats[-1]}"
    # Only uppercase the first letter — .capitalize() would lowercase the rest
    # and turn "AI and LLM tooling" into "Ai and llm tooling".
    subject = subject[0].upper() + subject[1:]
    return (f"{subject} led the week. Here are the repositories developers are "
            f"paying attention to right now.")


def _fallback_observations(content: RoundupContent) -> list:
    if not content.entries:
        return []
    top = content.entries[0]
    out = [
        f"{top.name} led the week at +{top.weekly_stars:,} stars. A seven-day "
        f"spike measures attention, not durability — the number worth watching "
        f"is whether the contributor count holds up a month from now."
    ]
    langs = [e.language for e in content.entries if e.language]
    if langs:
        top_lang = max(set(langs), key=langs.count)
        share = langs.count(top_lang)
        if share > 1:
            out.append(f"{top_lang} shows up in {share} of the {content.count} "
                       f"projects on this list.")
    return out[:3]


_PROSE_SCHEMA = {
    "hook": "one short attention-grabbing line, max 90 characters",
    "intro": "1-2 sentences describing what the reader is looking at",
    "observations": "1-3 short strings, each an observation supported by the data",
    "cta": "one closing question inviting replies",
    "summaries": "object mapping full_name to a one-sentence plain summary",
}


def _prose_prompt(content: RoundupContent) -> str:
    repos = [
        {
            "rank": e.rank,
            "name": e.name,
            "full_name": e.full_name,
            "description": e.description,
            "language": e.language,
            "stars_gained": e.weekly_stars,
            "stars_total": e.stars,
            "topics": e.topics,
        }
        for e in content.entries
    ]
    return (
        "You are writing social copy for Abdallah, a full-stack developer with a "
        "technical audience. English is his second language: write in simple, "
        "natural, human English. Knowledgeable, concise, curious. No hype, no "
        "clickbait, no fake excitement, no generic AI phrasing.\n\n"
        "Below is a ranked list of GitHub repositories with REAL star deltas. "
        "SUMMARISE the data given — never invent a fact, a feature, a benchmark, "
        "or a trend that is not visible in it. If a repository has no description, "
        "return an empty string for it rather than guessing what it does.\n\n"
        "Do NOT compute or restate totals, ranks, or star counts. Those are "
        "rendered by the application.\n\n"
        f"DATA:\n{json.dumps(repos, ensure_ascii=False)}\n\n"
        f"Return JSON with exactly these keys: {json.dumps(_PROSE_SCHEMA)}\n"
        "Each summary must be ONE sentence, under 140 characters, describing what "
        "the project IS. No markdown, no emojis in summaries."
    )


def _banned_hit(text: str) -> bool:
    """Reject the model's prose if it reaches for the phrases we've banned."""
    import content_formats as CF
    try:
        import social_copy as SC
        banned = set(CF.FORBIDDEN_PHRASES) | set(SC.BANNED)
    except Exception:
        banned = set(CF.FORBIDDEN_PHRASES)
    low = (text or "").lower()
    return any(b in low for b in banned)


def _apply_prose(content: RoundupContent, use_llm=True, model="gpt-4o-mini") -> None:
    """Fill hook/intro/observations/cta/summaries. Deterministic if the LLM fails."""
    week = _week_index()
    content.hook = _FALLBACK_HOOKS[week % len(_FALLBACK_HOOKS)]
    content.intro = _fallback_intro(content)
    content.observations = _fallback_observations(content)
    content.cta = _FALLBACK_CTAS[week % len(_FALLBACK_CTAS)]

    if not use_llm or not content.entries:
        return
    if not os.environ.get("OPENAI_API_KEY", ""):
        return

    try:
        from agent import llm_ops as LLM
        result = LLM.chat(
            [{"role": "user", "content": _prose_prompt(content)}],
            model=model, temperature=0.6, max_tokens=900, timeout=60,
            job_id="roundup_prose", json_mode=True,
        )
        if not result.ok:
            print(f"⚠️ roundup prose failed ({result.error_class}); using template.")
            return
        data = json.loads(result.text)
    except Exception as exc:
        print(f"⚠️ roundup prose unusable ({exc}); using template.")
        return

    hook = (data.get("hook") or "").strip()
    if hook and len(hook) <= 120 and not _banned_hit(hook):
        content.hook = hook

    intro = (data.get("intro") or "").strip()
    if intro and len(intro) <= 320 and not _banned_hit(intro):
        content.intro = intro

    obs = [o.strip() for o in (data.get("observations") or [])
           if isinstance(o, str) and o.strip() and not _banned_hit(o)]
    if obs:
        content.observations = obs[:3]

    cta = (data.get("cta") or "").strip()
    if cta and len(cta) <= 160 and not _banned_hit(cta):
        content.cta = cta

    # A rewritten summary may only REPLACE an existing description. Filling a
    # blank description from the model is exactly the hallucination this guards
    # against: there is no source text for it to be a summary of.
    summaries = data.get("summaries") or {}
    if isinstance(summaries, dict):
        for entry in content.entries:
            new = summaries.get(entry.full_name) or summaries.get(entry.name)
            if (entry.description and isinstance(new, str) and new.strip()
                    and len(new.strip()) <= 200 and not _banned_hit(new)):
                entry.description = " ".join(new.split())


# ── Text helpers ────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://\S+")


def x_weighted_len(text: str) -> int:
    """Approximate X's weighted character count.

    X replaces every URL with a 23-character t.co link regardless of its real
    length, and counts most emoji and CJK as two. Measuring `len()` instead
    under-counts emoji and wildly over-counts long GitHub URLs, so a post that
    X would accept gets split for no reason.
    """
    text = text or ""
    urls = _URL_RE.findall(text)
    stripped = _URL_RE.sub("", text)
    total = 23 * len(urls)
    for ch in stripped:
        total += 2 if ord(ch) > 0x1100 else 1
    return total


def _shorten(text: str, max_chars: int) -> str:
    """Trim prose on a word boundary. Never applied to a URL or a repo name."""
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" .,;:—-")
    return (cut + "…") if cut else ""


# ── LinkedIn ────────────────────────────────────────────────────────────────

class LinkedInRoundupFormatter:
    """The full detailed version. LinkedIn has no practical length limit here."""

    DESC_MAX = 160

    def render(self, content: RoundupContent) -> str:
        blocks = [content.hook, "", content.headline(), ""]
        if content.intro:
            blocks += [content.intro, ""]

        for e in content.entries:
            blocks.append(f"{e.rank}. {e.name} — +{e.weekly_stars:,} ⭐")
            desc = _shorten(e.description, self.DESC_MAX)
            if desc:
                blocks.append(desc)
            blocks.append(f"🔗 {e.url}")
            blocks.append("")

        if content.observations:
            blocks.append("💡 What stood out")
            blocks += content.observations
            blocks.append("")

        if content.article_url:
            blocks += ["📖 Full breakdown:", content.article_url, ""]

        if content.cta:
            blocks += [content.cta, ""]

        blocks.append(_HASHTAGS)
        return "\n".join(blocks).strip()


# ── X / Twitter ─────────────────────────────────────────────────────────────

class XPostTooLong(ValueError):
    """Raised when a post cannot be made to fit — never truncate blindly."""


class XRoundupFormatter:
    """Renders a thread, sized programmatically against X's weighted limit.

    Numbering is resolved before rendering: the packer reserves the width of the
    widest possible "🧵 n/n" suffix, so substituting the real numbers afterwards
    can only ever shrink a post, never overflow one.
    """

    DESC_MAX = 90
    DESC_MIN = 40

    def __init__(self, limit: int = X_LIMIT):
        self.limit = limit

    # -- entry rendering
    def _entry(self, e: RepoEntry, desc_max: int) -> str:
        head = f"{e.rank}. {e.name} — +{e.weekly_stars:,} ⭐"
        desc = _shorten(e.description, desc_max)
        parts = [head] + ([desc] if desc else []) + [f"🔗 {e.url}"]
        return "\n".join(parts)

    def _entry_that_fits(self, e: RepoEntry, budget: int) -> str:
        """Shrink the summary until the entry fits; drop it before the URL."""
        for desc_max in (self.DESC_MAX, 70, self.DESC_MIN, 0):
            block = self._entry(e, desc_max)
            if x_weighted_len(block) <= budget:
                return block
        block = self._entry(e, 0)
        if x_weighted_len(block) > budget:
            # Name + URL alone overflow. Truncating either makes the entry
            # meaningless or the link dead, so surface it instead.
            raise XPostTooLong(f"{e.full_name} cannot fit in {budget} characters")
        return block

    # -- single-post form
    def render_single(self, content: RoundupContent) -> str:
        """One post carrying the headline and as many repos as genuinely fit."""
        head = f"{content.count} {content.label} repos gained {content.total_stars:,} GitHub stars this week."
        lines, tail = [head], f"\n\n{content.article_url}" if content.article_url else ""
        for e in content.entries:
            candidate = lines + [f"{e.rank}. {e.name} +{e.weekly_stars:,}"]
            if x_weighted_len("\n".join(candidate) + tail) > self.limit:
                break
            lines = candidate
        return "\n".join(lines) + tail

    def _combined(self, content: RoundupContent) -> str:
        """The whole roundup as one post — used only when it genuinely fits."""
        lines = [content.hook, "", content.headline(), ""]
        for e in content.entries:
            lines += [self._entry(e, self.DESC_MAX), ""]
        if content.article_url:
            lines += [content.article_url, ""]
        if content.cta:
            lines.append(content.cta)
        return "\n".join(lines).strip()

    def fits_in_one_post(self, content: RoundupContent) -> bool:
        return bool(content.entries) and x_weighted_len(self._combined(content)) <= self.limit

    # -- thread
    def render_thread(self, content: RoundupContent) -> list:
        """Return the thread as a list of posts, each within the limit."""
        if not content.entries:
            return []
        # A short week doesn't need a thread, and each extra post is billed.
        if self.fits_in_one_post(content):
            return [self._combined(content)]
        posts = self._pack(content, numbered=True)
        self.validate(posts)
        return posts

    def _pack_at(self, entries: list, budget: int, desc_max: int) -> list:
        posts, current = [], []
        for e in entries:
            block = self._entry(e, desc_max)
            if x_weighted_len(block) > budget:
                block = self._entry_that_fits(e, budget)
            candidate = current + [block]
            if current and x_weighted_len("\n\n".join(candidate)) > budget:
                posts.append("\n\n".join(current))
                current = [block]
            else:
                current = candidate
        if current:
            posts.append("\n\n".join(current))
        return posts

    def _pack_entries(self, entries: list, budget: int) -> list:
        """Choose the summary width that yields the fewest posts.

        Every post in a thread is billed separately, so a description length
        that fits two entries per post costs half what one-per-post costs. Ties
        go to the longer summary — same price, more information.
        """
        best = None
        for desc_max in (self.DESC_MAX, 70, 55, self.DESC_MIN):
            packed = self._pack_at(entries, budget, desc_max)
            if best is None or len(packed) < len(best):
                best = packed
        return best

    def _closer(self, content: RoundupContent, budget: int) -> str:
        """Takeaway + article link + CTA, shrunk until it fits.

        The article URL is the one part never dropped — it is the whole point of
        the closing post. The takeaway gives way first, then the CTA.
        """
        for takeaway_max, cta_max in ((150, 100), (100, 80), (60, 60), (0, 60), (0, 0)):
            lines = []
            if content.observations and takeaway_max:
                lines.append(f"💡 Takeaway: {_shorten(content.observations[0], takeaway_max)}")
            if content.article_url:
                lines += ["", "Full breakdown:", content.article_url]
            if content.cta and cta_max:
                lines += ["", _shorten(content.cta, cta_max)]
            closer = "\n".join(lines).strip()
            if x_weighted_len(closer) <= budget:
                return closer
        return content.article_url

    def _pack(self, content: RoundupContent, numbered: bool) -> list:
        # Worst case is one entry per post, plus opener and closer.
        max_posts = len(content.entries) + 2
        suffix_room = x_weighted_len(f"\n\n🧵 {max_posts}/{max_posts}") if numbered else 0
        budget = self.limit - suffix_room

        opener_lines = [content.hook, "", content.headline()]
        intro = _shorten(content.intro, 150)
        if intro and x_weighted_len("\n".join(opener_lines + ["", intro])) <= budget - 30:
            opener_lines += ["", intro]
        if numbered:
            opener_lines += ["", "Here are the projects developers are watching 👇"]
        opener = "\n".join(opener_lines)

        body = self._pack_entries(content.entries, budget)

        closer = self._closer(content, budget)

        posts = [opener] + body + ([closer] if closer else [])
        if not numbered:
            return posts
        total = len(posts)
        return [f"{p}\n\n🧵 {i}/{total}" for i, p in enumerate(posts, 1)]

    def validate(self, posts: list) -> None:
        for i, post in enumerate(posts, 1):
            width = x_weighted_len(post)
            if width > self.limit:
                raise XPostTooLong(f"post {i}/{len(posts)} is {width}/{self.limit}")

    @staticmethod
    def char_counts(posts: list, limit: int = X_LIMIT) -> list:
        """(index, total, weighted_length, limit) — for the dry-run preview."""
        return [(i, len(posts), x_weighted_len(p), limit)
                for i, p in enumerate(posts, 1)]
