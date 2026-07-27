"""One instrumented LLM entry point for every publishing lane (Phase 0).

Before this module, six hand-rolled `requests.post(".../chat/completions")`
callers each had their own timeout, error handling, and zero token accounting.
That made cost, retry classification, and quality scoring impossible to build on
top of. Everything now goes through `chat()`, which records one ledger line per
call.

Naming note: `agent/llm.py` already owns a `LLMClient` — that one drives the
multi-provider tool-calling agent loop. This is a different job: instrumented
one-shot completions for the publishing scripts. Kept separate deliberately.

Honesty rules (they are the point of the ledger):
  - Token counts come from the provider's `usage` block. If it is absent, they
    are recorded as null and the cost as "unknown" — never estimated.
  - Cost is an ESTIMATE from a local price table, stamped with `pricing_version`
    so a stale table is visible rather than silently wrong.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import requests

KIT = Path(__file__).resolve().parents[1]
USAGE_LEDGER = KIT / "content" / "llm_usage.jsonl"

DEFAULT_BASE_URL = "https://api.openai.com/v1"

# USD per 1M tokens. Update `PRICING_VERSION` whenever this changes — a cost
# figure whose pricing_version is old should be treated as approximate.
PRICING_VERSION = "2026-07-27"
PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

# What a cost figure accounts for. Local inference is NOT free to operate —
# electricity, hardware amortisation, and wall-clock time are real costs that
# this ledger does not measure. Recording 0 without saying so would be a lie of
# omission, so a local model carries `local_compute_excluded`.
PRICING_BASIS_API = "provider_api_pricing"
PRICING_BASIS_LOCAL = "local_compute_excluded"

# Providers reachable as fallbacks that have NO price entry yet. Any call to one
# of these lands in `unpriced_models` and drags pricing_coverage to "partial".
KNOWN_UNPRICED_PROVIDERS = ("gemini", "alibaba/qwen", "ollama")

# HTTP statuses worth retrying. 429 is rate limiting; 5xx is the provider.
TRANSIENT_STATUSES = {408, 409, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """Raised by ChatResult.raise_for_status() so callers can keep old semantics."""


@dataclass
class ChatResult:
    ok: bool
    text: str = ""
    status_code: int | None = None
    error: str | None = None
    error_class: str | None = None  # transient | permanent | unknown
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    duration_ms: int = 0
    cost_usd: float | None = None
    cost_known: bool = False
    pricing_basis: str | None = None
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise LLMError(f"{self.error_class or 'error'}: {self.error}")

    def json(self) -> Any:
        """Parse the completion as JSON (for response_format=json_object calls)."""
        return json.loads(self.text)


def classify_error(status: int | None, exc: BaseException | None = None) -> str:
    """transient (retry) vs permanent (don't) — Phase 2 backoff depends on this."""
    if exc is not None and status is None:
        # Connection/timeout errors are worth another attempt.
        return "transient"
    if status is None:
        return "unknown"
    if status in TRANSIENT_STATUSES:
        return "transient"
    if 400 <= status < 500:
        return "permanent"  # auth, bad request, invalid_grant-style failures
    return "unknown"


def estimate_cost(model: str, input_tokens: int | None,
                  output_tokens: int | None) -> tuple[float | None, bool]:
    """Return (cost_usd, known). Unknown model or missing usage → (None, False)."""
    price = PRICING.get(model)
    if not price or input_tokens is None or output_tokens is None:
        return None, False
    cost = (input_tokens / 1_000_000) * price["input"] + \
           (output_tokens / 1_000_000) * price["output"]
    return round(cost, 6), True


def _record(result: ChatResult, job_id: str, content_id: str | None,
            provider: str) -> None:
    """Append one line to the usage ledger. Never raises into the caller."""
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "job_id": job_id,
        "content_id": content_id,
        "provider": provider,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cached_tokens": result.cached_tokens,
        "duration_ms": result.duration_ms,
        "cost_usd": result.cost_usd,
        "cost_known": result.cost_known,
        "pricing_basis": result.pricing_basis,
        "pricing_version": PRICING_VERSION if result.cost_known else None,
        "ok": result.ok,
        "status_code": result.status_code,
        "error_class": result.error_class,
        "error": (result.error or "")[:300] or None,
    }
    try:
        USAGE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass  # accounting must never break publishing


