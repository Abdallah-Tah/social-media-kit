"""ContentDecision audit log — every editorial decision, accepted or rejected.

Phase 0 defines the record and the append-only log. The scoring *logic* lands in
Phase 1; this module deliberately does not compute scores, it only stores what a
gate decided and why.

Why it exists: the dashboard is supposed to show "opportunities discovered" and
"opportunities rejected". Those numbers have to come from somewhere real, and a
rejected topic currently leaves no trace at all — it is simply not published.
This is the trace.

Scores are stored SEPARATELY on purpose (Abdallah's call, and the right one):
  source_confidence     0-100  how reliable/corroborated the sourcing is
  editorial_quality     0-100  structure, grounding, originality, usefulness
  publication_readiness pass/fail  the actual gate result
A single blended "confidence" number would imply the system knows whether an
article is objectively true. It does not.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

KIT = Path(__file__).resolve().parents[1]
DECISION_LOG = KIT / "content" / "content_decisions.jsonl"

# Pipeline stages a decision can come from.
STAGES = ("discovery", "topic_admission", "article_gate", "publish")

# Rejection reason codes. The dashboard groups by these, so they are a closed
# vocabulary rather than free text.
REASON_CODES = (
    "duplicate_slug",
    "duplicate_topic",
    "topic_saturated",
    "no_primary_source",
    "uncorroborated_extraordinary_claim",
    "promotional_only",
    "no_practical_value",
    "format_gate_failed",
    "below_quality_threshold",
    "ungrounded_numeric_claim",
    "publish_failed",
    "accepted",
)


@dataclass
class ContentDecision:
    stage: str
    decision: str  # accepted | rejected
    job_id: str
    title: str = ""
    slug: str = ""
    reason_code: str = ""
    reason: str = ""
    source_confidence: int | None = None
    editorial_quality: int | None = None
    publication_readiness: str | None = None  # passed | failed
    sources: list[str] = field(default_factory=list)
    content_format: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    ts: str = ""

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(f"unknown stage: {self.stage}")
        if self.decision not in ("accepted", "rejected"):
            raise ValueError(f"decision must be accepted|rejected, got {self.decision!r}")
        if self.reason_code and self.reason_code not in REASON_CODES:
            raise ValueError(f"unknown reason_code: {self.reason_code}")
        if self.publication_readiness not in (None, "passed", "failed"):
            raise ValueError("publication_readiness must be passed|failed|None")
        for name in ("source_confidence", "editorial_quality"):
            score = getattr(self, name)
            if score is not None and not 0 <= score <= 100:
                raise ValueError(f"{name} out of range: {score}")
        if not self.ts:
            self.ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")


def record(decision: ContentDecision) -> ContentDecision:
    """Append one decision. Never raises into the pipeline."""
    try:
        DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DECISION_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(decision)) + "\n")
    except OSError:
        pass
    return decision


def accept(stage: str, job_id: str, **kw: Any) -> ContentDecision:
    return record(ContentDecision(stage=stage, decision="accepted", job_id=job_id,
                                  reason_code=kw.pop("reason_code", "accepted"), **kw))


def reject(stage: str, job_id: str, reason_code: str, reason: str = "",
           **kw: Any) -> ContentDecision:
    return record(ContentDecision(stage=stage, decision="rejected", job_id=job_id,
                                  reason_code=reason_code, reason=reason, **kw))


def read(limit: int | None = None) -> list[dict[str, Any]]:
    try:
        with DECISION_LOG.open(encoding="utf-8") as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
    except (OSError, ValueError):
        return []
    return rows[-limit:] if limit else rows


def summary(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Counters the Phase 3 metrics endpoint will serve."""
    rows = read() if rows is None else rows
    accepted = [r for r in rows if r.get("decision") == "accepted"]
    rejected = [r for r in rows if r.get("decision") == "rejected"]
    by_reason: dict[str, int] = {}
    for r in rejected:
        code = r.get("reason_code") or "unspecified"
        by_reason[code] = by_reason.get(code, 0) + 1
    scored = [r for r in rows if r.get("editorial_quality") is not None]
    return {
        "decisions": len(rows),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "rejected_by_reason": by_reason,
        "duplicates_prevented": by_reason.get("duplicate_slug", 0)
                                + by_reason.get("duplicate_topic", 0),
        "avg_editorial_quality": (
            round(sum(r["editorial_quality"] for r in scored) / len(scored), 1)
            if scored else None
        ),
    }
