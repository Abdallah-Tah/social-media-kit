"""Phase 1 Stage 2.6 — source-relationship and syndication detection.

Why this exists: Stage 2 corroboration honours is_syndicated,
is_press_release_mirror, and adds_independent_evidence, but raw feed records
never supply them. Without detection, every source looked independent in
production and corroboration scored higher than the evidence justified.

The asymmetry these tests protect:
  * RelationshipResult.adds_independent_evidence is a POSITIVE finding
  * SourceRef.adds_independent_evidence means "not proven to be a bare
    repetition", and is cleared only on a positive non-corroborating call
An unreadable source is `relationship_unknown` and keeps the benefit of the
doubt. Absence of evidence is not evidence of syndication — getting that
backwards would quietly collapse every corroboration score.
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

from agent.editorial import source_relationships as SR  # noqa: E402
from agent.editorial.models import SourceRef  # noqa: E402
from agent.editorial.source_relationships import (  # noqa: E402
    CONFIG_PATH,
    RelationshipConfigError,
    analyze_candidate,
    apply_relationships,
    detect_evidence,
    detect_relationships,
    load_relationship_config,
    resolve_organization,
    text_similarity,
)

NOW = dt.datetime(2026, 7, 27, 12, 0, tzinfo=dt.timezone.utc)

# Long enough to clear min_comparable_tokens, so similarity is meaningful.
VENDOR_BODY = (
    "The release adds incremental backups to the core engine and changes the "
    "default write ahead log configuration for large installations")
BENCHMARK_BODY = (
    "We ran our own benchmarks against the release and measured a twelve percent "
    "regression in write throughput on identical hardware")
CODE_BODY = (
    "Reading the source code of the new backup path shows the checkpoint routine "
    "now batches segment writes before flushing them to disk")
COMMENTARY_BODY = (
    "This is exciting for anyone running large databases and what this means for "
    "operators is that backups get simpler over the next year or so")


@pytest.fixture
def config():
    return load_relationship_config(CONFIG_PATH)


@pytest.fixture
def raw_config():
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def ago(hours):
    return (NOW - dt.timedelta(hours=hours)).isoformat()


def classify(refs, config, **kwargs):
    """Return {url: relationship} for readable assertions."""
    results = detect_relationships(refs, config=config, **kwargs)
    return {ref.url: res.relationship for ref, res in zip(refs, results)}


def problems_from(tmp_path, data):
    path = tmp_path / "rel.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(RelationshipConfigError) as exc:
        load_relationship_config(path)
    return exc.value.problems


VENDOR = SourceRef(url="https://vendor.com/blog/release", kind="official_announcement",
                   published_at=ago(30), excerpt=VENDOR_BODY, feed_source="rss")


# ── Duplicates and multiple discovery ───────────────────────────────────────

def test_an_exact_canonical_url_duplicate_is_detected(config):
    refs = [
        SourceRef(url="https://news.dev/a", published_at=ago(10), excerpt=VENDOR_BODY),
        SourceRef(url="https://news.dev/a?utm_source=twitter", published_at=ago(10),
                  excerpt=VENDOR_BODY),
    ]
    results = detect_relationships(refs, config=config)
    assert results[1].relationship == SR.DUPLICATE_CANONICAL_URL
    assert results[1].origin_source_id == results[0].source_id


def test_the_same_article_from_two_feeds_is_detected_and_counted_once(config):
    refs = [
        SourceRef(url="https://news.dev/a", published_at=ago(10),
                  excerpt=VENDOR_BODY, feed_source="google_news"),
        SourceRef(url="https://news.dev/a", published_at=ago(10),
                  excerpt=VENDOR_BODY, feed_source="hackernews"),
    ]
    results = detect_relationships(refs, config=config)

    assert results[1].relationship == SR.SAME_ARTICLE_MULTIPLE_FEEDS
    assert set(results[1].discovery_paths) == {"google_news", "hackernews"}
    assert "matching_canonical_url" in results[1].reasons


def test_the_origin_is_not_labelled_a_duplicate_of_itself(config):
    """Two records sharing a canonical URL share a source_id; the first must
    still be classified on its own merits."""
    refs = [
        SourceRef(url="https://lab.dev/a", published_at=ago(10),
                  excerpt=BENCHMARK_BODY, feed_source="rss"),
        SourceRef(url="https://lab.dev/a", published_at=ago(10),
                  excerpt=BENCHMARK_BODY, feed_source="hackernews"),
    ]
    results = detect_relationships(refs, config=config)
    assert results[0].relationship == SR.ADDS_INDEPENDENT_EVIDENCE
    assert results[1].relationship == SR.SAME_ARTICLE_MULTIPLE_FEEDS


def test_the_same_body_at_a_different_url_from_one_publisher_is_one_article(config):
    refs = [
        SourceRef(url="https://news.dev/a", published_at=ago(10), excerpt=VENDOR_BODY),
        SourceRef(url="https://news.dev/amp/a", published_at=ago(10),
                  excerpt=VENDOR_BODY),
    ]
    results = detect_relationships(refs, config=config)
    assert results[1].relationship == SR.SAME_ARTICLE_MULTIPLE_FEEDS
    assert "matching_content_fingerprint" in results[1].reasons


def test_an_identical_body_from_a_different_organization_is_not_multi_feed(config):
    """That is syndication, not one article reached by two front doors."""
    refs = [VENDOR, SourceRef(url="https://echo.dev/a", published_at=ago(5),
                              excerpt=VENDOR_BODY)]
    assert classify(refs, config)["https://echo.dev/a"] == SR.SYNDICATED_COPY


# ── Organization identity ───────────────────────────────────────────────────

def test_subdomains_collapse_to_one_organization(config):
    refs = [
        SourceRef(url="https://news.bbc.co.uk/a", published_at=ago(10),
                  excerpt=BENCHMARK_BODY),
        SourceRef(url="https://sport.bbc.co.uk/b", published_at=ago(9),
                  excerpt=CODE_BODY),
    ]
    results = detect_relationships(refs, config=config)
    assert results[0].organization_id == results[1].organization_id == "bbc.co.uk"
    assert results[1].relationship == SR.SAME_ORGANIZATION


def test_a_configured_alias_resolves_to_one_organization(config):
    a = SourceRef(url="https://openai.com/blog/x")
    b = SourceRef(url="https://openai.com/research/y")
    assert resolve_organization(a, config) == resolve_organization(b, config) == "openai"


def test_a_configured_group_spans_a_domain_and_a_github_org(config):
    """github.com/vendor and vendor.com are one publisher when declared."""
    site = SourceRef(url="https://vendor.com/blog/x")
    repo = SourceRef(url="https://github.com/vendor/project/releases/tag/v1")
    assert resolve_organization(site, config) == "example_vendor"
    assert resolve_organization(repo, config) == "example_vendor"


def test_organization_ownership_is_never_inferred_from_domain_similarity(config):
    """vendor.com and vendor-news.com are different until declared otherwise."""
    a = SourceRef(url="https://vendor.com/x")
    b = SourceRef(url="https://vendor-news.com/x")
    assert resolve_organization(a, config) != resolve_organization(b, config)


def test_an_explicit_organization_id_wins(config):
    ref = SourceRef(url="https://brand-a.com/x", organization_id="MegaCorp")
    assert resolve_organization(ref, config) == "megacorp"


# ── Syndication ─────────────────────────────────────────────────────────────

def test_identical_content_from_a_later_publisher_is_syndicated(config):
    refs = [VENDOR, SourceRef(url="https://reprint.dev/a", published_at=ago(2),
                              excerpt=VENDOR_BODY)]
    results = detect_relationships(refs, config=config)

    assert results[1].relationship == SR.SYNDICATED_COPY
    assert "matching_content_fingerprint" in results[1].reasons
    assert "published_after_origin" in results[1].reasons
    assert results[1].origin_source_id == results[0].source_id


def test_a_similar_title_alone_is_not_enough_to_call_syndication(config):
    """Two outlets running the same wire headline have agreed about nothing."""
    headline = "Vendor ships incremental backups in its newest release"
    refs = [
        SourceRef(url="https://vendor.com/blog/x", kind="official_announcement",
                  title=headline, published_at=ago(30), excerpt=VENDOR_BODY),
        SourceRef(url="https://other.dev/a", title=headline, published_at=ago(2),
                  excerpt=BENCHMARK_BODY),
    ]
    results = detect_relationships(refs, config=config)
    assert results[1].relationship != SR.SYNDICATED_COPY
    assert results[1].relationship == SR.ADDS_INDEPENDENT_EVIDENCE


def test_explicit_syndication_metadata_is_honoured(config):
    ref = SourceRef(url="https://reprint.dev/a", published_at=ago(2),
                    excerpt=BENCHMARK_BODY, syndicated_from="vendor.com")
    results = detect_relationships([ref], config=config)
    assert results[0].relationship == SR.SYNDICATED_COPY
    assert "explicit_syndication_metadata" in results[0].reasons


def test_a_known_syndication_network_is_detected(config):
    ref = SourceRef(url="https://msn.com/en-us/story", published_at=ago(2),
                    excerpt=BENCHMARK_BODY)
    results = detect_relationships([ref], config=config)
    assert results[0].relationship == SR.SYNDICATED_COPY
    assert "known_syndication_network" in results[0].reasons


def test_an_earlier_publication_is_not_a_copy_of_a_later_one(config):
    """Ordering matters: the origin cannot be syndicated from its own copy."""
    refs = [
        SourceRef(url="https://first.dev/a", published_at=ago(30), excerpt=VENDOR_BODY),
        SourceRef(url="https://second.dev/a", published_at=ago(2), excerpt=VENDOR_BODY),
    ]
    results = detect_relationships(refs, config=config)
    assert results[0].relationship != SR.SYNDICATED_COPY
    assert results[1].relationship == SR.SYNDICATED_COPY


# ── Press-release mirrors ───────────────────────────────────────────────────

def test_a_known_press_release_domain_is_a_mirror(config):
    ref = SourceRef(url="https://prnewswire.com/news/vendor", published_at=ago(20),
                    excerpt=VENDOR_BODY)
    results = detect_relationships([ref], config=config)
    assert results[0].relationship == SR.PRESS_RELEASE_MIRROR
    assert "known_press_release_domain" in results[0].reasons


def test_an_explicitly_declared_press_release_is_a_mirror(config):
    ref = SourceRef(url="https://outlet.dev/a", published_at=ago(20),
                    excerpt=VENDOR_BODY, is_press_release=True)
    assert detect_relationships([ref], config=config)[0].relationship == \
        SR.PRESS_RELEASE_MIRROR


def test_a_press_release_mirror_is_excluded_from_corroboration(config):
    from agent.editorial.models import Candidate
    from agent.editorial.source_confidence import score_source_confidence

    refs = (VENDOR, SourceRef(url="https://prnewswire.com/n", published_at=ago(20),
                              excerpt=VENDOR_BODY))
    candidate = Candidate(url="https://vendor.com/blog/release", event_time=ago(30),
                          subject_org="vendor.com", sources=refs)
    enriched = apply_relationships(
        candidate, detect_relationships(refs, subject_org="vendor.com", config=config))

    corroboration = score_source_confidence(enriched, now=NOW).components["corroboration"]
    assert corroboration.extra["counted_domains"] == []
    assert any(e["reason"] == "press_release_mirror"
               for e in corroboration.extra["excluded_domains"])


# ── Evidence ────────────────────────────────────────────────────────────────

def test_an_independent_benchmark_counts_as_new_evidence(config):
    ref = SourceRef(url="https://lab.dev/bench", published_at=ago(2),
                    excerpt=BENCHMARK_BODY)
    result = detect_relationships([ref], config=config)[0]

    assert result.relationship == SR.ADDS_INDEPENDENT_EVIDENCE
    assert result.adds_independent_evidence is True
    assert "independent_benchmark" in result.evidence_kinds


def test_source_code_analysis_counts_as_new_evidence(config):
    ref = SourceRef(url="https://deep.dev/a", published_at=ago(2), excerpt=CODE_BODY)
    result = detect_relationships([ref], config=config)[0]
    assert result.adds_independent_evidence is True
    assert "source_code_inspection" in result.evidence_kinds


def test_commentary_without_evidence_does_not_count(config):
    refs = [VENDOR, SourceRef(url="https://takes.dev/a", published_at=ago(2),
                              excerpt=COMMENTARY_BODY)]
    result = detect_relationships(refs, config=config)[1]

    assert result.adds_independent_evidence is False
    assert result.relationship != SR.ADDS_INDEPENDENT_EVIDENCE
    assert result.evidence_kinds == ()


def test_a_repeated_vendor_claim_without_evidence_is_classified(config):
    """Substantially restates the announcement and adds nothing."""
    restated = VENDOR_BODY + " It is exciting for operators everywhere."
    refs = [VENDOR, SourceRef(url="https://echo.dev/a", published_at=ago(29),
                              excerpt=restated)]
    result = detect_relationships(refs, config=config)[1]

    assert result.relationship == SR.REPEATS_VENDOR_STATEMENT
    assert result.adds_independent_evidence is False
    assert "restates_origin_without_new_evidence" in result.reasons


def test_a_repeated_vendor_claim_is_excluded_from_corroboration(config):
    from agent.editorial.models import Candidate
    from agent.editorial.source_confidence import score_source_confidence

    restated = VENDOR_BODY + " It is exciting for operators everywhere."
    refs = (VENDOR, SourceRef(url="https://echo.dev/a", published_at=ago(29),
                              excerpt=restated))
    candidate = Candidate(url="https://vendor.com/blog/release", event_time=ago(30),
                          subject_org="vendor.com", sources=refs)
    enriched = apply_relationships(
        candidate, detect_relationships(refs, subject_org="vendor.com", config=config))

    corroboration = score_source_confidence(enriched, now=NOW).components["corroboration"]
    assert corroboration.extra["counted_domains"] == []
    assert any(e["reason"] == "repeats_vendor_statement_without_evidence"
               for e in corroboration.extra["excluded_domains"])


def test_independent_reporting_with_no_overlap_is_recognized(config):
    unrelated = ("Operators at three large hosting providers described their own "
                 "migration plans for the coming quarter in detail")
    refs = [VENDOR, SourceRef(url="https://press.dev/a", published_at=ago(2),
                              excerpt=unrelated)]
    result = detect_relationships(refs, config=config)[1]
    assert result.relationship == SR.INDEPENDENT_REPORTING


def test_detect_evidence_is_directly_testable(config):
    assert detect_evidence(SourceRef(url="u", excerpt=BENCHMARK_BODY), config).has_evidence
    assert not detect_evidence(SourceRef(url="u", excerpt=COMMENTARY_BODY),
                               config).has_evidence
    assert not detect_evidence(SourceRef(url="u", excerpt=""), config).readable


# ── First party ─────────────────────────────────────────────────────────────

def test_a_first_party_source_never_counts_as_independent_corroboration(config):
    result = detect_relationships([VENDOR], subject_org="vendor.com", config=config)[0]
    assert result.relationship == SR.FIRST_PARTY_REPETITION
    assert result.adds_independent_evidence is False


def test_first_party_is_detected_from_the_source_kind_without_subject_org(config):
    result = detect_relationships([VENDOR], config=config)[0]
    assert result.relationship == SR.FIRST_PARTY_REPETITION
    assert "first_party_source_kind" in result.reasons


def test_a_second_first_party_page_is_repetition(config):
    refs = [VENDOR, SourceRef(url="https://vendor.com/docs/backups",
                              kind="official_documentation", published_at=ago(28),
                              excerpt=CODE_BODY)]
    results = detect_relationships(refs, subject_org="vendor.com", config=config)
    assert all(r.relationship == SR.FIRST_PARTY_REPETITION for r in results)


# ── Unknown ─────────────────────────────────────────────────────────────────

def test_an_unreadable_source_stays_explicitly_unknown(config):
    ref = SourceRef(url="https://thin.dev/a", published_at=ago(2), excerpt="")
    result = detect_relationships([ref], config=config)[0]

    assert result.relationship == SR.RELATIONSHIP_UNKNOWN
    assert result.confidence == 0.0
    assert "no_source_excerpt" in result.reasons
    assert result.adds_independent_evidence is False


def test_an_unknown_relationship_does_not_exclude_a_source_from_corroboration(config):
    """Absence of evidence is not evidence of syndication."""
    from agent.editorial.models import Candidate
    from agent.editorial.source_confidence import score_source_confidence

    refs = (VENDOR,
            SourceRef(url="https://a.dev/x", published_at=ago(2), excerpt=""),
            SourceRef(url="https://b.dev/y", published_at=ago(2), excerpt=""))
    candidate = Candidate(url="https://vendor.com/blog/release", event_time=ago(30),
                          subject_org="vendor.com", sources=refs)
    enriched = apply_relationships(
        candidate, detect_relationships(refs, subject_org="vendor.com", config=config))

    corroboration = score_source_confidence(enriched, now=NOW).components["corroboration"]
    assert set(corroboration.extra["counted_domains"]) == {"a.dev", "b.dev"}
    assert corroboration.score == 25


# ── Determinism and purity ──────────────────────────────────────────────────

def test_source_order_does_not_affect_classification(config):
    refs = [
        VENDOR,
        SourceRef(url="https://lab.dev/bench", published_at=ago(2), excerpt=BENCHMARK_BODY),
        SourceRef(url="https://prnewswire.com/n", published_at=ago(20), excerpt=VENDOR_BODY),
        SourceRef(url="https://echo.dev/a", published_at=ago(1), excerpt=VENDOR_BODY),
    ]
    forward = classify(refs, config, subject_org="vendor.com")
    backward = classify(list(reversed(refs)), config, subject_org="vendor.com")
    assert forward == backward


def test_the_same_input_produces_identical_output(config):
    refs = [VENDOR, SourceRef(url="https://lab.dev/b", published_at=ago(2),
                              excerpt=BENCHMARK_BODY)]
    first = [r.to_dict() for r in detect_relationships(refs, config=config)]
    for _ in range(5):
        assert [r.to_dict() for r in detect_relationships(refs, config=config)] == first


def test_detection_does_not_mutate_the_sources_it_is_given(config):
    refs = [copy.deepcopy(VENDOR),
            SourceRef(url="https://msn.com/a", published_at=ago(2), excerpt=VENDOR_BODY)]
    snapshot = [r.to_dict() for r in refs]
    detect_relationships(refs, config=config)
    assert [r.to_dict() for r in refs] == snapshot


def test_enrichment_returns_a_new_candidate_and_mutates_nothing(config):
    from agent.editorial.models import Candidate

    refs = (SourceRef(url="https://msn.com/a", published_at=ago(2), excerpt=VENDOR_BODY),)
    candidate = Candidate(url="https://msn.com/a", sources=refs)
    before = candidate.to_dict()

    enriched = apply_relationships(candidate, detect_relationships(refs, config=config))

    assert enriched is not candidate
    assert candidate.to_dict() == before, "the original candidate must be untouched"
    assert enriched.sources[0].is_syndicated is True


def test_detection_makes_no_llm_or_network_call(config, monkeypatch):
    import urllib.request

    import agent.llm_ops as LLM

    def explode(*a, **k):
        raise AssertionError("the detector must not call an LLM or the network")

    monkeypatch.setattr(LLM, "chat", explode)
    monkeypatch.setattr(LLM, "requests", type("R", (), {"post": staticmethod(explode)}))
    monkeypatch.setattr(urllib.request, "urlopen", explode)

    assert detect_relationships([VENDOR], config=config)


def test_text_similarity_is_symmetric_and_bounded():
    assert text_similarity(VENDOR_BODY, VENDOR_BODY) == 1.0
    assert text_similarity(VENDOR_BODY, BENCHMARK_BODY) == \
        text_similarity(BENCHMARK_BODY, VENDOR_BODY)
    assert 0.0 <= text_similarity(VENDOR_BODY, BENCHMARK_BODY) <= 1.0
    assert text_similarity("", VENDOR_BODY) == 0.0


# ── Orchestration and the effect on Stage 2 ─────────────────────────────────

def test_detection_changes_the_stage_two_confidence_score(config):
    """The whole point: undetected syndication inflated corroboration."""
    from agent.editorial.models import Candidate
    from agent.editorial.source_confidence import score_source_confidence

    refs = (VENDOR,
            SourceRef(url="https://msn.com/copy", published_at=ago(2), excerpt=VENDOR_BODY),
            SourceRef(url="https://prnewswire.com/n", published_at=ago(20),
                      excerpt=VENDOR_BODY))
    candidate = Candidate(url="https://vendor.com/blog/release", event_time=ago(30),
                          subject_org="vendor.com", sources=refs)

    before = score_source_confidence(candidate, now=NOW).components["corroboration"]
    enriched = apply_relationships(
        candidate, detect_relationships(refs, subject_org="vendor.com", config=config))
    after = score_source_confidence(enriched, now=NOW).components["corroboration"]

    assert before.score == 25, "undetected, two mirrors looked independent"
    assert after.score == 5, "detected, neither is a second opinion"
    assert after.extra["counted_domains"] == []


def test_real_independent_evidence_still_earns_full_corroboration(config):
    from agent.editorial.models import Candidate
    from agent.editorial.source_confidence import score_source_confidence

    refs = (VENDOR,
            SourceRef(url="https://lab.dev/bench", published_at=ago(2),
                      excerpt=BENCHMARK_BODY),
            SourceRef(url="https://deep.dev/code", published_at=ago(1),
                      excerpt=CODE_BODY))
    candidate = Candidate(url="https://vendor.com/blog/release", event_time=ago(30),
                          subject_org="vendor.com", sources=refs)
    enriched = apply_relationships(
        candidate, detect_relationships(refs, subject_org="vendor.com", config=config))

    assert score_source_confidence(enriched, now=NOW).components["corroboration"].score == 25


def test_analyze_candidate_wires_the_three_steps(config):
    record = {
        "title": "Vendor ships incremental backups in the newest release",
        "url": "https://vendor.com/blog/release",
        "published_at": ago(30),
        "vendor": "vendor.com",
        "sources": [
            {"url": "https://vendor.com/blog/release", "kind": "official_announcement",
             "covers_exact_development": True, "published_at": ago(30),
             "excerpt": VENDOR_BODY},
            {"url": "https://msn.com/copy", "published_at": ago(2), "excerpt": VENDOR_BODY},
        ],
    }
    candidate, relationships, confidence = analyze_candidate(
        record, relationship_config=config, now=NOW)

    assert len(relationships) == len(candidate.sources)
    assert any(r.relationship == SR.SYNDICATED_COPY for r in relationships)
    assert confidence.components["primary_source"].score == 30
    assert confidence.components["corroboration"].score < 25


def test_the_detector_does_not_import_the_scorer_or_saturation():
    """Kept separate from normalization, scoring, and saturation logic."""
    import ast

    tree = ast.parse(open(SR.__file__, encoding="utf-8").read())
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {getattr(n, "module", "") or "" for n in top_level}
    for n in top_level:
        names.update(a.name for a in n.names)

    assert not any("source_confidence" in n for n in names), sorted(names)
    assert not any("candidate_adapter" in n for n in names), sorted(names)
    assert not any("saturation" in n for n in names), sorted(names)


# ── Configuration validation ────────────────────────────────────────────────

def test_the_shipped_config_loads(config):
    assert config.version == 1
    assert config.press_release_domains and config.syndication_domains
    assert config.evidence_markers


def test_a_domain_cannot_be_both_press_release_and_syndication(tmp_path, raw_config):
    raw_config["press_release_domains"].append("msn.com")
    assert any("cannot be both" in p for p in problems_from(tmp_path, raw_config))


def test_syndication_threshold_below_repetition_is_rejected(tmp_path, raw_config):
    raw_config["similarity"]["syndication_min_body"] = 0.4
    assert any("must be >=" in p for p in problems_from(tmp_path, raw_config))


@pytest.mark.parametrize("value", [0, 1.5, -0.2, "high"])
def test_out_of_range_similarity_thresholds_are_rejected(tmp_path, raw_config, value):
    raw_config["similarity"]["repetition_min_body"] = value
    assert any("repetition_min_body" in p for p in problems_from(tmp_path, raw_config))


def test_disabling_the_title_only_guard_is_rejected(tmp_path, raw_config):
    """Matching titles must never be sufficient, so this cannot be turned off."""
    raw_config["similarity"]["title_only_is_never_sufficient"] = False
    assert any("title_only_is_never_sufficient" in p
               for p in problems_from(tmp_path, raw_config))


def test_an_invalid_evidence_regex_is_rejected(tmp_path, raw_config):
    raw_config["evidence"]["markers"]["independent_benchmark"] = ["([unclosed"]
    assert any("invalid regex" in p for p in problems_from(tmp_path, raw_config))


def test_an_empty_marker_group_is_rejected(tmp_path, raw_config):
    raw_config["evidence"]["markers"]["ghost"] = []
    assert any("ghost" in p for p in problems_from(tmp_path, raw_config))


def test_a_missing_confidence_entry_is_rejected(tmp_path, raw_config):
    del raw_config["confidence"]["syndicated_copy"]
    assert any("missing relationship(s)" in p for p in problems_from(tmp_path, raw_config))


def test_an_unknown_confidence_relationship_is_rejected(tmp_path, raw_config):
    raw_config["confidence"]["telepathy"] = 0.5
    assert any("unknown relationship(s): telepathy" in p
               for p in problems_from(tmp_path, raw_config))


def test_an_out_of_range_confidence_is_rejected(tmp_path, raw_config):
    raw_config["confidence"]["syndicated_copy"] = 5
    assert any("within 0-1" in p for p in problems_from(tmp_path, raw_config))


def test_a_group_without_members_is_rejected(tmp_path, raw_config):
    raw_config["organization_groups"]["ghost"] = {"display": "Ghost"}
    assert any("at least one member" in p for p in problems_from(tmp_path, raw_config))


def test_an_unsupported_version_is_rejected(tmp_path, raw_config):
    raw_config["version"] = 99
    assert any("unsupported version" in p for p in problems_from(tmp_path, raw_config))


def test_a_missing_config_file_is_reported(tmp_path):
    with pytest.raises(RelationshipConfigError) as exc:
        load_relationship_config(tmp_path / "absent.yaml")
    assert any("not found" in p for p in exc.value.problems)


def test_validation_fails_closed_reporting_every_problem(tmp_path, raw_config):
    broken = copy.deepcopy(raw_config)
    broken["version"] = 99
    broken["similarity"]["title_only_is_never_sufficient"] = False
    del broken["confidence"]["syndicated_copy"]
    broken["organization_groups"]["ghost"] = {}
    assert len(problems_from(tmp_path, broken)) >= 4


# ── Dormancy ────────────────────────────────────────────────────────────────

def test_stage_two_six_changes_nothing_while_the_flag_is_false():
    import content_formats as CF
    from agent.editorial import editorial_slots_enabled

    assert editorial_slots_enabled() is False
    assert len(CF.NEWS_FORMATS) == 8
    assert not (set(CF.EDITORIAL_FORMATS) & set(CF.NEWS_FORMATS))