def chat(
    messages: list[dict[str, str]],
    *,
    model: str = "gpt-4o",
    temperature: float = 0.5,
    max_tokens: int | None = None,
    json_mode: bool = False,
    timeout: int = 120,
    job_id: str = "unknown",
    content_id: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ChatResult:
    """One instrumented completion. Never raises on HTTP failure — inspect .ok.

    Callers that previously used `raise_for_status()` keep that behavior by
    calling `result.raise_for_status()`.
    """
    key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
    url = (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/") \
        + "/chat/completions"
    provider = "openai" if "api.openai.com" in url else "custom"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    started = time.monotonic()
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — network layer, classified below
        result = ChatResult(
            ok=False, error=str(exc), error_class=classify_error(None, exc),
            duration_ms=int((time.monotonic() - started) * 1000), model=model,
        )
        _record(result, job_id, content_id, provider)
        return result

    duration_ms = int((time.monotonic() - started) * 1000)
    status = getattr(resp, "status_code", None)

    if not getattr(resp, "ok", False):
        result = ChatResult(
            ok=False, status_code=status,
            error=(getattr(resp, "text", "") or "")[:800],
            error_class=classify_error(status),
            duration_ms=duration_ms, model=model,
        )
        _record(result, job_id, content_id, provider)
        return result

    body = resp.json()
    text = (body.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    usage = body.get("usage") or {}
    # Missing usage stays None — the ledger says "unknown", it does not guess.
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    cost, known = estimate_cost(model, input_tokens, output_tokens)

    result = ChatResult(
        ok=True, text=text, status_code=status,
        pricing_basis=PRICING_BASIS_API if known else None,
        input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=cached,
        duration_ms=duration_ms, cost_usd=cost, cost_known=known, model=model, raw=body,
    )
    _record(result, job_id, content_id, provider)
    return result


# ── Ledger reads (Phase 3 metrics build on these) ───────────────────────────

def read_usage(limit: int | None = None) -> list[dict[str, Any]]:
    try:
        with USAGE_LEDGER.open(encoding="utf-8") as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
    except (OSError, ValueError):
        return []
    return rows[-limit:] if limit else rows


# LLM call sites NOT routed through this module. Any total here is a floor, not
# the platform's spend, until this tuple is empty.
#
# Phase 0.5 migrated agent/feed.py and agent/shorts.py. Still outstanding:
#   agent/llm.py           — the multi-provider tool-calling agent loop, which
#                            posts via its own _post(); instrumenting it means
#                            characterizing a full tool round-trip first.
#   scripts/image_generator.py — Gemini/FAL/OpenAI image generation, priced
#                            per-image rather than per-token, so it needs its
#                            own pricing model rather than this token table.
UNINSTRUMENTED_PATHS = ("agent/llm.py", "scripts/image_generator.py")


def usage_summary(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Totals for the dashboard.

    `cost_usd` is the sum over INSTRUMENTED calls only. It is deliberately NOT
    called a total platform cost: the coverage fields report that some paths are
    still unaccounted, and `cost_unknown_calls` reports calls whose provider
    returned no usage block. Both are surfaced rather than hidden so the number
    is never mistaken for complete.

    Coverage field naming is scoped on purpose. Usage-observation and pricing
    can only ever be measured over calls this module actually saw, so reporting
    either as a bare "complete" while UNINSTRUMENTED_PATHS is non-empty reads as
    a claim about the whole platform that the data does not support. The two
    per-path fields therefore carry an `instrumented_path_` prefix, and the only
    field that speaks for the platform is `global_instrumentation_coverage`,
    which stays "partial" until every call site is routed through here.
    """
    rows = read_usage() if rows is None else rows
    known = [r for r in rows if r.get("cost_known")]

    by_job: dict[str, dict[str, Any]] = {}
    for r in rows:
        job = r.get("job_id") or "unknown"
        entry = by_job.setdefault(job, {"calls": 0, "cost_usd": 0.0, "cost_known_calls": 0})
        entry["calls"] += 1
        if r.get("cost_known"):
            entry["cost_usd"] = round(entry["cost_usd"] + (r.get("cost_usd") or 0), 6)
            entry["cost_known_calls"] += 1

    return {
        "calls": len(rows),
        "failed_calls": sum(1 for r in rows if not r.get("ok")),
        "input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
        "output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
        "estimated_instrumented_cost_usd": round(sum(r.get("cost_usd") or 0 for r in known), 4),
        "cost_known_calls": len(known),
        "cost_unknown_calls": len(rows) - len(known),
        # Three independent coverage questions. A single "cost_coverage" field
        # conflated them and let a partial figure read as authoritative.
        #   global_instrumentation            — are all call sites routed here?
        #   instrumented_path_usage_observation — did the provider report tokens
        #                                       on the calls we did see?
        #   instrumented_path_pricing         — do we hold a price for every
        #                                       model we did see?
        # Only the first speaks for the platform; the other two are explicitly
        # scoped to instrumented calls so neither can be read as a global claim.
        "global_instrumentation_coverage": "partial" if UNINSTRUMENTED_PATHS else "complete",
        "instrumented_path_usage_observation_coverage": (
            "complete" if len(known) == len(rows) else "partial"
        ),
        "instrumented_path_pricing_coverage": _pricing_coverage(rows),
        "uninstrumented_paths": list(UNINSTRUMENTED_PATHS),
        "unpriced_models": sorted({r.get("model") for r in rows
                                   if r.get("model") and r["model"] not in PRICING}),
        "pricing_version": PRICING_VERSION,
        "by_job": by_job,
    }


def _pricing_coverage(rows: list[dict[str, Any]]) -> str:
    models = {r.get("model") for r in rows if r.get("model")}
    if not models:
        return "unknown"
    return "complete" if all(m in PRICING for m in models) else "partial"


def job_cost(job_id: str, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per-lane cost, e.g. estimated_measured_news_generation_cost.

    Scoped to one job_id so a measured figure is never presented as the
    platform total.
    """
    rows = [r for r in (read_usage() if rows is None else rows)
            if r.get("job_id") == job_id]
    known = [r for r in rows if r.get("cost_known")]
    return {
        "job_id": job_id,
        "calls": len(rows),
        f"estimated_measured_{job_id}_cost_usd": round(
            sum(r.get("cost_usd") or 0 for r in known), 4),
        "cost_known_calls": len(known),
        "cost_unknown_calls": len(rows) - len(known),
        "usage_observation_coverage": "complete" if len(known) == len(rows) else "partial",
        "pricing_coverage": _pricing_coverage(rows),
        "pricing_version": PRICING_VERSION,
    }
