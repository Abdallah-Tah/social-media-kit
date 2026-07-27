"""Phase 0 — shared LLM client, usage ledger, and ContentDecision audit."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from agent import content_decisions as CD
from agent import llm_ops as LLM


class FakeResponse:
    def __init__(self, content="ok", ok=True, status=200, usage=True):
        self._content, self.ok, self.status_code = content, ok, status
        self.text = content
        self._usage = usage

    def json(self):
        body = {"choices": [{"message": {"content": self._content}}]}
        if self._usage:
            body["usage"] = {"prompt_tokens": 1000, "completion_tokens": 500,
                             "prompt_tokens_details": {"cached_tokens": 200}}
        return body


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(LLM, "USAGE_LEDGER", tmp_path / "llm_usage.jsonl")
    monkeypatch.setattr(CD, "DECISION_LOG", tmp_path / "decisions.jsonl")
    monkeypatch.setenv("OPENAI_API_KEY", "k")


# ── Cost accounting ────────────────────────────────────────────────────────

def test_cost_is_computed_from_the_price_table():
    # gpt-4o: $2.50/1M in, $10.00/1M out → 1M in + 1M out = $12.50
    cost, known = LLM.estimate_cost("gpt-4o", 1_000_000, 1_000_000)
    assert known is True
    assert cost == pytest.approx(12.50)


def test_cost_is_unknown_for_an_unpriced_model():
    cost, known = LLM.estimate_cost("some-new-model", 100, 100)
    assert (cost, known) == (None, False)


def test_cost_is_unknown_when_usage_is_missing_not_guessed(monkeypatch):
    """The provider omitting `usage` must never produce an invented cost."""
    monkeypatch.setattr(LLM.requests, "post",
                        lambda *a, **k: FakeResponse(usage=False))
    result = LLM.chat([{"role": "user", "content": "x"}], job_id="t")

    assert result.ok is True
    assert result.input_tokens is None and result.output_tokens is None
    assert result.cost_usd is None
    assert result.cost_known is False

    row = json.loads((LLM.USAGE_LEDGER).read_text().strip())
    assert row["cost_usd"] is None
    assert row["cost_known"] is False
    assert row["pricing_version"] is None


def test_successful_call_records_every_required_field(monkeypatch):
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse())
    LLM.chat([{"role": "user", "content": "x"}], model="gpt-4o",
             job_id="news_publish", content_id="slug-1")

    row = json.loads(LLM.USAGE_LEDGER.read_text().strip())
    for field in ("ts", "job_id", "content_id", "provider", "model", "input_tokens",
                  "output_tokens", "cached_tokens", "duration_ms", "cost_usd",
                  "ok", "status_code", "error_class"):
        assert field in row, f"ledger missing {field}"
    assert row["job_id"] == "news_publish"
    assert row["content_id"] == "slug-1"
    assert row["provider"] == "openai"
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] == 500
    assert row["cached_tokens"] == 200
    assert row["cost_known"] is True
    assert row["pricing_version"] == LLM.PRICING_VERSION


# ── Error classification (Phase 2 retry depends on this) ───────────────────

@pytest.mark.parametrize("status,expected", [
    (429, "transient"), (500, "transient"), (503, "transient"), (408, "transient"),
    (401, "permanent"), (403, "permanent"), (400, "permanent"), (404, "permanent"),
    (None, "unknown"),
])
def test_error_classification(status, expected):
    assert LLM.classify_error(status) == expected


def test_network_exception_is_transient():
    assert LLM.classify_error(None, TimeoutError("timed out")) == "transient"


def test_failed_call_is_recorded_with_classification(monkeypatch):
    monkeypatch.setattr(LLM.requests, "post",
                        lambda *a, **k: FakeResponse(content="rate limited", ok=False, status=429))
    result = LLM.chat([{"role": "user", "content": "x"}], job_id="t")

    assert result.ok is False
    assert result.error_class == "transient"
    row = json.loads(LLM.USAGE_LEDGER.read_text().strip())
    assert row["ok"] is False and row["error_class"] == "transient"


def test_network_error_does_not_propagate(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("dns")

    monkeypatch.setattr(LLM.requests, "post", boom)
    result = LLM.chat([{"role": "user", "content": "x"}], job_id="t")
    assert result.ok is False and result.error_class == "transient"


def test_raise_for_status_preserves_old_caller_semantics(monkeypatch):
    monkeypatch.setattr(LLM.requests, "post",
                        lambda *a, **k: FakeResponse(ok=False, status=500))
    result = LLM.chat([{"role": "user", "content": "x"}], job_id="t")
    with pytest.raises(LLM.LLMError):
        result.raise_for_status()


def test_ledger_failure_never_breaks_the_call(monkeypatch, tmp_path):
    """Accounting is best-effort; publishing must not depend on it."""
    monkeypatch.setattr(LLM, "USAGE_LEDGER", tmp_path / "nope" / "x" / "u.jsonl")
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(LLM.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert LLM.chat([{"role": "user", "content": "x"}], job_id="t").ok is True


def test_usage_summary_reports_unknown_cost_calls(monkeypatch):
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse())
    LLM.chat([{"role": "user", "content": "x"}], model="gpt-4o", job_id="t")
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse(usage=False))
    LLM.chat([{"role": "user", "content": "x"}], model="gpt-4o", job_id="t")

    s = LLM.usage_summary()
    assert s["calls"] == 2
    assert s["cost_known_calls"] == 1
    assert s["cost_unknown_calls"] == 1


def test_summary_never_claims_to_be_a_complete_platform_total(monkeypatch):
    """feed.py and shorts.py are not routed here yet — say so, don't imply total."""
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse())
    LLM.chat([{"role": "user", "content": "x"}], model="gpt-4o", job_id="news_publish")

    s = LLM.usage_summary()
    assert "cost_usd" not in s, "a bare 'cost_usd' total reads as platform-wide"
    assert "cost_coverage" not in s, "one blended coverage field conflates three questions"
    assert s["estimated_instrumented_cost_usd"] > 0
    assert s["global_instrumentation_coverage"] == "partial"
    # The two measurable axes must name their scope. An unqualified
    # "usage_observation_coverage": "complete" reads as a platform-wide claim
    # while uninstrumented paths remain.
    assert "usage_observation_coverage" not in s
    assert "pricing_coverage" not in s
    # Phase 0.5 migrated feed.py and shorts.py; the agent loop and the image
    # generator remain outside the ledger.
    assert "agent/feed.py" not in s["uninstrumented_paths"]
    assert "agent/shorts.py" not in s["uninstrumented_paths"]
    assert "agent/llm.py" in s["uninstrumented_paths"]
    assert s["by_job"]["news_publish"]["calls"] == 1


