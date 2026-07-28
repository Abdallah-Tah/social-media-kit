"""Bounds and validation for agent/feed.py LLM enrichment.

`feed_run` is a *scheduled* job (every 3h, agent/automation.py), so anything
per-item multiplies by 8 runs/day forever. These tests pin the ceilings.

The seam is `llm_ops.requests.post` — the actual HTTP boundary. Counting there
is what makes "exactly one wire request per item" a claim about the wire rather
than about a mock two layers up, and it exercises llm_ops's real payload
construction, ledger write, and finish_reason handling on the way through.

History worth keeping in view: enrichment made TWO free-text calls per item
against kimi-k2.7-code:cloud at 256 max_tokens. That model is a reasoning model
whose reasoning shares the completion budget, so 6 of 10 live attempts came back
finish_reason=length with truncated or empty content. Hence the dedicated
non-reasoning model, the single structured request, and the truncation checks.
"""
import json
import os
import sys

import pytest
import requests as REQUESTS

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from agent import feed as FEED  # noqa: E402
from agent import llm_ops as LLM  # noqa: E402

GOOD_SUMMARY = "Python Build Standalone ships self-contained CPython builds for Linux and macOS."
GOOD_REASON = "It removes the system-Python dependency when shipping CLI tools."


def body(summary=GOOD_SUMMARY, reason=GOOD_REASON):
    return json.dumps({"summary": summary, "reason": reason})


class FakeResponse:
    def __init__(self, content="", ok=True, status=200, finish_reason="stop", usage=True):
        self._content, self.ok, self.status_code = content, ok, status
        self.text = content
        self._finish, self._usage = finish_reason, usage

    def json(self):
        out = {"choices": [{"message": {"content": self._content},
                            "finish_reason": self._finish}]}
        if self._usage:
            out["usage"] = {"prompt_tokens": 120, "completion_tokens": 80}
        return out


