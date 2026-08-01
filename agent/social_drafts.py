"""Social draft generator for published blog posts.

Creates editable, per-platform post drafts from a published draft's blog_url.
No live publishing happens here.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOCIAL_DRAFTS_DIR = ROOT / "content" / "social_drafts"
SOCIAL_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

VALID_STATUSES = {"idea", "draft", "needs_review", "approved", "scheduled", "published", "failed"}
_STATUS_ALIASES = {"reviewed": "needs_review"}
SUPPORTED_PLATFORMS = {
    "linkedin", "facebook", "x", "threads", "reddit", "newsletter", "youtube",
}

# A scheduled_at written without an offset means the local wall clock the
# operator typed, not UTC. Reading it as UTC published posts hours early.
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo

# A draft is retried a bounded number of times before it is parked as failed,
# so a permanently-rejected post can never occupy the queue forever.
MAX_PUBLISH_ATTEMPTS = 5

# Platform quota rejections resolve on their own at the next local day.
_QUOTA_MARKERS = ("limit reached", "daily limit", "quota")
# Transport-level hiccups are worth one more attempt shortly after.
_TRANSIENT_MARKERS = (
    "rate limit", "429", "timed out", "timeout", "temporarily",
    "502", "503", "504", "connection reset", "connection aborted",
)


@dataclass
class SocialDraft:
    draft_id: str = ""
    source_draft_id: str = ""
    platform: str = ""
    blog_url: str = ""
    title: str = ""
    text: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    status: str = "draft"
    scheduled_at: str = ""
    published_url: str = ""
    published_at: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    campaign_id: str = ""
    attempts: int = 0

    def __post_init__(self):
        if not self.draft_id:
            self.draft_id = str(uuid.uuid4())[:8]
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        self.status = _STATUS_ALIASES.get(self.status, self.status)
        if self.status not in VALID_STATUSES:
            self.status = "draft"

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "source_draft_id": self.source_draft_id,
            "platform": self.platform,
            "blog_url": self.blog_url,
            "title": self.title,
            "text": self.text,
            "description": self.description,
            "tags": self.tags,
            "hashtags": self.hashtags,
            "status": self.status,
            "scheduled_at": self.scheduled_at,
            "published_url": self.published_url,
            "published_at": self.published_at,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": self.history,
            "campaign_id": self.campaign_id,
            "attempts": self.attempts,
        }

    def touch(self) -> None:
        self.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()


def _parse_when(value: str) -> dt.datetime:
    """Parse a scheduled_at string, treating a naive value as local time.

    The scheduler compares against ``now`` in UTC, so a naive string had to be
    given *some* zone. Assuming UTC published every locally-typed time early by
    the size of the UTC offset; assuming local matches what the operator meant.
    """
    when = dt.datetime.fromisoformat(value)
    if when.tzinfo is None:
        when = when.replace(tzinfo=LOCAL_TZ)
    return when


def _next_local_day(now: dt.datetime) -> dt.datetime:
    """Just after midnight local time — when platform daily quotas reset."""
    local = now.astimezone(LOCAL_TZ)
    return (local + dt.timedelta(days=1)).replace(
        hour=0, minute=5, second=0, microsecond=0
    )


def _retry_plan(error: str, now: dt.datetime) -> tuple[dt.datetime, str] | None:
    """When a failure is worth retrying, return (retry_at, reason).

    A quota rejection ("daily news limit reached") is not a broken draft — the
    post is fine and the platform simply has no room today. Burning it to
    ``failed`` is what left a backlog of drafts needing a manual retry.
    """
    text = (error or "").lower()
    if any(marker in text for marker in _QUOTA_MARKERS):
        return _next_local_day(now), "platform daily limit"
    if any(marker in text for marker in _TRANSIENT_MARKERS):
        return now + dt.timedelta(hours=1), "transient platform error"
    return None


def _social_draft_path(draft_id: str) -> Path:
    if ".." in draft_id or "/" in draft_id or "\\" in draft_id:
        raise ValueError("invalid draft id")
    return SOCIAL_DRAFTS_DIR / f"{draft_id}.json"


def _extract_summary(body: str, max_chars: int = 240) -> str:
    """Return the first substantive paragraph, excluding headings and sources."""
    body = re.sub(r"```.*?```", "", body or "", flags=re.S)
    body = re.sub(r"^#\s+.*$", "", body, flags=re.M)
    body = re.split(r"^##\s+(?:sources?|references?)\b", body, maxsplit=1, flags=re.I | re.M)[0]
    for paragraph in re.split(r"\n\s*\n", body):
        text = re.sub(r"^\s{0,3}#{1,6}\s+", "", paragraph, flags=re.M)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Unwrap emphasis, but only where the marker wraps a word. Blanket
        # stripping of "_" also ate the underscore inside identifiers, so
        # `reserved_at` went out to LinkedIn as "reservedat".
        text = re.sub(r"(?<![\w*])\*{1,2}([^*\n]+)\*{1,2}(?![\w*])", r"\1", text)
        text = re.sub(r"(?<![\w_])_{1,2}([^_\n]+)_{1,2}(?![\w_])", r"\1", text)
        text = text.replace("`", "")
        text = re.sub(r"\s+", " ", text).strip(" -")
        if len(text) >= 80 and not _contains_placeholder(text):
            return _truncate(text, max_chars)
    return ""


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rsplit(" ", 1)[0] + "..."


def _contains_placeholder(text: str) -> bool:
    normalized = " ".join((text or "").lower().split())
    markers = (
        "explain why this matters",
        "what the reader should do next",
        "deep technical analysis of the news",
        "builder takeaway explain",
        "angle deep technical analysis",
        "what do you think?",
    )
    return any(marker in normalized for marker in markers)


def _quality_error(title: str, body: str, summary: str = "") -> str | None:
    if not title or len(title.strip()) < 12:
        return "content needs a specific title before social drafts can be created"
    if _contains_placeholder(title) or _contains_placeholder(body):
        return "content contains placeholder copy; write a substantive article before creating social drafts"
    if len(re.sub(r"\s+", "", body or "")) < 180:
        return "content is too short to create a useful social post"
    if not summary:
        return "content has no substantive introductory paragraph for social copy"
    return None


_URL_RE = re.compile(r"https?://\S+")
# Something checkable. Two families count, because technical specificity is not
# always numeric: "the reserved_at timestamp is cleared before the handler
# finishes" names a real mechanism and carries no digit at all.
#
#   measurements — a version, count, percentage, duration, or CVE. A bare
#                  four-digit year is excluded: "in 2026" is not a fact about
#                  the thing being described.
#   identifiers  — backticked code, snake_case, a call, a path, a CONSTANT.
#                  Deliberately NOT plain CamelCase, which would match any
#                  brand name and let "OpenAI has improved their API" through.
_CONCRETE_FACT_RE = re.compile(
    r"\bCVE-\d{4}-\d{4,}\b"
    r"|\b\d+\.\d+(?:\.\d+)?\b"
    r"|\b\d+\s?(?:%|percent|ms|x|k|m|bn|gb|mb|kb|hours?|minutes?|days?|weeks?)\b"
    r"|\b(?!\d{4}\b)\d[\d,]*\b"
    r"|`[^`]+`"
    r"|\b[a-z][a-z0-9]*_[a-z0-9_]+\b"
    r"|\b\w+\([^)]*\)"
    r"|(?:^|\s)/[\w.-]+(?:/[\w.-]+)+"
    r"|\b[A-Z][A-Z0-9]{2,}_[A-Z0-9_]+\b",
    re.I,
)
# Feed-derived drafts carry a provenance marker that is not prose.
_BOILERPLATE_RE = re.compile(r"\bsource:\s*\w+", re.I)


# Minimum prose (URL and boilerplate excluded) before a post says anything.
# X is held lower on purpose: the whole post is 280 characters including the
# link, so its copy is ~115 by construction and the general floor rejected
# every X draft outright.
_MIN_PROSE_CHARS = 100
_MIN_PROSE_CHARS_SHORTFORM = 60
_SHORTFORM_PLATFORMS = {"x", "threads"}


def _social_post_quality_error(title: str, text: str,
                               platform: str | None = None) -> str | None:
    if not title or len(title.strip()) < 12:
        return "social draft needs a specific title before publishing"
    if _contains_placeholder(title) or _contains_placeholder(text):
        return "social draft contains placeholder copy and cannot be published"

    # Measure the *prose*. A link and a "Source: hackernews" tag are not copy,
    # and counting them let a post that was nothing but the headline repeated
    # three times clear both the length and the distinct-term checks — a long
    # URL alone contributes a dozen "terms".
    prose = _BOILERPLATE_RE.sub(" ", _URL_RE.sub(" ", text or ""))
    floor = (_MIN_PROSE_CHARS_SHORTFORM
             if (platform or "").lower() in _SHORTFORM_PLATFORMS
             else _MIN_PROSE_CHARS)
    if len(re.sub(r"\s+", "", prose)) < floor:
        return "social draft is too short to publish"

    title_terms = set(re.findall(r"[a-z0-9]+", title.lower()))
    post_terms = re.findall(r"[a-z0-9]+", prose.lower())
    non_title_terms = [term for term in post_terms if term not in title_terms]
    if title.lower() in text.lower() and len(non_title_terms) < 18:
        return "social draft mostly repeats its headline and cannot be published"

    # A post has to carry one concrete, checkable fact. "OpenAI has updated
    # their API to improve usability and performance for developers" is a
    # grammatical sentence that tells a developer nothing — it survived every
    # other check here because it is long enough and does not repeat the title.
    # A number, version, or CVE is the cheapest reliable proxy for specificity.
    if not _CONCRETE_FACT_RE.search(prose):
        return "social draft states no concrete fact (no version, number, or measure)"
    return None


def social_post_quality_error(title: str, text: str,
                              platform: str | None = None) -> str | None:
    """Why this copy cannot be published, or None if it is publishable.

    Public wrapper so a publishing lane can reject bad copy at generation time,
    with a line in its own log, instead of discovering it hours later when the
    scheduler parks the draft for review.
    """
    return _social_post_quality_error(title, text, platform)


def _format_hashtags(tags: list[str]) -> list[str]:
    cleaned = [re.sub(r"[^a-zA-Z0-9]", "", tag) for tag in tags if tag]
    cleaned = [tag for tag in cleaned if tag]
    if not any(tag.lower() == "buildwithabdallah" for tag in cleaned):
        cleaned.append("BuildWithAbdallah")
    return cleaned[:5]


def _platform_copy(title: str, summary: str, blog_url: str, hashtags: list[str]) -> tuple[str, str, str]:
    """Compose social-native copy from the article's own summary.

    NOTE: this deliberately contains no per-article special cases. An earlier
    revision dispatched three hardcoded narratives on loose substring matches
    ("code review" in subject, etc.), which meant any future article whose
    title+summary happened to contain those words would publish factually
    unrelated copy verbatim to LinkedIn/Facebook/X. Keep this generic — the
    LLM-written variants live in scripts/social_copy.py.
    """
    hashtag_str = " ".join(f"#{tag}" for tag in hashtags)
    linkedin = (
        f"{summary}\n\n"
        "The interesting part is not the headline. It is the implementation decision that changes how this "
        "behaves in a real project.\n\n"
        f"I break that down in the full guide: {blog_url}\n\n{hashtag_str}"
    )
    facebook = (
        f"{summary}\n\n"
        "I focused on the practical implementation choices, not just the demo.\n\n"
        f"Read the full guide: {blog_url}\n\n{hashtag_str}"
    )
    return linkedin, facebook, f"{_truncate(summary, 115)}\n{blog_url}\n{hashtag_str}"


def generate_social_drafts(
    source_draft_id: str,
    blog_url: str,
    title: str,
    body: str,
    platforms: list[str],
    tags: list[str] | None = None,
) -> list[SocialDraft]:
    """Generate social post drafts for selected platforms.

    Returns an empty list if blog_url is missing or platforms is empty.
    """
    if not blog_url or not platforms:
        return []

    summary = _extract_summary(body, 280)
    if _quality_error(title, body, summary):
        return []
    hashtags = _format_hashtags(tags or [])
    hashtag_str = " ".join(f"#{tag}" for tag in hashtags)
    linkedin_text, facebook_text, x_text = _platform_copy(title, summary, blog_url, hashtags)

    builders = {
        "linkedin": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="linkedin",
            blog_url=blog_url,
            title=title,
            text=linkedin_text,
            description=summary,
            hashtags=hashtags,
        ),
        "facebook": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="facebook",
            blog_url=blog_url,
            title=title,
            text=facebook_text,
            description=summary,
            hashtags=hashtags,
        ),
        "x": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="x",
            blog_url=blog_url,
            title=title,
            text=x_text,
            description=_truncate(summary, 180),
            hashtags=hashtags,
        ),
        "threads": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="threads",
            blog_url=blog_url,
            title=title,
            text=f"{summary}\n\nThe full implementation is here: {blog_url}\n\n{hashtag_str}",
            description=summary,
            hashtags=hashtags,
        ),
        "reddit": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="reddit",
            blog_url=blog_url,
            title=title,
            text=f"{summary}\n\nFull write-up: {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
        "newsletter": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="newsletter",
            blog_url=blog_url,
            title=title,
            text=f"# {title}\n\n{summary}\n\nRead the full article: {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
        "youtube": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="youtube",
            blog_url=blog_url,
            title=title,
            text=f"{summary}\n\nFull guide: {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
    }

    drafts: list[SocialDraft] = []
    for platform in platforms:
        platform = platform.lower().strip()
        if platform in SUPPORTED_PLATFORMS and platform in builders:
            drafts.append(builders[platform]())
    return drafts


def save_social_draft(draft: SocialDraft) -> Path:
    draft.touch()
    path = _social_draft_path(draft.draft_id)
    path.write_text(json.dumps(draft.to_dict(), indent=2), encoding="utf-8")
    return path


def load_social_draft(draft_id: str) -> SocialDraft | None:
    path = _social_draft_path(draft_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SocialDraft(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def update_social_draft(draft_id: str, fields: dict[str, Any]) -> SocialDraft | None:
    draft = load_social_draft(draft_id)
    if draft is None:
        return None
    old_status = draft.status
    if "status" in fields:
        new_status = _STATUS_ALIASES.get(fields["status"], fields["status"])
        fields = {**fields, "status": new_status}
        if new_status not in VALID_STATUSES:
            return None
    allowed = {"title", "text", "description", "tags", "hashtags", "status"}
    for key, value in fields.items():
        if key in allowed and hasattr(draft, key):
            if key in {"tags", "hashtags"} and isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            setattr(draft, key, value)
    if "status" in fields and draft.status != old_status:
        draft.history.append({
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "from": old_status,
            "to": draft.status,
        })
    draft.touch()
    save_social_draft(draft)
    return draft


def list_social_drafts(source_draft_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    out = []
    for p in sorted(SOCIAL_DRAFTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if source_draft_id is not None and data.get("source_draft_id") != source_draft_id:
                continue
            if status is not None and data.get("status") != status:
                continue
            out.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return out


def delete_social_draft(draft_id: str) -> bool:
    path = _social_draft_path(draft_id)
    if path.exists():
        path.unlink()
        return True
    return False


def schedule_social_drafts(
    draft_ids: list[str],
    scheduled_at: str,
    stagger_minutes: int = 0,
) -> dict[str, Any]:
    """Schedule approved social drafts for future publishing.

    Only drafts with status=approved can be scheduled. Sets status=scheduled
    and stores the ISO datetime. Immediate publishing does not happen.

    ``stagger_minutes`` spaces successive drafts out from ``scheduled_at``.
    Without it every selected draft carries the identical timestamp and the
    whole batch fires in a single run — which reads as a burst on the feed and
    walks straight into the platform daily limits.
    """
    results: dict[str, Any] = {}
    try:
        base = _parse_when(scheduled_at)
    except ValueError:
        return {
            "ok": True,
            "results": {
                draft_id: {"ok": False, "error": "invalid scheduled_at datetime"}
                for draft_id in draft_ids
            },
        }

    offset = 0
    for draft_id in draft_ids:
        draft = load_social_draft(draft_id)
        if draft is None:
            results[draft_id] = {"ok": False, "error": "social draft not found"}
            continue
        if draft.status != "approved":
            results[draft_id] = {"ok": False, "error": f"draft must be approved, current status: {draft.status}"}
            continue
        when = base + dt.timedelta(minutes=stagger_minutes * offset)
        offset += 1
        draft.status = "scheduled"
        # Store normalized and tz-aware so the queue never re-guesses the zone.
        draft.scheduled_at = when.isoformat()
        draft.attempts = 0
        draft.error = ""
        save_social_draft(draft)
        results[draft_id] = {"ok": True, "draft": draft.to_dict()}
    return {"ok": True, "results": results}


def publish_social_draft(draft_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Publish a single approved/scheduled social draft to its platform.

    Returns ok, published_url, error. On success, updates the draft with
    published_url, published_at, and status=published. On failure, sets
    status=failed and stores error.
    """
    from .social_publishers import publish

    draft = load_social_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "social draft not found"}
    if draft.status not in {"approved", "scheduled"}:
        return {"ok": False, "error": f"social draft must be approved or scheduled, current status: {draft.status}"}

    now = dt.datetime.now(dt.timezone.utc)
    was_scheduled = draft.status == "scheduled"

    error = _social_post_quality_error(draft.title, draft.text, draft.platform)
    if error:
        # A scheduled draft that fails the gate can never pass it unedited, so
        # leaving it queued made the hourly publisher retry it forever. Park it
        # for review instead — it leaves the queue and stays visible.
        if was_scheduled and not dry_run:
            draft.status = "needs_review"
            draft.error = error
            draft.history.append({
                "ts": now.isoformat(),
                "from": "scheduled",
                "to": "needs_review",
                "note": f"quality gate: {error}",
            })
            draft.touch()
            save_social_draft(draft)
        return {"ok": False, "error": error}

    result = publish(draft.platform, draft.to_dict(), dry_run=dry_run)
    if dry_run:
        # A rehearsal must leave the queue exactly as it found it. Recording a
        # dry run as published — with a placeholder URL — retired every draft
        # it touched, and `publish_due` ships with dry_run enabled by default.
        return {**result, "dry_run": True, "would_publish": bool(result.get("ok"))}
    if result.get("ok"):
        draft.status = "published"
        draft.published_url = result.get("published_url", "")
        draft.published_at = now.isoformat()
        draft.error = ""
    else:
        failure = result.get("error", "publish failed")
        draft.error = failure
        draft.attempts = (draft.attempts or 0) + 1
        plan = _retry_plan(failure, now) if was_scheduled else None
        if plan and draft.attempts < MAX_PUBLISH_ATTEMPTS:
            retry_at, reason = plan
            draft.status = "scheduled"
            draft.scheduled_at = retry_at.isoformat()
            draft.history.append({
                "ts": now.isoformat(),
                "from": "scheduled",
                "to": "scheduled",
                "note": f"retry {draft.attempts}/{MAX_PUBLISH_ATTEMPTS} at {retry_at.isoformat()} ({reason})",
            })
            result = {**result, "retryable": True, "retry_at": retry_at.isoformat()}
        else:
            draft.status = "failed"
    save_social_draft(draft)
    return result


