"""Phase 0.5 stabilization — bounds on agent/feed.py LLM enrichment.

Context these tests exist to protect: `feed_run` is a *scheduled* job (every 3h,
`agent/automation.py`), and enrichment makes two calls per item. Before the
Phase 0.5 fix `_llm_chat` raised NameError on every call and a bare
`except Exception: pass` swallowed it, so this path made zero requests in
production. Turning it on is a real increase in request volume, and these tests
pin the ceilings that keep it bounded.

The seam under test is `feed._llm_chat` — the single function that reaches the
provider. Counting calls there is what makes "zero LLM requests" a claim about
the wire, not about a mock two layers up.
"""
import json
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from agent import feed as FEED  # noqa: E402
from agent import llm_ops as LLM  # noqa: E402


class CountingLLM:
    """Stands in for feed._llm_chat and records every call."""

    def __init__(self, reply="GENERATED", fail_on=None, empty=False):
        self.calls = []
        self._reply, self._fail_on, self._empty = reply, fail_on or set(), empty

    def __call__(self, prompt, config):
        self.calls.append(prompt)
        for needle in self._fail_on:
            if needle in prompt:
                raise RuntimeError(f"provider exploded on {needle!r}")
        return "" if self._empty else self._reply

    @property
    def count(self):
        return len(self.calls)


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


PRICED_CONFIG = SimpleNamespace(
    api_key="k", provider="openai", model="gpt-4o", base_url=None,
)
UNPRICED_CONFIG = SimpleNamespace(
    api_key="k", provider="ollama", model="kimi-k2.7-code:cloud",
    base_url="http://localhost:11434/v1",
)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Redirect every file the enrichment pass touches, and clear env bounds."""
    monkeypatch.setattr(FEED, "FEED_DIR", tmp_path)
    monkeypatch.setattr(FEED, "ENRICHMENT_CACHE_PATH", tmp_path / "enrichment_cache.json")
    monkeypatch.setattr(FEED, "ENRICHMENT_LOG_PATH", tmp_path / "enrichment_log.jsonl")
    monkeypatch.setattr(LLM, "USAGE_LEDGER", tmp_path / "llm_usage.jsonl")
    # config/feed.yaml must not leak real settings into these assertions.
    monkeypatch.setattr(FEED, "_load_feed_config", lambda: {})
    for var in ("FEED_LLM_ENRICHMENT_ENABLED", "FEED_LLM_MAX_ITEMS_PER_RUN",
                "FEED_LLM_DAILY_BUDGET_USD"):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def use_config(monkeypatch):
    def _apply(cfg=PRICED_CONFIG):
        monkeypatch.setattr("agent.config.AgentConfig.load", staticmethod(lambda: cfg))
    return _apply


def log_actions(tmp_path):
    path = tmp_path / "enrichment_log.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln)["action"] for ln in path.read_text().splitlines() if ln.strip()]


# ── 1. the happy path actually populates both fields ────────────────────────

def test_successful_llm_response_populates_summary_and_reason(monkeypatch, use_config):
    """The Phase 0.5 fix must stay fixed: NameError here meant empty summaries."""
    use_config()
    llm = CountingLLM(reply="A real summary.")
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    items = FEED._summarize_top(make_items(1), {"tone": "practical"})

    assert items[0].summary == "A real summary."
    assert items[0].reason == "A real summary."  # same stub answers both prompts
    assert llm.count == 2  # summary + reason
    stats = FEED.last_enrichment_stats()
    assert stats.enriched == 1 and stats.failed == 0


# ── 2. failure preserves the deterministic fallback ─────────────────────────

def test_llm_failure_preserves_deterministic_fallback(monkeypatch, use_config):
    use_config()
    monkeypatch.setattr(FEED, "_llm_chat", CountingLLM(fail_on={"Summarize"}))

    items = FEED._summarize_top(make_items(1), {})

    assert items[0].summary == ""                                  # no fake summary
    assert items[0].reason == "deterministic ranker reason 0"      # ranker survives
    assert FEED.last_enrichment_stats().failed == 1
    assert "error" in log_actions(FEED.ENRICHMENT_LOG_PATH.parent)


def test_an_empty_completion_is_a_failure_not_a_successful_summary(monkeypatch, use_config):
    """A 200 with blank content must not cache as a valid summary."""
    use_config()
    monkeypatch.setattr(FEED, "_llm_chat", CountingLLM(empty=True))

    items = FEED._summarize_top(make_items(1), {})

    assert items[0].summary == ""
    assert items[0].reason == "deterministic ranker reason 0"
    assert FEED.last_enrichment_stats().enriched == 0
    assert FEED.last_enrichment_stats().failed == 1
    assert not FEED.ENRICHMENT_CACHE_PATH.exists()  # nothing cached


def test_a_reason_failure_still_keeps_the_summary(monkeypatch, use_config):
    """Losing the second call must not throw away the first call's result."""
    use_config()
    monkeypatch.setattr(FEED, "_llm_chat", CountingLLM(reply="S", fail_on={"why this article matters"}))

    items = FEED._summarize_top(make_items(1), {})

    assert items[0].summary == "S"
    assert items[0].reason == "deterministic ranker reason 0"
    assert FEED.last_enrichment_stats().enriched == 1