def test_the_three_coverage_axes_are_independent(monkeypatch):
    """Instrumentation, usage observation, and pricing can each be partial alone."""
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse())
    LLM.chat([{"role": "user", "content": "x"}], model="gpt-4o", job_id="t")
    s = LLM.usage_summary()
    assert s["instrumented_path_usage_observation_coverage"] == "complete"
    assert s["instrumented_path_pricing_coverage"] == "complete"  # gpt-4o is priced
    assert s["global_instrumentation_coverage"] == "partial"      # agent loop not routed
    assert s["unpriced_models"] == []


def test_an_unpriced_fallback_model_shows_up_as_partial_pricing(monkeypatch):
    """Gemini/Alibaba/Ollama fallbacks have no price entry — say so explicitly."""
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse())
    LLM.chat([{"role": "user", "content": "x"}], model="gemini-2.5-pro", job_id="t")

    s = LLM.usage_summary()
    assert s["instrumented_path_pricing_coverage"] == "partial"
    assert "gemini-2.5-pro" in s["unpriced_models"]
    assert s["instrumented_path_usage_observation_coverage"] == "partial"
    assert s["estimated_instrumented_cost_usd"] == 0


def test_priced_api_call_records_its_pricing_basis(monkeypatch):
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse())
    LLM.chat([{"role": "user", "content": "x"}], model="gpt-4o", job_id="t")
    row = json.loads(LLM.USAGE_LEDGER.read_text().strip())
    assert row["pricing_basis"] == LLM.PRICING_BASIS_API