class Wire:
    """Records every HTTP call. `script` may hold responses or exceptions."""

    def __init__(self, *script):
        self.calls = []
        self._script = list(script) or [FakeResponse(body())]

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        item = self._script[min(len(self.calls) - 1, len(self._script) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item

    @property
    def count(self):
        return len(self.calls)

    @property
    def payload(self):
        return self.calls[-1]["json"]


def make_items(n=6, summary=""):
    return [
        FEED.FeedItem(
            title=f"Story {i}",
            url=f"https://example.com/story-{i}",
            source="hackernews",
            summary=summary,
            reason=f"deterministic ranker reason {i}",
            matched_interests=["python"],
        )
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(FEED, "FEED_DIR", tmp_path)
    monkeypatch.setattr(FEED, "ENRICHMENT_CACHE_PATH", tmp_path / "enrichment_cache.json")
    monkeypatch.setattr(FEED, "ENRICHMENT_LOG_PATH", tmp_path / "enrichment_log.jsonl")
    monkeypatch.setattr(LLM, "USAGE_LEDGER", tmp_path / "llm_usage.jsonl")
    monkeypatch.setattr(FEED, "_load_feed_config", lambda: {})
    for var in ("FEED_LLM_ENRICHMENT_ENABLED", "FEED_LLM_MAX_ITEMS_PER_RUN",
                "FEED_LLM_DAILY_BUDGET_USD", "FEED_LLM_PROVIDER", "FEED_LLM_MODEL",
                "FEED_LLM_BASE_URL", "FEED_LLM_MAX_TOKENS", "FEED_LLM_JSON_MODE",
                "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    # Credentials come from the environment, never hardcoded in the module.
    monkeypatch.setenv("FEED_LLM_API_KEY", "test-key")
    yield


def wire(monkeypatch, *script):
    w = Wire(*script)
    monkeypatch.setattr(LLM, "requests", type("R", (), {"post": staticmethod(w)}))
    return w


def actions(tmp_path):
    path = tmp_path / "enrichment_log.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln)["action"] for ln in path.read_text().splitlines() if ln.strip()]


def details(tmp_path):
    path = tmp_path / "enrichment_log.jsonl"
    return [json.loads(ln).get("detail") or "" for ln in path.read_text().splitlines()
            if ln.strip()]


# ── the dedicated feed model ────────────────────────────────────────────────

def test_feed_uses_its_own_model_not_the_agent_loop_model(monkeypatch, tmp_path):
    """The agent loop runs kimi; feed enrichment must not inherit it."""
    w = wire(monkeypatch)
    FEED._summarize_top(make_items(1), {})

    assert w.payload["model"] == "gpt-4o-mini"
    assert w.calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert w.calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert FEED.last_enrichment_stats().model == "gpt-4o-mini"
    assert FEED.last_enrichment_stats().provider == "openai"


def test_config_precedence_env_then_yaml_then_default(monkeypatch):
    monkeypatch.setattr(FEED, "_load_feed_config",
                        lambda: {"llm": {"provider": "ollama", "model": "yaml-model",
                                         "max_tokens": 999}})
    monkeypatch.setenv("FEED_LLM_MODEL", "env-model")

    cfg = FEED.feed_llm_config()

    assert cfg.model == "env-model"      # env wins
    assert cfg.provider == "ollama"      # yaml applies where env is absent
    assert cfg.max_tokens == 999
    assert FEED.DEFAULT_FEED_LLM_MODEL == "gpt-4o-mini"   # documented default
    assert FEED.DEFAULT_FEED_LLM_PROVIDER == "openai"


def test_json_object_mode_is_requested(monkeypatch):
    w = wire(monkeypatch)
    FEED._summarize_top(make_items(1), {})
    assert w.payload["response_format"] == {"type": "json_object"}


def test_json_mode_can_be_disabled_for_providers_that_lack_it(monkeypatch):
    monkeypatch.setenv("FEED_LLM_JSON_MODE", "false")
    w = wire(monkeypatch)
    FEED._summarize_top(make_items(1), {})
    assert "response_format" not in w.payload


# ── one request, both fields ────────────────────────────────────────────────

def test_one_request_produces_both_summary_and_reason(monkeypatch):
    w = wire(monkeypatch)

    items = FEED._summarize_top(make_items(1), {"tone": "practical"})

    assert w.count == 1, "summary and reason must come from a single request"
    assert items[0].summary == GOOD_SUMMARY
    assert items[0].reason == GOOD_REASON
    stats = FEED.last_enrichment_stats()
    assert stats.enriched == 1 and stats.llm_calls == 1


def test_exactly_one_wire_request_per_attempted_item(monkeypatch):
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "3")
    w = wire(monkeypatch)

    FEED._summarize_top(make_items(6), {})

    assert w.count == 3, "3 attempted items -> 3 requests, never 6"
    assert FEED.last_enrichment_stats().llm_calls == 3


def test_a_valid_structured_response_is_stored_in_the_cache(monkeypatch, tmp_path):
    wire(monkeypatch)
    FEED._summarize_top(make_items(1), {})

    cache = json.loads((tmp_path / "enrichment_cache.json").read_text())
    entry = next(iter(cache.values()))
    assert entry["summary"] == GOOD_SUMMARY
    assert entry["reason"] == GOOD_REASON
    assert entry["model"] == "gpt-4o-mini"
    assert entry["schema_version"] == FEED.ENRICHMENT_SCHEMA_VERSION


def test_the_fingerprint_is_versioned_so_the_v1_cache_cannot_be_served(monkeypatch):
    """The prompt and response schema changed; old entries must not match."""
    assert FEED.ENRICHMENT_SCHEMA_VERSION == 2
    item = make_items(1)[0]
    fp_v2 = FEED.enrichment_fingerprint(item)
    monkeypatch.setattr(FEED, "ENRICHMENT_SCHEMA_VERSION", 1)
    assert FEED.enrichment_fingerprint(item) != fp_v2


# ── validation failures, all degrade safely ─────────────────────────────────

BAD_RESPONSES = [
    pytest.param(FakeResponse("not json at all"), "EnrichmentMalformed", id="malformed-json"),
    pytest.param(FakeResponse('["a","b"]'), "EnrichmentMalformed", id="json-array"),
    pytest.param(FakeResponse('{"summary":"x"}'), "EnrichmentMalformed", id="missing-reason"),
    pytest.param(FakeResponse(body(summary="")), "EnrichmentEmpty", id="blank-summary"),
    pytest.param(FakeResponse(body(reason="")), "EnrichmentEmpty", id="blank-reason"),
    pytest.param(FakeResponse(body(), finish_reason="length"), "EnrichmentTruncated",
                 id="finish-reason-length"),
    pytest.param(FakeResponse(body(summary="This sentence just stops mid")),
                 "EnrichmentTruncated", id="unfinished-summary"),
    pytest.param(FakeResponse(body(reason="Because it")), "EnrichmentTruncated",
                 id="unfinished-reason"),
    pytest.param(FakeResponse(body(summary="A" * 401 + ".")), "EnrichmentInvalid",
                 id="summary-too-long"),
    pytest.param(FakeResponse(body(reason="Important.")), "EnrichmentInvalid",
                 id="stub-reason"),
    pytest.param(FakeResponse(body(reason=GOOD_SUMMARY)), "EnrichmentInvalid",
                 id="reason-echoes-summary"),
    pytest.param(FakeResponse("", ok=False, status=500), "EnrichmentError", id="http-500"),
    pytest.param(REQUESTS.ConnectionError("no route to host"), "EnrichmentError",
                 id="network-error"),
]


@pytest.mark.parametrize("response,expected_error", BAD_RESPONSES)
def test_bad_responses_preserve_deterministic_content(monkeypatch, tmp_path,
                                                      response, expected_error):
    """No fabricated summary, ranker reason intact, nothing cached, reason logged."""
    wire(monkeypatch, response)

    items = FEED._summarize_top(make_items(1), {})

    assert items[0].summary == "", "a failed attempt must not write a summary"
    assert items[0].reason == "deterministic ranker reason 0"
    stats = FEED.last_enrichment_stats()
    assert stats.enriched == 0 and stats.failed == 1
    assert not FEED.ENRICHMENT_CACHE_PATH.exists(), "failures must never be cached"
    assert "error" in actions(tmp_path)
    assert expected_error in " ".join(details(tmp_path))


def test_a_failed_item_is_retried_on_the_next_run(monkeypatch):
    """Nothing was cached, so the next run gets another chance."""
    w = wire(monkeypatch, FakeResponse("not json"), FakeResponse(body()))

    FEED._summarize_top(make_items(1), {})
    items = FEED._summarize_top(make_items(1), {})

    assert w.count == 2
    assert items[0].summary == GOOD_SUMMARY


# ── cache ───────────────────────────────────────────────────────────────────

def test_unchanged_items_use_the_cache(monkeypatch, tmp_path):
    """feed_run uses include_seen=True, so the same stories recur every 3h."""
    w = wire(monkeypatch)

    FEED._summarize_top(make_items(2), {})
    assert w.count == 2

    second = FEED._summarize_top(make_items(2), {})

    assert w.count == 2, "unchanged items must not be re-requested"
    assert second[0].summary == GOOD_SUMMARY
    assert second[0].reason == GOOD_REASON
    stats = FEED.last_enrichment_stats()
    assert stats.cache_hits == 2 and stats.llm_calls == 0
    assert actions(tmp_path).count("unchanged") == 2


def test_changed_source_content_invalidates_the_cache(monkeypatch):
    w = wire(monkeypatch)

    FEED._summarize_top(make_items(1), {})
    changed = make_items(1)
    changed[0].title = "Story 0 — updated headline"
    FEED._summarize_top(changed, {})

    assert w.count == 2


# ── per-run cap ─────────────────────────────────────────────────────────────

def test_the_default_cap_allows_at_most_five_requests_per_run(monkeypatch):
    w = wire(monkeypatch)

    FEED._summarize_top(make_items(20), {})

    assert FEED.DEFAULT_MAX_ITEMS_PER_RUN == 5
    assert FEED.LLM_CALLS_PER_ITEM == 1
    assert w.count == 5, "5 items x 1 request = the per-run ceiling"
    assert FEED.last_enrichment_stats().skipped_item_limit == 15


def test_the_scheduled_daily_ceiling_is_forty_requests():
    """8 runs/day (interval_hours=3) x 5 items x 1 request."""
    runs_per_day = 24 // 3
    assert runs_per_day * FEED.DEFAULT_MAX_ITEMS_PER_RUN * FEED.LLM_CALLS_PER_ITEM == 40


def test_the_per_run_item_limit_is_enforced(monkeypatch, tmp_path):
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "2")
    w = wire(monkeypatch)

    FEED._summarize_top(make_items(6), {})

    assert w.count == 2
    stats = FEED.last_enrichment_stats()
    assert stats.enriched == 2 and stats.skipped_item_limit == 4
    assert actions(tmp_path).count("item_limit") == 4


def test_a_failed_item_still_counts_against_the_cap(monkeypatch):
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "2")
    w = wire(monkeypatch, FakeResponse("not json"))

    FEED._summarize_top(make_items(5), {})

    assert w.count == 2, "a failure burns quota, so it spends a slot"
    assert FEED.last_enrichment_stats().skipped_item_limit == 3


# ── daily budget ────────────────────────────────────────────────────────────

def write_ledger_row(cost_usd, job_id=FEED.ENRICHMENT_JOB_ID, model="gpt-4o-mini"):
    import time

    # Stamped exactly as llm_ops._record does: LOCAL time with an offset.
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "job_id": job_id, "model": model, "cost_usd": cost_usd,
        "cost_known": True, "ok": True,
    }
    LLM.USAGE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LLM.USAGE_LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_the_daily_budget_is_enforced(monkeypatch, tmp_path):
    """gpt-4o-mini is priced, so unlike the old kimi model the budget binds."""
    monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.50")
    write_ledger_row(0.75)
    w = wire(monkeypatch)

    FEED._summarize_top(make_items(4), {})

    assert w.count == 0, "over budget means no requests at all"
    stats = FEED.last_enrichment_stats()
    assert stats.budget_enforceable is True
    assert stats.skipped_budget == 4 and stats.enriched == 0
    assert actions(tmp_path).count("budget") == 4