def publish_due_social_drafts(dry_run: bool = False, max_per_run: int = 0) -> dict[str, Any]:
    """Publish scheduled social drafts whose scheduled_at has passed.

    Skips future scheduled drafts. Returns per-id results.

    ``max_per_run`` (0 = unlimited) caps how many drafts one pass may publish.
    A backlog — the dashboard was down, or a day of drafts came due together —
    otherwise drains as a single burst the moment the scheduler comes back.
    Oldest due first, so nothing starves behind a newer draft.
    """
    now = dt.datetime.now(dt.timezone.utc)
    results: dict[str, Any] = {}
    due: list[tuple[dt.datetime, str]] = []

    for data in list_social_drafts(status="scheduled"):
        draft_id = data.get("draft_id")
        scheduled_at = data.get("scheduled_at", "")
        try:
            when = _parse_when(scheduled_at)
        except ValueError:
            results[draft_id] = {"ok": False, "error": "invalid scheduled_at"}
            continue
        if when > now:
            results[draft_id] = {"ok": False, "error": "scheduled for the future", "skipped": True}
            continue
        due.append((when, draft_id))

    due.sort(key=lambda item: item[0])
    for index, (_, draft_id) in enumerate(due):
        if max_per_run and index >= max_per_run:
            results[draft_id] = {
                "ok": False,
                "error": f"deferred — run cap of {max_per_run} reached",
                "skipped": True,
            }
            continue
        results[draft_id] = publish_social_draft(draft_id, dry_run=dry_run)
    return {"ok": True, "results": results}


