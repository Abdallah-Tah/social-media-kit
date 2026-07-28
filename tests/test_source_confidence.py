"""Phase 1 Stage 2 — deterministic source-confidence scoring.

Scores the EVIDENCE only. Not the opportunity score, not editorial quality, not
an admission decision — this module returns a number and an explanation, and
nothing in it may publish, decide, or reach the network.
"""
import copy
import datetime as dt
import os
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agent.editorial import source_confidence as SC  # noqa: E402
from agent.editorial.source_confidence import (  # noqa: E402
    Candidate,
    Claim,
    ScoringConfigError,
    SourceRef,
    load_scoring_config,
    registrable_domain,
    score_source_confidence,
)

SHIPPED = os.path.join(ROOT, "config", "source_confidence.yaml")
NOW = dt.datetime(2026, 7, 27, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def config():
    return load_scoring_config(SHIPPED)


@pytest.fixture
def raw():
    with open(SHIPPED, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(autouse=True)
def fixed_authority(monkeypatch):
    """Pin the authority scorer so unrelated components stay constant.

    Also guarantees the tests never touch content/feed/domain_*.json.
    """
    from agent.feed_authority import AuthorityBreakdown

    def fake(url, source, metadata=None, **kwargs):
        return AuthorityBreakdown(domain_score=0.8, source_score=0.7,
                                  final_score=0.75, signals=["fixed for test"])

    monkeypatch.setattr("agent.feed_authority.item_authority", fake)
    yield


def hours_ago(h):
    return (NOW - dt.timedelta(hours=h)).isoformat()


def score(candidate, config, now=NOW):
    return score_source_confidence(candidate, config, now=now)


def problems_from(tmp_path, data):
    path = tmp_path / "sc.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ScoringConfigError) as exc:
        load_scoring_config(path)
    return exc.value.problems


# ── 1. Primary-source availability ──────────────────────────────────────────

def test_an_exact_primary_source_earns_full_points(config):
    c = Candidate(url="https://x.dev/a", event_time=hours_ago(2), sources=(
        SourceRef(url="https://vendor.com/release-notes", kind="release_notes",
                  covers_exact_development=True),
    ))
    comp = score(c, config).components["primary_source"]
    assert comp.score == 30 and comp.max == 30
    assert comp.extra["source_urls"] == ["https://vendor.com/release-notes"]


def test_an_indirect_first_party_source_earns_partial_points(config):
    c = Candidate(url="https://x.dev/a", event_time=hours_ago(2), sources=(
        SourceRef(url="https://vendor.com/docs", kind="official_documentation",
                  covers_exact_development=False),
    ))
    assert score(c, config).components["primary_source"].score == 20


def test_a_secondary_source_citing_an_unavailable_primary_earns_ten(config):
    c = Candidate(url="https://news.dev/a", event_time=hours_ago(2), sources=(
        SourceRef(url="https://news.dev/a", kind="secondary", links_to_primary=True),
    ))
    assert score(c, config).components["primary_source"].score == 10


def test_a_secondary_source_without_primary_evidence_earns_nothing(config):
    c = Candidate(url="https://news.dev/a", event_time=hours_ago(2), sources=(
        SourceRef(url="https://news.dev/a", kind="secondary"),
    ))
    comp = score(c, config).components["primary_source"]
    assert comp.score == 0
    assert comp.extra["source_urls"] == []


@pytest.mark.parametrize("kind", sorted(SC.PRIMARY_KINDS))
def test_every_declared_primary_kind_counts(config, kind):
    c = Candidate(url="https://x.dev", event_time=hours_ago(1), sources=(
        SourceRef(url="https://p.org/1", kind=kind, covers_exact_development=True),
    ))
    assert score(c, config).components["primary_source"].score == 30


# ── 2. Independent corroboration ────────────────────────────────────────────

def test_two_independent_domains_earn_full_corroboration(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://a.com/1"), SourceRef(url="https://b.com/2"),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.score == 25
    assert comp.extra["counted_domains"] == ["a.com", "b.com"]


def test_one_independent_domain_earns_fifteen(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1"),))
    assert score(c, config).components["corroboration"].score == 15


def test_syndicated_copies_do_not_inflate_corroboration(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://a.com/1"),
        SourceRef(url="https://syndicate1.com/1", syndicated_from="a.com"),
        SourceRef(url="https://syndicate2.com/1", syndicated_from="a.com"),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.score == 15, "three pages, one real organization"
    assert comp.extra["counted_domains"] == ["a.com"]
    reasons = {e["reason"] for e in comp.extra["excluded_domains"]}
    assert reasons == {SC.EXCLUSION_SYNDICATED}


def test_multiple_subdomains_of_one_organization_do_not_inflate(config):
    c = Candidate(url="https://news.bbc.co.uk/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://news.bbc.co.uk/1"),
        SourceRef(url="https://sport.bbc.co.uk/2"),
        SourceRef(url="https://bbc.co.uk/3"),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.extra["counted_domains"] == ["bbc.co.uk"]
    assert comp.score == 15
    assert all(e["reason"] == SC.EXCLUSION_SAME_ORG
               for e in comp.extra["excluded_domains"])


def test_duplicate_canonical_urls_count_once(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://a.com/1"),
        SourceRef(url="https://a.com/1?utm_source=twitter"),
        SourceRef(url="https://a.com/1/"),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.extra["counted_domains"] == ["a.com"]
    assert any(e["reason"] == SC.EXCLUSION_DUPLICATE_URL
               for e in comp.extra["excluded_domains"])


def test_press_release_mirrors_are_excluded(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://wire1.com/pr", is_press_release=True),
        SourceRef(url="https://wire2.com/pr", is_press_release=True),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.score == 5, "pages exist but none independent"
    assert comp.extra["counted_domains"] == []


def test_repeating_a_vendor_statement_without_evidence_is_excluded(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://a.com/1", adds_independent_evidence=False),
        SourceRef(url="https://b.com/2", adds_independent_evidence=False),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.score == 5
    assert all(e["reason"] == SC.EXCLUSION_NO_EVIDENCE
               for e in comp.extra["excluded_domains"])


def test_the_subject_organizations_own_pages_are_not_corroboration(config):
    """First-party evidence is a primary source, not a second opinion."""
    c = Candidate(url="https://vendor.com/a", event_time=hours_ago(2),
                  subject_org="vendor.com", sources=(
        SourceRef(url="https://vendor.com/blog", kind="official_announcement"),
        SourceRef(url="https://vendor.com/docs", kind="official_documentation"),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.extra["counted_domains"] == []
    assert any(e["reason"] == SC.EXCLUSION_FIRST_PARTY
               for e in comp.extra["excluded_domains"])


def test_first_party_material_never_corroborates_even_without_subject_org(config):
    """subject_org is often unknown; the kind alone must be enough."""
    c = Candidate(url="https://vendor.io/x", event_time=hours_ago(2), sources=(
        SourceRef(url="https://vendor.io/docs", kind="official_documentation"),
        SourceRef(url="https://vendor.io/changelog", kind="release_notes"),
        SourceRef(url="https://devblog.com/x"),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.extra["counted_domains"] == ["devblog.com"]
    assert comp.score == 15
    assert {e["reason"] for e in comp.extra["excluded_domains"]} == {
        SC.EXCLUSION_FIRST_PARTY}


def test_a_third_party_authority_publication_does_corroborate(config):
    """A CVE advisory or a paper is primary AND independent of the vendor."""
    c = Candidate(url="https://vendor.io/x", event_time=hours_ago(2),
                  subject_org="vendor.io", sources=(
        SourceRef(url="https://vendor.io/advisory", kind="security_advisory"),
        SourceRef(url="https://cisa.gov/alert", kind="government_publication"),
        SourceRef(url="https://arxiv.org/abs/1", kind="research_paper"),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.extra["counted_domains"] == ["arxiv.org", "cisa.gov"]
    assert comp.score == 25


def test_identical_titles_alone_never_establish_corroboration(config):
    """Two outlets running the same wire copy agree about nothing."""
    same = "Vendor announces the thing"
    c = Candidate(title=same, url="https://a.com/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://a.com/1", title=same, syndicated_from="wire"),
        SourceRef(url="https://b.com/2", title=same, syndicated_from="wire"),
    ))
    assert score(c, config).components["corroboration"].score == 5


def test_no_sources_at_all_scores_zero_corroboration(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2))
    comp = score(c, config).components["corroboration"]
    assert comp.score == 0 and comp.extra["excluded_domains"] == []


@pytest.mark.parametrize("url,expected", [
    ("https://www.example.com/a", "example.com"),
    ("https://news.example.com/a", "example.com"),
    ("https://news.bbc.co.uk/a", "bbc.co.uk"),
    ("https://example.co.uk/a", "example.co.uk"),
    ("https://a.b.c.example.com.au/x", "example.com.au"),
    ("", ""),
])
def test_registrable_domain_collapses_subdomains(url, expected):
    assert registrable_domain(url) == expected


def test_an_explicit_publisher_beats_domain_guessing(config):
    """Two brands owned by one publisher are one organization."""
    c = Candidate(url="https://brand-a.com/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://brand-a.com/1", publisher="MegaCorp"),
        SourceRef(url="https://brand-b.com/2", publisher="MegaCorp"),
    ))
    comp = score(c, config).components["corroboration"]
    assert comp.extra["counted_domains"] == ["megacorp"]
    assert comp.score == 15


# ── 3. Domain authority ─────────────────────────────────────────────────────

def test_authority_output_is_normalized_into_twenty_points(config):
    c = Candidate(url="https://a.com/1", source="google_news", event_time=hours_ago(2))
    comp = score(c, config).components["domain_authority"]
    assert comp.max == 20
    assert comp.score == 15, "final_score 0.75 * 20"
    assert comp.extra["existing_authority_breakdown"]["final_score"] == 0.75


def test_the_existing_authority_explanation_is_retained(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2))
    breakdown = score(c, config).components["domain_authority"].extra[
        "existing_authority_breakdown"]
    assert breakdown["signals"] == ["fixed for test"]
    assert "domain_score" in breakdown and "history_score" in breakdown


def test_authority_cannot_rescue_missing_evidence(config, monkeypatch):
    """A famous outlet with no primary source and no corroboration must stay low."""
    from agent.feed_authority import AuthorityBreakdown

    monkeypatch.setattr("agent.feed_authority.item_authority",
                        lambda *a, **k: AuthorityBreakdown(final_score=1.0, signals=["max"]))
    c = Candidate(url="https://famous.com/a", event_time=hours_ago(1), sources=())
    result = score(c, config)

    assert result.components["domain_authority"].score == 20
    assert result.components["primary_source"].score == 0
    assert result.components["corroboration"].score == 0
    # Below the lowest slot threshold (practical_takeaway = 65).
    assert result.score <= 45
    assert result.score < 65


def test_the_evidence_free_ceiling_is_below_every_slot_threshold(config):
    """Structural guarantee, stated as arithmetic rather than convention."""
    ceiling = (config.weights["domain_authority"] + config.weights["recency"]
               + config.weights["claim_traceability"])
    assert ceiling == 45
    assert ceiling < 65


# ── 4. Recency ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("age_h,expected", [
    (1, 15), (23.9, 15), (24, 15), (48, 12), (72, 12),
    (100, 8), (168, 8), (200, 4), (336, 4), (400, 0), (10_000, 0),
])
def test_news_recency_decays_through_its_bands(config, age_h, expected):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(age_h))
    assert score(c, config).components["recency"].score == expected


def test_recency_uses_event_time_not_ingestion_time(config):
    """A two-week-old story discovered today is still two weeks old."""
    c = Candidate(url="https://a.com/1", event_time=hours_ago(400),
                  discovered_at=hours_ago(0))
    comp = score(c, config).components["recency"]
    assert comp.score == 0
    assert comp.extra["age_hours"] == pytest.approx(400, abs=0.1)


def test_a_missing_date_is_handled_explicitly(config):
    c = Candidate(url="https://a.com/1", event_time="")
    result = score(c, config)
    comp = result.components["recency"]
    assert comp.score == 0
    assert comp.extra["event_time"] is None
    assert SC.WARN_MISSING_EVENT_TIME in result.warnings


def test_an_unparseable_date_is_flagged_not_guessed(config):
    c = Candidate(url="https://a.com/1", event_time="last tuesday-ish")
    result = score(c, config)
    assert result.components["recency"].score == 0
    assert SC.WARN_UNPARSEABLE_TIMESTAMP in result.warnings
    assert SC.WARN_MISSING_EVENT_TIME in result.warnings


def test_a_future_timestamp_warns_and_is_capped_below_maximum(config):
    c = Candidate(url="https://a.com/1",
                  event_time=(NOW + dt.timedelta(hours=48)).isoformat())
    result = score(c, config)
    comp = result.components["recency"]

    assert SC.WARN_FUTURE_TIMESTAMP in result.warnings
    assert comp.score == 12, "capped at the band below the top, never 15"
    assert comp.score < config.weights["recency"]


def test_small_clock_skew_is_tolerated_not_flagged(config):
    c = Candidate(url="https://a.com/1",
                  event_time=(NOW + dt.timedelta(minutes=2)).isoformat())
    result = score(c, config)
    assert SC.WARN_FUTURE_TIMESTAMP not in result.warnings
    assert result.components["recency"].score == 15


def test_conflicting_source_timestamps_are_flagged(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2), sources=(
        SourceRef(url="https://a.com/1", published_at=hours_ago(2)),
        SourceRef(url="https://b.com/2", published_at=hours_ago(200)),
    ))
    result = score(c, config)
    assert SC.WARN_CONFLICTING_TIMESTAMPS in result.warnings
    # Earliest credible stamp wins, so the age reflects the original event.
    assert result.components["recency"].extra["age_hours"] == pytest.approx(200, abs=0.1)


def test_timezone_aware_comparison_across_offsets(config):
    """Same instant expressed three ways must score identically."""
    utc = dt.datetime(2026, 7, 27, 6, 0, tzinfo=dt.timezone.utc)
    variants = [
        utc.isoformat(),
        utc.astimezone(dt.timezone(dt.timedelta(hours=-4))).isoformat(),
        "2026-07-27T06:00:00Z",
    ]
    scores = {score(Candidate(url="https://a.com/1", event_time=v), config)
              .components["recency"].score for v in variants}
    assert scores == {15}


def test_a_naive_timestamp_is_read_as_utc(config):
    c = Candidate(url="https://a.com/1", event_time="2026-07-27T06:00:00")
    assert score(c, config).components["recency"].score == 15


@pytest.mark.parametrize("kind,age_h,expected", [
    ("news", 400, 0),
    ("tutorial", 400, 15),      # tutorials age slowly
    ("repository", 400, 8),
    ("paper", 400, 12),
])
def test_recency_profiles_differ_by_content_kind(config, kind, age_h, expected):
    """One decay function for every artifact type would be wrong for most."""
    c = Candidate(url="https://a.com/1", content_kind=kind, event_time=hours_ago(age_h))
    comp = score(c, config).components["recency"]
    assert comp.score == expected
    assert comp.extra["profile"] == kind


def test_an_artifact_selects_its_configured_profile(config):
    c = Candidate(url="https://a.com/1", artifact="github_roundup",
                  content_kind="news", event_time=hours_ago(150))
    comp = score(c, config).components["recency"]
    assert comp.extra["profile"] == "repository"
    assert comp.score == 15, "150h is fresh for a repository, stale for news"


def test_an_unknown_content_kind_falls_back_to_the_default_profile(config):
    c = Candidate(url="https://a.com/1", content_kind="mystery", event_time=hours_ago(2))
    assert score(c, config).components["recency"].extra["profile"] == "news"


# ── 5. Claim traceability ───────────────────────────────────────────────────

def test_fully_traceable_claims_earn_full_points(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1"),),
                  claims=(Claim("x", source_url="https://a.com/1"),
                          Claim("y", source_url="https://a.com/1")))
    comp = score(c, config).components["claim_traceability"]
    assert comp.score == 10
    assert comp.extra == {"traceable_claims": 2, "material_claims": 2}


def test_mostly_traceable_claims_earn_seven(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1"),),
                  claims=tuple(Claim(f"c{i}", source_url="https://a.com/1")
                               for i in range(3)) + (Claim("unsupported"),))
    comp = score(c, config).components["claim_traceability"]
    assert comp.score == 7
    assert comp.extra["traceable_claims"] == 3


def test_unsupported_claims_reduce_the_score(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1"),),
                  claims=(Claim("a", source_url="https://a.com/1"),
                          Claim("b"), Claim("c"), Claim("d")))
    assert score(c, config).components["claim_traceability"].score == 3


def test_claims_with_no_evidence_mapping_earn_nothing(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  claims=(Claim("a"), Claim("b")))
    comp = score(c, config).components["claim_traceability"]
    assert comp.score == 0
    assert comp.extra == {"traceable_claims": 0, "material_claims": 2}


def test_immaterial_claims_are_ignored(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1"),),
                  claims=(Claim("material", source_url="https://a.com/1"),
                          Claim("colour commentary", material=False)))
    assert score(c, config).components["claim_traceability"].score == 10


def test_an_excerpt_is_a_specific_enough_mapping(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1"),),
                  claims=(Claim("a", excerpt="the docs say X"),))
    assert score(c, config).components["claim_traceability"].score == 10


def test_a_claim_pointing_at_an_unknown_url_is_not_traceable(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1"),),
                  claims=(Claim("a", source_url="https://elsewhere.com/z"),))
    assert score(c, config).components["claim_traceability"].score == 0


def test_a_vendor_benchmark_in_a_primary_source_is_not_independently_verified(config):
    """The document being primary does not make its benchmark verified."""
    c = Candidate(url="https://vendor.com/a", event_time=hours_ago(2),
                  subject_org="vendor.com",
                  sources=(SourceRef(url="https://vendor.com/blog",
                                     kind="official_announcement",
                                     covers_exact_development=True),),
                  claims=(Claim("30% faster", vendor_claim=True,
                                source_url="https://vendor.com/blog"),))
    result = score(c, config)

    assert result.components["primary_source"].score == 30, "the document IS primary"
    assert result.components["claim_traceability"].score == 0, "the benchmark is not verified"
    assert SC.WARN_UNVERIFIED_VENDOR_CLAIM in result.warnings


def test_a_vendor_claim_counts_once_an_independent_source_exists(config):
    c = Candidate(url="https://vendor.com/a", event_time=hours_ago(2),
                  subject_org="vendor.com",
                  sources=(SourceRef(url="https://vendor.com/blog",
                                     kind="official_announcement",
                                     covers_exact_development=True),
                           SourceRef(url="https://independent.dev/test")),
                  claims=(Claim("30% faster", vendor_claim=True,
                                source_url="https://vendor.com/blog"),))
    result = score(c, config)
    assert result.components["claim_traceability"].score == 10
    assert SC.WARN_UNVERIFIED_VENDOR_CLAIM not in result.warnings


def test_no_material_claims_is_reported_explicitly(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1", excerpt="event happened"),))
    result = score(c, config)
    assert result.components["claim_traceability"].score == 3
    assert SC.WARN_NO_MATERIAL_CLAIMS in result.warnings


# ── Totals, purity, determinism ─────────────────────────────────────────────

def test_components_sum_exactly_to_the_total(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(30), sources=(
        SourceRef(url="https://p.org/x", kind="release_notes",
                  covers_exact_development=True),
        SourceRef(url="https://a.com/1"), SourceRef(url="https://b.com/2"),
    ), claims=(Claim("x", source_url="https://p.org/x"),))
    result = score(c, config)
    assert result.score == sum(c.score for c in result.components.values())
    assert set(result.components) == set(SC.COMPONENTS)


def test_the_maximums_sum_to_one_hundred(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(2))
    result = score(c, config)
    assert sum(comp.max for comp in result.components.values()) == 100


def test_the_score_is_bounded_zero_to_one_hundred(config):
    best = Candidate(url="https://a.com/1", event_time=hours_ago(1), sources=(
        SourceRef(url="https://p.org/x", kind="release_notes",
                  covers_exact_development=True),
        SourceRef(url="https://a.com/1"), SourceRef(url="https://b.com/2"),
    ), claims=(Claim("x", source_url="https://p.org/x"),))
    worst = Candidate(url="https://a.com/1")

    assert 0 <= score(worst, config).score <= 100
    assert 0 <= score(best, config).score <= 100
    assert score(worst, config).score == 15, "authority only"


def test_the_same_input_always_produces_identical_output(config):
    c = Candidate(url="https://a.com/1", event_time=hours_ago(30), sources=(
        SourceRef(url="https://b.com/2"), SourceRef(url="https://a.com/1"),
        SourceRef(url="https://a.com/1?utm_source=x"),
    ), claims=(Claim("x", excerpt="e"), Claim("y")))
    first = score(c, config).to_dict()
    for _ in range(5):
        assert score(c, config).to_dict() == first


def test_warnings_are_deduplicated_and_order_stable(config):
    c = Candidate(url="https://a.com/1", event_time="nonsense", sources=(
        SourceRef(url="https://a.com/1", published_at="also nonsense"),
    ))
    warnings = score(c, config).warnings
    assert len(warnings) == len(set(warnings))
    assert score(c, config).warnings == warnings


def test_scoring_makes_no_llm_call(config, monkeypatch):
    """Stage 2 is deterministic. Any LLM use here would be a regression."""
    import agent.llm_ops as LLM

    def explode(*a, **k):
        raise AssertionError("source confidence must not call an LLM")

    monkeypatch.setattr(LLM, "chat", explode)
    monkeypatch.setattr(LLM, "requests", type("R", (), {"post": staticmethod(explode)}))

    c = Candidate(url="https://a.com/1", event_time=hours_ago(2),
                  sources=(SourceRef(url="https://a.com/1"),),
                  claims=(Claim("x", source_url="https://a.com/1"),))
    assert score(c, config).score > 0


def test_scoring_writes_nothing_to_production_history(config, tmp_path, monkeypatch):
    """No history writes: the scorer reads evidence, it does not learn from it."""
    import agent.feed_authority as FA

    def explode(*a, **k):
        raise AssertionError("the scorer must not write history")

    monkeypatch.setattr(FA, "record_domain_success", explode)
    monkeypatch.setattr(FA, "save_domain_authority", explode)

    c = Candidate(url="https://a.com/1", event_time=hours_ago(2))
    assert score(c, config).score >= 0


# ── Worked examples ─────────────────────────────────────────────────────────

def test_a_high_confidence_candidate(config):
    c = Candidate(
        title="Postgres 19 ships incremental backups",
        url="https://arstechnica.com/pg19", source="google_news",
        event_time=hours_ago(10), subject_org="postgresql.org",
        sources=(
            SourceRef(url="https://postgresql.org/docs/release-19", kind="release_notes",
                      covers_exact_development=True, publisher="postgresql.org",
                      published_at=hours_ago(10)),
            SourceRef(url="https://arstechnica.com/pg19", published_at=hours_ago(6)),
            SourceRef(url="https://theregister.com/pg19", published_at=hours_ago(5)),
        ),
        claims=(Claim("incremental backups added",
                      source_url="https://postgresql.org/docs/release-19"),),
    )
    result = score(c, config)
    assert result.score == 95
    assert result.warnings == ()


def test_a_medium_confidence_candidate(config):
    c = Candidate(
        title="Framework X adds a plugin API", url="https://devblog.com/x",
        source="hackernews", event_time=hours_ago(60),
        sources=(
            SourceRef(url="https://vendor.io/docs/plugins", kind="official_documentation",
                      covers_exact_development=False, published_at=hours_ago(60)),
            SourceRef(url="https://devblog.com/x", published_at=hours_ago(50)),
        ),
        claims=(Claim("plugin API exists", source_url="https://vendor.io/docs/plugins"),
                Claim("it is faster than the old one"),),
    )
    result = score(c, config)
    assert result.components["primary_source"].score == 20
    assert result.components["corroboration"].score == 15
    assert result.components["recency"].score == 12
    assert result.components["claim_traceability"].score == 3
    assert result.score == 65


def test_a_low_confidence_candidate(config):
    c = Candidate(
        title="Rumour: BigCo may release something", url="https://aggregator.net/r",
        source="reddit", event_time=hours_ago(400),
        sources=(
            SourceRef(url="https://aggregator.net/r", syndicated_from="wire"),
            SourceRef(url="https://mirror.net/r", is_press_release=True),
        ),
        claims=(Claim("BigCo will release it in Q4"),),
    )
    result = score(c, config)
    assert result.components["primary_source"].score == 0
    assert result.components["corroboration"].score == 5
    assert result.components["recency"].score == 0
    assert result.components["claim_traceability"].score == 0
    assert result.score == 20
    assert result.score < 65, "below every slot threshold"


# ── Configuration validation ────────────────────────────────────────────────

def test_the_shipped_config_loads(config):
    assert config.version == 1
    assert sum(config.weights.values()) == 100
    assert config.weights == {"primary_source": 30, "corroboration": 25,
                              "domain_authority": 20, "recency": 15,
                              "claim_traceability": 10}


def test_weights_that_do_not_total_one_hundred_are_rejected(tmp_path, raw):
    raw["weights"]["recency"] = 20
    assert any("sum to 105, must be 100" in p for p in problems_from(tmp_path, raw))


def test_a_negative_weight_is_rejected(tmp_path, raw):
    raw["weights"]["recency"] = -15
    assert any("negative" in p for p in problems_from(tmp_path, raw))


def test_an_unknown_component_name_is_rejected(tmp_path, raw):
    raw["weights"]["vibes"] = 0
    assert any("unknown component name(s): vibes" in p for p in problems_from(tmp_path, raw))


def test_a_missing_component_is_rejected(tmp_path, raw):
    del raw["weights"]["recency"]
    assert any("missing component weight(s): recency" in p
               for p in problems_from(tmp_path, raw))


def test_non_monotonic_recency_scores_are_rejected(tmp_path, raw):
    raw["recency_profiles"]["news"] = [
        {"max_age_hours": 24, "score": 8},
        {"max_age_hours": 72, "score": 15},   # rises with age
        {"max_age_hours": None, "score": 0},
    ]
    assert any("non-increasing with age" in p for p in problems_from(tmp_path, raw))


def test_unordered_recency_bands_are_rejected(tmp_path, raw):
    raw["recency_profiles"]["news"] = [
        {"max_age_hours": 72, "score": 15},
        {"max_age_hours": 24, "score": 12},
        {"max_age_hours": None, "score": 0},
    ]
    assert any("must increase in max_age_hours" in p for p in problems_from(tmp_path, raw))


def test_duplicate_time_boundaries_are_rejected(tmp_path, raw):
    raw["recency_profiles"]["news"] = [
        {"max_age_hours": 24, "score": 15},
        {"max_age_hours": 24, "score": 12},
        {"max_age_hours": None, "score": 0},
    ]
    assert any("duplicate max_age_hours" in p for p in problems_from(tmp_path, raw))


def test_a_missing_catch_all_band_is_rejected(tmp_path, raw):
    raw["recency_profiles"]["news"] = [{"max_age_hours": 24, "score": 15}]
    assert any("catch-all band" in p for p in problems_from(tmp_path, raw))


def test_a_band_score_above_the_component_max_is_rejected(tmp_path, raw):
    raw["recency_profiles"]["news"][0]["score"] = 99
    assert any("outside 0-15" in p for p in problems_from(tmp_path, raw))


def test_an_artifact_reference_that_does_not_exist_is_rejected(tmp_path, raw):
    raw["artifact_profiles"]["not_an_artifact"] = "news"
    assert any("unknown artifact 'not_an_artifact'" in p
               for p in problems_from(tmp_path, raw))


def test_an_artifact_pointing_at_an_unknown_profile_is_rejected(tmp_path, raw):
    raw["artifact_profiles"]["github_roundup"] = "no_such_profile"
    assert any("unknown profile 'no_such_profile'" in p
               for p in problems_from(tmp_path, raw))


def test_an_unknown_default_profile_is_rejected(tmp_path, raw):
    raw["recency_default_profile"] = "nope"
    assert any("recency_default_profile" in p for p in problems_from(tmp_path, raw))


def test_an_out_of_range_most_threshold_is_rejected(tmp_path, raw):
    raw["claim_traceability"]["most_threshold"] = 1.5
    assert any("most_threshold" in p for p in problems_from(tmp_path, raw))


def test_an_unsupported_version_is_rejected(tmp_path, raw):
    raw["version"] = 99
    assert any("unsupported version" in p for p in problems_from(tmp_path, raw))


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(ScoringConfigError) as exc:
        load_scoring_config(tmp_path / "absent.yaml")
    assert any("not found" in p for p in exc.value.problems)


def test_every_config_problem_is_reported_not_just_the_first(tmp_path, raw):
    broken = copy.deepcopy(raw)
    broken["version"] = 99
    broken["weights"]["recency"] = -1
    broken["recency_default_profile"] = "nope"
    problems = problems_from(tmp_path, broken)
    assert len(problems) >= 3


# ── Dormancy ────────────────────────────────────────────────────────────────

def test_stage_two_changes_nothing_while_the_flag_is_false():
    import content_formats as CF
    from agent.editorial import editorial_slots_enabled

    assert editorial_slots_enabled() is False
    assert len(CF.NEWS_FORMATS) == 8
    assert not (set(CF.EDITORIAL_FORMATS) & set(CF.NEWS_FORMATS))
