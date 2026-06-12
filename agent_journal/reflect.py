"""Reflection pass: digest of graded runs → one Anthropic call → proposals.

Fresh context every time — only the rubric and the digest are sent, never
conversation history. Output is parsed defensively: fences stripped,
schema validated, malformed items skipped with a stderr warning.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests

from agent_journal.db import get_meta, set_meta
from agent_journal.proposals import PROPOSAL_TYPES, insert_proposal

DEFAULT_REFLECT_MODEL = "claude-fable-5"
MIN_NEWLY_GRADED = 10
_META_LAST_REFLECTED = "last_reflected_run_id"

RUBRIC_PROMPT = """\
You are a quality auditor for "Taco", an automated content agent. You are
given a digest of its recent runs: task type, content pillar, prompt
version, final outcome (approved / corrected / rejected / published),
the human reviewer's correction notes, and any errors.

Your job, in order:

1. FAILURE PATTERNS — identify recurring failure patterns. A pattern
   needs at least 2 supporting runs; cite their run ids as evidence.
   One-off failures are noise: mention them in one line, do not propose
   changes for them.

2. PROPOSALS — for each pattern, propose at most one minimal change.
   Fewer, better proposals beat many speculative ones. Zero proposals
   is a valid answer.

Allowed proposal types:
- "prompt_edit"  — change wording in the system prompt. target = the
  section name, change = exact new wording.
- "rule_add"     — add one new rule the system prompt will load.
  change = the exact rule text, imperative, max 2 sentences.
- "config_change"— change a config value. target = file/key,
  change = old -> new and why.
- "code_change"  — requires human implementation. target = file/function,
  change = precise description of the fix.

Hard constraints:
- Never propose changes to: the proposal gate, the run journal or its
  schema, the source verification rules (Verified-source /
  vendor-reported), or this rubric. Such proposals will be discarded.
- Never propose relaxing a validation gate to make failures pass.
- Every proposal must cite evidence_run_ids from the digest.

Output: a single JSON array, no markdown fences, no commentary:
[{"type": "...", "target": "...", "change": "...",
  "evidence_run_ids": [..], "expected_effect": "..."}]
Output [] if no pattern meets the evidence bar.
"""


def reflect_model() -> str:
    return os.environ.get("ANTHROPIC_REFLECT_MODEL", DEFAULT_REFLECT_MODEL)


def newly_graded_count(conn) -> int:
    """Graded runs since the last reflection (for the cron gate)."""
    last = int(get_meta(conn, _META_LAST_REFLECTED, "0"))
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_runs WHERE outcome IS NOT NULL AND id > ?",
        (last,),
    ).fetchone()
    return row["n"]


def build_digest(rows: list[dict[str, Any]]) -> str:
    """One structured line per graded run."""
    lines = []
    for r in rows:
        lines.append(
            f"run {r['id']} | {r['task_type']} | pillar={r['pillar'] or '-'} "
            f"| prompt v{r['prompt_version'] or '?'} | model={r['model_used'] or '-'} "
            f"| outcome={r['outcome']}"
            f" | note: {(r['outcome_detail'] or '-')[:200]}"
            f" | error: {(r['error'] or '-')[:200]}"
        )
    return "\n".join(lines)


def parse_proposals(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse the model's output into validated proposal items.

    Returns (valid_items, warnings). Never raises on malformed input.
    """
    warnings: list[str] = []
    raw = (text or "").strip()
    if raw.startswith("```"):
        # Strip an opening fence (with optional language tag) and a closing one.
        lines = raw.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    data: Any = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Fallback: extract the outermost JSON array.
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
    if data is None:
        warnings.append("Reflection output is not valid JSON; no proposals parsed.")
        return [], warnings
    if not isinstance(data, list):
        warnings.append(f"Reflection output is {type(data).__name__}, expected a list.")
        return [], warnings

    valid: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        problem = _validate_item(item)
        if problem:
            warnings.append(f"Proposal item {i} rejected: {problem}")
            continue
        item["evidence_run_ids"] = [int(x) for x in item["evidence_run_ids"]]
        valid.append(item)
    return valid, warnings


def _validate_item(item: Any) -> str | None:
    if not isinstance(item, dict):
        return f"not an object ({type(item).__name__})"
    if item.get("type") not in PROPOSAL_TYPES:
        return f"invalid type '{item.get('type')}'"
    for key in ("target", "change", "expected_effect"):
        if not isinstance(item.get(key), str) or not item.get(key, "").strip():
            return f"missing/empty '{key}'"
    ids = item.get("evidence_run_ids")
    if not isinstance(ids, list) or not ids:
        return "missing/empty 'evidence_run_ids'"
    try:
        [int(x) for x in ids]
    except (TypeError, ValueError):
        return "non-integer evidence_run_ids"
    return None


def call_anthropic(digest: str, model: str, api_key: str) -> tuple[str, str]:
    """One messages call; returns (text, responding_model).

    The responding model is taken from the API response — Fable can fall
    back to Opus, and we record what actually answered.
    """
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2000,
            "system": RUBRIC_PROMPT,
            "messages": [{"role": "user", "content": f"Run digest:\n\n{digest}"}],
        },
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Anthropic API HTTP {response.status_code}: {response.text[:300]}")
    payload = response.json()
    responded_model = str(payload.get("model", ""))
    text = "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    )
    return text, responded_model


def run_reflection(
    conn,
    *,
    last: int = 25,
    model: str | None = None,
    force: bool = False,
    min_graded: int = MIN_NEWLY_GRADED,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Run one reflection pass; returns a summary dict.

    Raises RuntimeError on hard failures (no key, API error) — the CLI
    turns those into a warning + exit 0 so cron never breaks.
    """
    model = model or reflect_model()
    summary: dict[str, Any] = {"ran": False, "model": model, "proposals": 0, "warnings": []}

    if not force:
        n = newly_graded_count(conn)
        if n < min_graded:
            summary["skipped"] = (
                f"only {n} newly graded runs since last reflection "
                f"(need >= {min_graded}; use --force to override)"
            )
            return summary

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM agent_runs WHERE outcome IS NOT NULL ORDER BY id DESC LIMIT ?",
        (last,),
    ).fetchall()]
    if not rows:
        summary["skipped"] = "no graded runs to reflect on"
        return summary
    rows.reverse()  # chronological order in the digest

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("BWA_ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY (or BWA_ANTHROPIC_API_KEY)")

    digest = build_digest(rows)
    run_ids = [r["id"] for r in rows]
    responded_model, error_text = "", None
    valid: list[dict[str, Any]] = []
    try:
        text, responded_model = call_anthropic(digest, model, api_key)
        valid, warnings = parse_proposals(text)
        summary["warnings"] = warnings
        for w in warnings:
            print(f"[reflect] WARNING: {w}", file=sys.stderr)
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"

    proposal_ids = [insert_proposal(conn, item, run_ids) for item in valid]
    conn.execute(
        """INSERT INTO reflections
           (requested_model, responded_model, runs_count, run_id_min, run_id_max,
            proposals_created, error)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (model, responded_model, len(rows), min(run_ids), max(run_ids),
         len(proposal_ids), error_text),
    )
    conn.commit()

    if error_text:
        raise RuntimeError(f"Reflection failed: {error_text}")

    set_meta(conn, _META_LAST_REFLECTED, str(max(run_ids)))
    summary.update(ran=True, responded_model=responded_model,
                   runs=len(rows), proposals=len(proposal_ids),
                   proposal_ids=proposal_ids)
    return summary