# ── 3. unchanged items are not re-summarized ────────────────────────────────

def test_unchanged_items_do_not_trigger_another_llm_request(monkeypatch, use_config):
    """feed_run uses include_seen=True, so the same stories recur every 3h."""
    use_config()
    llm = CountingLLM(reply="cached me")
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    FEED._summarize_top(make_items(2), {})
    assert llm.count == 4  # 2 items x 2 calls

    # Second run, same source content -> fingerprints match -> no new requests.
    second = FEED._summarize_top(make_items(2), {})

    assert llm.count == 4, "unchanged items must not be re-summarized"
    assert second[0].summary == "cached me"
    assert second[0].reason == "cached me"
    stats = FEED.last_enrichment_stats()
    assert stats.cache_hits == 2 and stats.llm_calls == 0
    assert log_actions(FEED.ENRICHMENT_LOG_PATH.parent).count("unchanged") == 2


def test_changed_source_content_does_invalidate_the_cache(monkeypatch, use_config):
    """The fingerprint must track the content, or edits would never refresh."""
    use_config()
    llm = CountingLLM()
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    FEED._summarize_top(make_items(1), {})
    changed = make_items(1)
    changed[0].title = "Story 0 — updated headline"
    FEED._summarize_top(changed, {})

    assert llm.count == 4  # both runs called the provider


# ── 4. per-run item cap ─────────────────────────────────────────────────────

def test_the_per_run_item_limit_is_enforced(monkeypatch, use_config):
    use_config()
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "2")
    llm = CountingLLM()
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    FEED._summarize_top(make_items(6), {})

    assert llm.count == 4, "2 items x 2 calls, the other 4 items skipped"
    stats = FEED.last_enrichment_stats()
    assert stats.enriched == 2 and stats.skipped_item_limit == 4
    assert log_actions(FEED.ENRICHMENT_LOG_PATH.parent).count("item_limit") == 4


def test_the_default_cap_matches_the_documented_production_default(monkeypatch, use_config):
    use_config()
    llm = CountingLLM()
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    FEED._summarize_top(make_items(20), {})

    assert FEED.DEFAULT_MAX_ITEMS_PER_RUN == 5
    assert llm.count == 10, "5 items x 2 calls is the documented per-run ceiling"


def test_a_failed_item_still_counts_against_the_cap(monkeypatch, use_config):
    """A failure costs provider quota, so it must not buy a free retry slot."""
    use_config()
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "2")
    llm = CountingLLM(fail_on={"Summarize"})
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    FEED._summarize_top(make_items(5), {})

    assert llm.count == 2, "two attempts, both failed, cap still spent"
    assert FEED.last_enrichment_stats().skipped_item_limit == 3


# ── 5. daily budget ─────────────────────────────────────────────────────────

def write_ledger_row(cost_usd, job_id=FEED.ENRICHMENT_JOB_ID):
    import datetime as dt

    row = {
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "job_id": job_id, "model": "gpt-4o", "cost_usd": cost_usd,
        "cost_known": True, "ok": True,
    }
    LLM.USAGE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LLM.USAGE_LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_the_daily_budget_is_enforced(monkeypatch, use_config):
    use_config(PRICED_CONFIG)  # gpt-4o is in the price table -> budget can bind
    monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.50")
    write_ledger_row(0.75)  # already over budget for today
    llm = CountingLLM()
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    FEED._summarize_top(make_items(4), {})

    assert llm.count == 0, "over budget means no provider calls at all"
    stats = FEED.last_enrichment_stats()
    assert stats.budget_enforceable is True
    assert stats.skipped_budget == 4 and stats.enriched == 0
    assert log_actions(FEED.ENRICHMENT_LOG_PATH.parent).count("budget") == 4


def test_spend_under_the_budget_still_enriches(monkeypatch, use_config):
    use_config(PRICED_CONFIG)
    monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.50")
    write_ledger_row(0.10)
    llm = CountingLLM()
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    FEED._summarize_top(make_items(1), {})

    assert llm.count == 2
    assert FEED.last_enrichment_stats().skipped_budget == 0


def test_another_lanes_spend_does_not_consume_the_feed_budget(monkeypatch, use_config):
    use_config(PRICED_CONFIG)
    monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.50")
    write_ledger_row(5.00, job_id="news_publish")
    monkeypatch.setattr(FEED, "_llm_chat", CountingLLM())

    FEED._summarize_top(make_items(1), {})

    assert FEED.last_enrichment_stats().skipped_budget == 0