def test_spend_is_read_on_the_same_clock_the_ledger_is_written_with(monkeypatch):
    """Regression: a UTC 'today' against locally-stamped rows read $0.

    Caught in live verification at 20:40 EDT — the UTC date was already the next
    day, so the budget window matched nothing and stopped binding for the last
    four hours of every day. Reproduced by pushing the local zone west so local
    and UTC dates differ.
    """
    import time

    monkeypatch.setenv("TZ", "Pacific/Honolulu")  # UTC-10, no DST
    time.tzset()
    try:
        monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.50")
        write_ledger_row(0.75)
        w = wire(monkeypatch)

        FEED._summarize_top(make_items(2), {})

        assert FEED._spend_today() == 0.75, "today's spend must be visible"
        assert w.count == 0, "over budget, regardless of local/UTC date skew"
        assert FEED.last_enrichment_stats().skipped_budget == 2
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()


def test_spend_under_the_budget_still_enriches(monkeypatch):
    monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.50")
    write_ledger_row(0.10)
    w = wire(monkeypatch)

    FEED._summarize_top(make_items(1), {})

    assert w.count == 1
    assert FEED.last_enrichment_stats().skipped_budget == 0


def test_another_lanes_spend_does_not_consume_the_feed_budget(monkeypatch):
    monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.50")
    write_ledger_row(5.00, job_id="news_publish")
    wire(monkeypatch)

    FEED._summarize_top(make_items(1), {})

    assert FEED.last_enrichment_stats().skipped_budget == 0