def test_local_inference_is_never_described_as_free():
    """Ollama cost 0 must carry local_compute_excluded, not an unqualified zero."""
    assert LLM.PRICING_BASIS_LOCAL == "local_compute_excluded"
    assert "ollama" in LLM.KNOWN_UNPRICED_PROVIDERS


def test_job_cost_is_scoped_to_one_lane(monkeypatch):
    monkeypatch.setattr(LLM.requests, "post", lambda *a, **k: FakeResponse())
    LLM.chat([{"role": "user", "content": "x"}], model="gpt-4o", job_id="news_publish")
    LLM.chat([{"role": "user", "content": "x"}], model="gpt-4o", job_id="auto_publish")

    c = LLM.job_cost("news_publish")
    assert c["calls"] == 1
    assert c["estimated_measured_news_publish_cost_usd"] > 0
    assert c["usage_observation_coverage"] == "complete"
    assert c["pricing_coverage"] == "complete"


def test_json_mode_and_max_tokens_are_optional(monkeypatch):
    captured = {}

    def cap(url, **kw):
        captured.update(kw)
        return FakeResponse()

    monkeypatch.setattr(LLM.requests, "post", cap)
    LLM.chat([{"role": "user", "content": "x"}], job_id="t")
    assert "max_tokens" not in captured["json"]
    assert "response_format" not in captured["json"]


# ── ContentDecision audit ──────────────────────────────────────────────────

def test_accept_and_reject_are_appended():
    CD.accept("topic_admission", "news_publish", title="A", slug="a")
    CD.reject("topic_admission", "news_publish", "duplicate_slug", "already live", slug="b")

    rows = CD.read()
    assert [r["decision"] for r in rows] == ["accepted", "rejected"]
    assert rows[1]["reason_code"] == "duplicate_slug"
    assert rows[1]["reason"] == "already live"


def test_scores_are_stored_separately_not_blended():
    d = CD.accept("article_gate", "news_publish", source_confidence=80,
                  editorial_quality=72, publication_readiness="passed")
    assert d.source_confidence == 80
    assert d.editorial_quality == 72
    assert d.publication_readiness == "passed"
    row = CD.read()[-1]
    assert "confidence" not in row  # no single blended number


def test_invalid_records_are_rejected_loudly():
    with pytest.raises(ValueError):
        CD.ContentDecision(stage="nonsense", decision="accepted", job_id="j")
    with pytest.raises(ValueError):
        CD.ContentDecision(stage="publish", decision="maybe", job_id="j")
    with pytest.raises(ValueError):
        CD.ContentDecision(stage="publish", decision="accepted", job_id="j",
                           reason_code="not_a_real_code")
    with pytest.raises(ValueError):
        CD.ContentDecision(stage="publish", decision="accepted", job_id="j",
                           editorial_quality=101)
    with pytest.raises(ValueError):
        CD.ContentDecision(stage="publish", decision="accepted", job_id="j",
                           publication_readiness="probably")


def test_summary_counts_duplicates_prevented():
    CD.reject("topic_admission", "j", "duplicate_slug", slug="a")
    CD.reject("topic_admission", "j", "duplicate_topic", slug="b")
    CD.reject("article_gate", "j", "below_quality_threshold", editorial_quality=40)
    CD.accept("publish", "j", editorial_quality=80)

    s = CD.summary()
    assert s["decisions"] == 4
    assert s["accepted"] == 1 and s["rejected"] == 3
    assert s["duplicates_prevented"] == 2
    assert s["avg_editorial_quality"] == 60.0


def test_read_survives_a_corrupt_log(monkeypatch):
    CD.DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
    CD.DECISION_LOG.write_text("{not json\n", encoding="utf-8")
    assert CD.read() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