def test_an_unpriced_model_reports_the_budget_as_unenforceable(monkeypatch, use_config):
    """Honesty rule: never let unknown cost silently pass as $0 spent.

    The live config runs ollama `kimi-k2.7-code:cloud`, which has no price entry,
    so the ledger records cost as unknown. Treating that as $0 would let an
    unlimited number of calls pass a budget check. The run is still bounded — by
    the per-run item cap — but the budget must not *claim* to be enforcing.
    """
    use_config(UNPRICED_CONFIG)
    monkeypatch.setenv("FEED_LLM_DAILY_BUDGET_USD", "0.00")
    llm = CountingLLM()
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    FEED._summarize_top(make_items(3), {})

    stats = FEED.last_enrichment_stats()
    assert stats.budget_enforceable is False
    assert stats.skipped_budget == 0
    assert llm.count == 6, "still bounded by the item cap, not by the budget"


# ── 6. the kill switch ──────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_disabled_enrichment_makes_zero_llm_requests(monkeypatch, use_config, value):
    use_config()
    monkeypatch.setenv("FEED_LLM_ENRICHMENT_ENABLED", value)
    llm = CountingLLM()
    monkeypatch.setattr(FEED, "_llm_chat", llm)

    items = FEED._summarize_top(make_items(5), {})

    assert llm.count == 0
    assert all(i.summary == "" for i in items)
    assert all(i.reason.startswith("deterministic") for i in items)
    stats = FEED.last_enrichment_stats()
    assert stats.enabled is False and stats.llm_calls == 0
    assert log_actions(FEED.ENRICHMENT_LOG_PATH.parent).count("disabled") == 5


def test_enrichment_defaults_to_enabled(monkeypatch, use_config):
    """Documented production default — the summaries are the point of the feed."""
    use_config()
    monkeypatch.setattr(FEED, "_llm_chat", CountingLLM())

    FEED._summarize_top(make_items(1), {})

    assert FEED.DEFAULT_ENRICHMENT_ENABLED is True
    assert FEED.last_enrichment_stats().enabled is True


# ── 7. one bad item never ends the run ──────────────────────────────────────

def test_a_single_failed_item_does_not_terminate_the_feed_run(monkeypatch, use_config):
    use_config()
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "5")

    class FlakyOnStory1(CountingLLM):
        def __call__(self, prompt, config):
            self.calls.append(prompt)
            if "Story 1" in prompt:
                raise RuntimeError("boom")
            return "ok summary"

    monkeypatch.setattr(FEED, "_llm_chat", FlakyOnStory1())

    items = FEED._summarize_top(make_items(3), {})

    assert items[0].summary == "ok summary"
    assert items[1].summary == ""                               # the failed one
    assert items[1].reason == "deterministic ranker reason 1"
    assert items[2].summary == "ok summary"                     # run continued
    stats = FEED.last_enrichment_stats()
    assert stats.enriched == 2 and stats.failed == 1


def test_build_feed_survives_an_enrichment_failure(monkeypatch, use_config):
    """End to end: a provider outage degrades the feed, it does not break it."""
    use_config()
    monkeypatch.setattr(FEED, "_llm_chat", CountingLLM(fail_on={"Summarize"}))
    monkeypatch.setattr(FEED, "load_seen", lambda: {"urls": {}, "ttl_days": 30})
    monkeypatch.setattr(FEED, "mark_seen", lambda *a, **k: None)
    monkeypatch.setattr(FEED, "load_profile_with_interests",
                        lambda name="default": {"interests": ["python"]})
    monkeypatch.setattr(FEED, "get_feed_sources", lambda profile: ["hackernews"])
    # Distinct wording: dedupe_items collapses titles with high word overlap,
    # so "Story 0/1/2" would arrive at the ranker as a single item.
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
    # rank_items writes its own deterministic reason; the point is that it
    # survives the provider outage rather than being blanked by a failed call.
    assert all(i.reason for i in items)
    assert FEED.last_enrichment_stats().failed == 3


# ── configuration resolution ────────────────────────────────────────────────

def test_env_overrides_the_yaml_block(monkeypatch):
    monkeypatch.setattr(FEED, "_load_feed_config",
                        lambda: {"llm": {"enabled": False, "max_items_per_run": 99,
                                         "daily_budget_usd": 9.0}})
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "3")

    settings = FEED.enrichment_settings()

    assert settings["max_items_per_run"] == 3   # env wins
    assert settings["enabled"] is False         # yaml still applies where env is absent
    assert settings["daily_budget_usd"] == 9.0


def test_a_malformed_bound_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("FEED_LLM_MAX_ITEMS_PER_RUN", "not-a-number")

    assert FEED.enrichment_settings()["max_items_per_run"] == FEED.DEFAULT_MAX_ITEMS_PER_RUN