def publish_selected_social_drafts(draft_ids: list[str], dry_run: bool = False) -> dict[str, Any]:
    """Publish multiple approved social drafts. Returns per-id results."""
    results = {}
    for draft_id in draft_ids:
        results[draft_id] = publish_social_draft(draft_id, dry_run=dry_run)
    return {"ok": True, "results": results}


def retry_social_draft(draft_id: str) -> dict[str, Any]:
    """Reset a failed draft back to approved so it can be retried."""
    draft = load_social_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "social draft not found"}
    if draft.status != "failed":
        return {"ok": False, "error": f"only failed drafts can be retried, current status: {draft.status}"}
    old_status = draft.status
    draft.status = "approved"
    draft.error = ""
    draft.history.append({
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "from": old_status,
        "to": "approved",
        "note": "manual retry",
    })
    draft.touch()
    save_social_draft(draft)
    return {"ok": True, "draft": draft.to_dict()}


def create_social_drafts_from_blog(
    source_draft_id: str,
    blog_url: str,
    title: str,
    body: str,
    platforms: list[str],
    tags: list[str] | None = None,
) -> list[SocialDraft]:
    """Generate and persist social drafts for a published blog post."""
    drafts = generate_social_drafts(source_draft_id, blog_url, title, body, platforms, tags)
    for d in drafts:
        save_social_draft(d)
    return drafts