def test_an_unpriced_model_reports_the_budget_as_unenforceable(monkeypatch):
    """Honesty rule: unknown cost must never silently pass as $0 spent."""
    monkeypatch.setenv("FEED_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("FEED_LLM_MODEL", "kimi-k2.7-code:cloud")
    monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.00")
    w = wire(monkeypatch)

    FEED._summarize_top(make_items(3), {})

    stats = FEED.last_enrichment_stats()
    assert stats.budget_enforceable is False
    assert stats.skipped_budget == 0
    assert w.count == 3, "still bounded by the item cap, not by the budget"


# ── kill switch ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_disabled_enrichment_makes_zero_requests(monkeypatch, tmp_path, value):
    monkeypatch.setenv("FEED_LLM_ENRICHMENT_ENABLED", value)
    w = wire(monkeypatch)

    items = FEED._summarize_top(make_items(5), {})

    assert w.count == 0
    assert all(i.summary == "" for i in items)
    assert all(i.reason.startswith("deterministic") for i in items)
    assert FEED.last_enrichment_stats().enabled is False
    assert actions(tmp_path).count("disabled") == 5


def test_enrichment_defaults_to_enabled(monkeypatch):
    wire(monkeypatch)
    FEED._summarize_top(make_items(1), {})
    assert FEED.DEFAULT_ENRICHMENT_ENABLED is True
    assert FEED.last_enrichment_stats().enabled is True


# ── one bad item never ends the run ─────────────────────────────────────────

def test_processing_continues_after_a_single_failure(monkeypatch):
    w = wire(monkeypatch,
             FakeResponse(body()),
             FakeResponse("not json"),        # item 1 fails
             FakeResponse(body()))

    items = FEED._summarize_top(make_items(3), {})

    assert w.count == 3
    assert items[0].summary == GOOD_SUMMARY
    assert items[1].summary == ""                              # the failed one
    assert items[1].reason == "deterministic ranker reason 1"
    assert items[2].summary == GOOD_SUMMARY                    # run continued
    stats = FEED.last_enrichment_stats()
    assert stats.enriched == 2 and stats.failed == 1


def test_build_feed_survives_a_total_provider_outage(monkeypatch):
    wire(monkeypatch, REQUESTS.ConnectionError("provider down"))
    monkeypatch.setattr(FEED, "load_seen", lambda: {"urls": {}, "ttl_days": 30})
    monkeypatch.setattr(FEED, "mark_seen", lambda *a, **k: None)
    monkeypatch.setattr(FEED, "load_profile_with_interests",
                        lambda name="default": {"interests": ["python"]})
    monkeypatch.setattr(FEED, "get_feed_sources", lambda profile: ["hackernews"])
    fetched = [
        FEED.FeedItem(title=t, url=f"https://example.com/{i}", source="hackernews")
        for i, t in enumerate([
            "Python packaging finally gets a lockfile",
            "Rust adoption climbs in embedded firmware",
            "Postgres 19 ships incremental backups",
        ])
    ]
    import scripts.feed_sources as SOURCES
    monkeypatch.setattr(SOURCES, "fetch_all", lambda sources, topic=None: list(fetched))

    items = FEED.build_feed(limit=3, use_llm=True)

    assert len(items) == 3
    assert all(i.summary == "" for i in items), "no fabricated summaries"
    assert all(i.reason for i in items), "deterministic reasons survive"
    assert FEED.last_enrichment_stats().failed == 3


# ── bounds configuration ────────────────────────────────────────────────────

def test_env_overrides_the_yaml_block(monkeypatch):
    monkeypatch.setattr(FEED, "_load_feed_config",
                        lambda: {"llm": {"enabled": False, "max_items_per_run": 99,
                                         "daily_budget_usd": 9.0}})
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "3")

    settings = FEED.enrichment_settings()

    assert settings["max_items_per_run"] == 3
    assert settings["enabled"] is False
    assert settings["daily_budget_usd"] == 9.0


def test_a_malformed_bound_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "not-a-number")
    assert FEED.enrichment_settings()["max_items_per_run"] == FEED.DEFAULT_MAX_ITEMS_PER_RUN
