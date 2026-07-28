"""Phase 1 Stage 2.5 — normalization of intelligence records into Candidates.

The adapter is the production path into the Stage 2 scorer. It is deterministic
and does no I/O: no LLM, no network, no writes, and no mutation of the records
it is handed.

Failure behaviour is deliberately lopsided and tested as such. Missing optional
metadata yields warnings and explicitly-unknown fields; only a structurally
unusable record is rejected, and then with an exact reason. A pipeline that
silently drops candidates is one that silently stops publishing.
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

from agent.editorial import models as M  # noqa: E402
from agent.editorial.candidate_adapter import (  # noqa: E402
    CONFIG_PATH,
    REJECT_EMPTY_RECORD,
    REJECT_NO_IDENTITY,
    NormalizationConfigError,
    dedupe_sources,
    load_normalization_config,
    normalize_and_score,
    normalize_candidate,
    normalize_many,
    resolve_development_type,
)
from agent.editorial.models import Candidate, NormalizationError, SourceRef  # noqa: E402

NOW = dt.datetime(2026, 7, 27, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def config():
    return load_normalization_config(CONFIG_PATH)


@pytest.fixture
def raw_config():
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def norm(record, config, **kwargs):
    return normalize_candidate(record, config=config, **kwargs)


def problems_from(tmp_path, data):
    path = tmp_path / "norm.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(NormalizationConfigError) as exc:
        load_normalization_config(path)
    return exc.value.problems


# ── Records used across the suite ───────────────────────────────────────────

ANNOUNCEMENT = {
    "title": "OpenAI launches GPT-5 with a new reasoning mode",
    "url": "https://openai.com/blog/gpt-5",
    "published_at": "2026-07-26T09:00:00Z",
    "source": "rss",
    "sources": [
        {"url": "https://openai.com/blog/gpt-5", "kind": "official_announcement",
         "covers_exact_development": True, "published_at": "2026-07-26T09:00:00Z"},
        {"url": "https://techcrunch.com/gpt-5", "published_at": "2026-07-26T11:00:00Z"},
    ],
}

GITHUB_RELEASE = {
    "title": "Laravel 13.2 released",
    "url": "https://github.com/laravel/framework/releases/tag/v13.2.0",
    "tag_name": "v13.2.0",
    "released_at": "2026-07-25T10:00:00Z",
    "source": "github",
    "sources": [
        {"url": "https://github.com/laravel/framework/releases/tag/v13.2.0",
         "kind": "repository_release", "covers_exact_development": True,
         "published_at": "2026-07-25T10:00:00Z"},
    ],
}

PAPER = {
    "title": "Scaling laws for sparse mixture-of-experts models",
    "url": "https://arxiv.org/abs/2607.01234",
    "abstract": "We study scaling behaviour of sparse MoE architectures.",
    "published_at": "2026-07-20T00:00:00Z",
    "sources": [
        {"url": "https://arxiv.org/abs/2607.01234", "kind": "research_paper",
         "covers_exact_development": True, "published_at": "2026-07-20T00:00:00Z"},
    ],
}


# ── Source mapping ──────────────────────────────────────────────────────────

def test_an_official_announcement_maps_to_a_primary_source_ref(config):
    c = norm(ANNOUNCEMENT, config)
    primary = c.primary_source

    assert primary is not None
    assert primary.source_kind == "official_announcement"
    assert primary.is_primary and primary.is_first_party
    assert primary.covers_exact_development
    assert primary.registrable_domain == "openai.com"


def test_an_independent_article_is_not_marked_first_party(config):
    c = norm(ANNOUNCEMENT, config)
    tc = next(s for s in c.sources if s.registrable_domain == "techcrunch.com")

    assert tc.is_primary is False
    assert tc.is_first_party is False
    assert tc.is_syndicated is False
    assert tc.repeated_vendor_statement is False


def test_a_github_release_maps_to_repository_release(config):
    c = norm(GITHUB_RELEASE, config)
    assert c.development_type == "repository_release"
    assert c.primary_source.source_kind == "repository_release"
    assert c.artifact_type == "repository", "repository recency profile, not news"


def test_a_github_url_alone_is_enough_to_classify_a_release(config):
    """The URL shape carries the type even without a typed SourceRef."""
    c = norm({"title": "Something shipped",
              "url": "https://github.com/vercel/next.js/releases/tag/v16.0.0"}, config)
    assert c.development_type == "repository_release"


def test_paper_metadata_maps_to_research_paper(config):
    c = norm(PAPER, config)
    assert c.development_type == "research_paper"
    assert c.artifact_type == "paper"
    assert c.primary_source.source_kind == "research_paper"


def test_an_arxiv_domain_alone_classifies_a_paper(config):
    c = norm({"title": "Some interesting result", "url": "https://arxiv.org/abs/1"}, config)
    assert c.development_type == "research_paper"


def test_the_source_ref_schema_is_fully_populated(config):
    ref = norm(ANNOUNCEMENT, config).primary_source.to_dict()
    for key in ("url", "canonical_url", "domain", "registrable_domain",
                "organization_id", "source_kind", "publication_time",
                "discovered_at", "title", "is_primary", "is_first_party",
                "is_syndicated", "is_press_release_mirror",
                "repeated_vendor_statement", "cluster_evidence", "excerpt"):
        assert key in ref, key


# ── Deduplication ───────────────────────────────────────────────────────────

def test_the_same_story_from_multiple_feeds_dedupes_to_one_source(config):
    """Google News + Hacker News + RSS is one source, not three."""
    record = {
        "title": "Postgres 19 ships incremental backups",
        "url": "https://postgresql.org/about/news/19",
        "sources": [
            {"url": "https://postgresql.org/about/news/19", "feed_source": "google_news"},
            {"url": "https://postgresql.org/about/news/19?utm_source=hn",
             "feed_source": "hackernews"},
            {"url": "https://postgresql.org/about/news/19/", "feed_source": "rss"},
        ],
    }
    c = norm(record, config)
    assert len(c.sources) == 1


def test_dedupe_keeps_the_richest_view_of_a_source():
    """A primary kind and an excerpt found on a later copy must survive."""
    merged = dedupe_sources([
        SourceRef(url="https://a.com/x", kind="secondary"),
        SourceRef(url="https://a.com/x?utm_campaign=y", kind="release_notes",
                  covers_exact_development=True, excerpt="the notes say X",
                  published_at="2026-07-01T00:00:00Z"),
    ])
    assert len(merged) == 1
    assert merged[0].kind == "release_notes"
    assert merged[0].covers_exact_development is True
    assert merged[0].excerpt == "the notes say X"


def test_dedupe_is_order_independent():
    a = SourceRef(url="https://a.com/1")
    b = SourceRef(url="https://b.com/2")
    assert {s.url for s in dedupe_sources([a, b])} == {s.url for s in dedupe_sources([b, a])}


# ── Canonical topic identity ────────────────────────────────────────────────

def test_the_canonical_topic_id_matches_the_specified_shape(config):
    assert norm(ANNOUNCEMENT, config).canonical_topic_id == "openai:model_release:gpt-5"
    assert norm(GITHUB_RELEASE, config).canonical_topic_id == \
        "laravel:repository_release:13.2.0"


def test_the_topic_id_is_stable_across_source_order(config):
    shuffled = copy.deepcopy(ANNOUNCEMENT)
    shuffled["sources"] = list(reversed(shuffled["sources"]))

    first, second = norm(ANNOUNCEMENT, config), norm(shuffled, config)
    assert first.canonical_topic_id == second.canonical_topic_id
    assert first.source_fingerprint == second.source_fingerprint
    assert first.candidate_id == second.candidate_id


def test_two_different_releases_from_one_vendor_get_different_topic_ids(config):
    """Never collapse every development from a company into one topic."""
    a = norm({"title": "Laravel 13.2 released", "tag_name": "v13.2.0",
              "url": "https://github.com/laravel/framework/releases/tag/v13.2.0"}, config)
    b = norm({"title": "Laravel 13.3 released", "tag_name": "v13.3.0",
              "url": "https://github.com/laravel/framework/releases/tag/v13.3.0"}, config)

    assert a.canonical_topic_id != b.canonical_topic_id
    assert a.canonical_topic_id.endswith(":13.2.0")
    assert b.canonical_topic_id.endswith(":13.3.0")


def test_different_development_types_for_one_vendor_differ(config):
    a = norm({"title": "OpenAI changes pricing for the API",
              "url": "https://openai.com/pricing",
              "published_at": "2026-07-10T00:00:00Z"}, config)
    b = norm(ANNOUNCEMENT, config)
    assert a.canonical_topic_id != b.canonical_topic_id
    assert ":pricing_change:" in a.canonical_topic_id


def test_a_period_style_development_uses_a_month_bucket(config):
    c = norm({"title": "Vendor announces pricing changes across the board",
              "url": "https://vendor.com/pricing", "published_at": "2026-07-10T00:00:00Z"},
             config)
    assert c.canonical_topic_id.endswith(":2026-07")


def test_a_topic_key_falling_back_to_the_title_is_flagged(config):
    c = norm({"title": "Something happened somewhere today",
              "url": "https://blog.example.com/a"}, config)
    assert M.WARN_TOPIC_KEY_FROM_TITLE in c.warnings or c.event_time
    assert c.canonical_topic_id.count(":") == 2


# ── Subject organization ────────────────────────────────────────────────────

def test_the_subject_org_resolves_from_a_first_party_domain(config):
    c = norm({"title": "PostgreSQL 19 is out",
              "url": "https://postgresql.org/about/news/19",
              "sources": [{"url": "https://postgresql.org/about/news/19",
                           "kind": "official_announcement"}]}, config)
    assert c.subject_org == "postgresql"
    assert c.subject_org_resolution_reason == "first_party_source_domain"
    assert c.subject_org_confidence == 0.9


def test_the_subject_org_resolves_from_a_repository_owner(config):
    c = norm(GITHUB_RELEASE, config)
    assert c.subject_org == "laravel"
    assert c.subject_org_resolution_reason == "repository_owner"


def test_explicit_metadata_wins_over_everything(config):
    c = norm({**ANNOUNCEMENT, "vendor": "anthropic"}, config)
    assert c.subject_org == "anthropic"
    assert c.subject_org_resolution_reason == "explicit_metadata"
    assert c.subject_org_confidence == 1.0


def test_an_ambiguous_subject_org_stays_unresolved_with_a_warning(config):
    """A bare word match is never enough to name an organization."""
    c = norm({"title": "Some startup ships a thing nobody configured",
              "url": "https://randomblog.example/post"}, config)

    assert c.subject_org == ""
    assert c.subject_org_confidence == 0.0
    assert c.subject_org_resolution_reason == "unresolved"
    assert M.WARN_SUBJECT_ORG_UNRESOLVED in c.warnings
    assert c.canonical_topic_id.startswith("unknown:")


def test_a_configured_alias_in_the_title_resolves_at_medium_confidence(config):
    c = norm({"title": "Anthropic ships something notable today",
              "url": "https://randomblog.example/post"}, config)
    assert c.subject_org == "anthropic"
    assert c.subject_org_resolution_reason == "configured_alias_name"
    assert c.subject_org_confidence == 0.6
    assert M.WARN_SUBJECT_ORG_LOW_CONFIDENCE in c.warnings


def test_org_resolution_does_not_depend_on_source_order(config):
    record = {"title": "A release happened", "url": "https://x.dev/a", "sources": [
        {"url": "https://beta.com/d", "kind": "official_documentation"},
        {"url": "https://alpha.com/d", "kind": "official_documentation"},
    ]}
    flipped = copy.deepcopy(record)
    flipped["sources"] = list(reversed(flipped["sources"]))
    assert norm(record, config).subject_org == norm(flipped, config).subject_org


# ── Claims ──────────────────────────────────────────────────────────────────

def test_a_vendor_benchmark_claim_is_marked_vendor_provided(config):
    c = norm({
        "title": "Vendor model scores 92% on MMLU",
        "url": "https://vendor.com/blog/model",
        "benchmarks": {"MMLU": "92%"},
        "sources": [{"url": "https://vendor.com/blog/model",
                     "kind": "official_announcement", "covers_exact_development": True}],
    }, config)
    benchmarks = [cl for cl in c.claims if cl.claim_type == "benchmark"]

    assert benchmarks, "the structured benchmark field must produce a claim"
    assert all(cl.vendor_claim for cl in benchmarks)
    assert all(cl.verification == M.VERIFIED_VENDOR for cl in benchmarks)


def test_a_vendor_claim_becomes_independently_established_with_a_third_party(config):
    c = norm({
        "title": "Vendor model scores 92% on MMLU",
        "url": "https://vendor.com/blog/model",
        "benchmarks": {"MMLU": "92%"},
        "sources": [
            {"url": "https://vendor.com/blog/model", "kind": "official_announcement",
             "covers_exact_development": True},
            {"url": "https://independent.dev/replication"},
        ],
    }, config)
    benchmarks = [cl for cl in c.claims if cl.claim_type == "benchmark"]
    assert all(cl.verification == M.VERIFIED_INDEPENDENT for cl in benchmarks)


def test_claims_carry_the_full_required_schema(config):
    claim = norm(ANNOUNCEMENT, config).claims[0].to_dict()
    for key in ("claim_id", "text", "normalized_text", "claim_type", "material",
                "vendor_provided", "verification", "traceability",
                "source_references", "warnings"):
        assert key in claim, key
    assert claim["claim_id"].startswith("claim_")


def test_claim_ids_are_stable_and_unique(config):
    first, second = norm(ANNOUNCEMENT, config), norm(ANNOUNCEMENT, config)
    ids = [c.claim_id for c in first.claims]
    assert ids == [c.claim_id for c in second.claims]
    assert len(ids) == len(set(ids))


def test_a_headline_claim_is_traceable_to_its_source(config):
    claim = norm(ANNOUNCEMENT, config).claims[0]
    assert claim.traceability == M.TRACEABLE
    assert claim.source_url in {s.url for s in norm(ANNOUNCEMENT, config).sources}


def test_no_claims_are_invented_when_nothing_is_extractable(config):
    c = norm({"url": "https://example.com/x"}, config)   # no title at all
    assert c.claims == ()
    assert M.WARN_NO_CLAIMS_EXTRACTED in c.warnings


def test_the_event_claim_type_follows_the_development_type(config):
    assert norm(GITHUB_RELEASE, config).claims[0].claim_type == "version_fact"
    assert norm(PAPER, config).claims[0].claim_type == "event_fact"
    assert norm(ANNOUNCEMENT, config).claims[0].claim_type == "capability"


# ── Time resolution ─────────────────────────────────────────────────────────

def test_event_time_uses_the_explicit_release_timestamp(config):
    c = norm(GITHUB_RELEASE, config)
    assert c.event_time == "2026-07-25T10:00:00+00:00"
    assert c.event_time_source == "explicit_release"


def test_event_time_falls_back_to_the_primary_source(config):
    c = norm({"title": "A thing shipped", "url": "https://vendor.com/a", "sources": [
        {"url": "https://vendor.com/a", "kind": "release_notes",
         "published_at": "2026-07-24T08:00:00Z"},
    ]}, config)
    assert c.event_time.startswith("2026-07-24")
    assert c.event_time_source in ("explicit_release", "primary_source")


def test_event_time_falls_back_to_discovery_with_a_warning(config):
    c = norm({"title": "Undated story about something",
              "url": "https://blog.example/a"}, config,
             discovered_at="2026-07-27T09:00:00Z")
    assert c.event_time.startswith("2026-07-27")
    assert c.event_time_source == "discovery"
    assert M.WARN_EVENT_TIME_FROM_DISCOVERY in c.warnings


def test_a_completely_missing_event_time_is_explicit(config):
    c = norm({"title": "Undated story about something",
              "url": "https://blog.example/a"}, config)
    assert c.event_time == ""
    assert c.event_time_source == "none"
    assert M.WARN_MISSING_EVENT_TIME in c.warnings


def test_conflicting_timestamps_produce_a_warning_and_keep_alternatives(config):
    c = norm({"title": "A story with disagreeing dates", "url": "https://a.com/1",
              "sources": [
                  {"url": "https://a.com/1", "published_at": "2026-07-01T00:00:00Z"},
                  {"url": "https://b.com/2", "published_at": "2026-07-26T00:00:00Z"},
              ]}, config)

    assert M.WARN_CONFLICTING_TIMESTAMPS in c.warnings
    assert c.alternative_event_times, "the rejected timestamps must be preserved"
    assert c.event_time_selection_reason


def test_close_timestamps_are_not_flagged_as_conflicting(config):
    c = norm({"title": "A story with close dates", "url": "https://a.com/1",
              "sources": [
                  {"url": "https://a.com/1", "published_at": "2026-07-26T00:00:00Z"},
                  {"url": "https://b.com/2", "published_at": "2026-07-26T06:00:00Z"},
              ]}, config)
    assert M.WARN_CONFLICTING_TIMESTAMPS not in c.warnings


def test_an_unparseable_timestamp_is_flagged(config):
    c = norm({"title": "A story with a bad date", "url": "https://a.com/1",
              "published_at": "sometime last week"}, config)
    assert M.WARN_UNPARSEABLE_TIMESTAMP in c.warnings


def test_all_resolved_timestamps_are_timezone_aware(config):
    c = norm({"title": "Naive timestamp story", "url": "https://a.com/1",
              "published_at": "2026-07-26T09:00:00"}, config)
    parsed = dt.datetime.fromisoformat(c.event_time)
    assert parsed.tzinfo is not None


# ── Development type edges ──────────────────────────────────────────────────

def test_an_unclassifiable_record_keeps_development_type_unknown(config):
    c = norm({"title": "Update", "url": "https://blog.example.com/x"}, config)
    assert c.development_type == "unknown"
    assert M.WARN_DEVELOPMENT_TYPE_UNKNOWN in c.warnings


def test_a_real_headline_with_no_specific_signal_is_general_news(config):
    c = norm({"title": "Developers are talking about something again",
              "url": "https://blog.example.com/x"}, config)
    assert c.development_type == "general_news"


def test_explicit_development_type_metadata_wins(config):
    c = norm({"title": "Laravel 13.2 released", "url": "https://github.com/laravel/f/releases/tag/v13",
              "development_type": "security_issue"}, config)
    assert c.development_type == "security_issue"


@pytest.mark.parametrize("title,expected", [
    ("Critical CVE-2026-1234 found in the parser", "security_issue"),
    ("Redis changes its license to BUSL", "licensing_change"),
    ("Vendor cuts pricing for the API tier", "pricing_change"),
    ("Breaking change: config format no longer supported", "compatibility_change"),
    ("Service is now generally available in three regions", "deployment_availability"),
    ("Startup raises $40M in a Series B round", "funding_or_company_news"),
])
def test_development_type_rules_classify_headlines(config, title, expected):
    assert norm({"title": title, "url": "https://x.dev/a"}, config).development_type == expected


def test_every_configured_rule_type_is_a_known_development_type(config):
    assert all(rule.development_type in M.DEVELOPMENT_TYPES for rule in config.rules)


# ── Robustness ──────────────────────────────────────────────────────────────

def test_missing_optional_metadata_does_not_crash(config):
    c = norm({"title": "Bare minimum story"}, config)
    assert isinstance(c, Candidate)
    assert c.development_type in M.DEVELOPMENT_TYPES
    assert c.warnings


def test_a_url_only_record_still_normalizes(config):
    c = norm({"url": "https://example.com/story"}, config)
    assert c.url == "https://example.com/story"
    assert c.title == ""


def test_a_record_with_no_title_and_no_url_is_rejected_with_a_reason(config):
    with pytest.raises(NormalizationError) as exc:
        norm({"summary": "orphaned text"}, config)
    assert exc.value.reason == REJECT_NO_IDENTITY


def test_an_empty_record_is_rejected_with_a_reason(config):
    with pytest.raises(NormalizationError) as exc:
        norm({}, config)
    assert exc.value.reason == REJECT_EMPTY_RECORD


def test_normalize_many_reports_rejections_instead_of_dropping_them(config):
    good = {"title": "A real story about something", "url": "https://a.com/1"}
    bad = {"summary": "no identity"}
    candidates, rejections = normalize_many([good, bad, good], config=config)

    assert len(candidates) == 2
    assert len(rejections) == 1
    assert rejections[0]["reason"] == REJECT_NO_IDENTITY


def test_the_adapter_never_mutates_the_record_it_is_given(config):
    record = copy.deepcopy(ANNOUNCEMENT)
    snapshot = copy.deepcopy(record)
    norm(record, config)
    assert record == snapshot


def test_the_same_input_produces_an_identical_candidate(config):
    first = norm(ANNOUNCEMENT, config).to_dict()
    for _ in range(5):
        assert norm(ANNOUNCEMENT, config).to_dict() == first


def test_the_candidate_schema_is_fully_populated(config):
    data = norm(ANNOUNCEMENT, config).to_dict()
    for key in ("candidate_id", "canonical_topic_id", "title", "normalized_title",
                "development_type", "artifact_type", "subject_name", "subject_org",
                "event_time", "discovered_at", "primary_source", "sources",
                "claims", "cluster_id", "canonical_url", "source_fingerprint",
                "opportunity_score", "authority_metadata", "warnings",
                "normalization_version"):
        assert key in data, key
    assert data["normalization_version"] == M.NORMALIZATION_VERSION


def test_no_primary_source_is_warned_about(config):
    c = norm({"title": "A story with only secondary coverage",
              "url": "https://blog.example/a"}, config)
    assert M.WARN_NO_PRIMARY_SOURCE in c.warnings
    assert c.primary_source is None


# ── Existing SMKit structures ───────────────────────────────────────────────

def test_a_feed_item_normalizes_without_adaptation(config):
    from agent.feed import FeedItem

    item = FeedItem(title="Rust 1.90 stabilises async closures",
                    url="https://blog.rust-lang.org/1.90",
                    source="hackernews", published_at="2026-07-26T00:00:00Z",
                    summary="Async closures are now stable.")
    c = norm(item, config)
    assert c.title.startswith("Rust 1.90")
    assert c.source == "hackernews"
    assert c.sources


def test_a_story_cluster_becomes_one_candidate_with_many_sources(config):
    from agent.feed import FeedItem
    from agent.feed_clustering import cluster_items

    items = [
        FeedItem(title="Postgres 19 ships incremental backups",
                 url="https://a.com/pg19", source="google_news",
                 published_at="2026-07-26T00:00:00Z"),
        FeedItem(title="Postgres 19 ships incremental backups",
                 url="https://b.com/pg19", source="hackernews",
                 published_at="2026-07-26T01:00:00Z"),
    ]
    cluster = cluster_items(items)[0]
    c = norm(cluster, config)

    assert c.cluster_id == cluster.cluster_id
    assert len(c.sources) >= 2
    assert all(s.cluster_id == cluster.cluster_id for s in c.sources
               if s.cluster_member_count)


def test_opportunity_engine_output_is_carried_through(config):
    c = norm({**ANNOUNCEMENT, "opportunity": {"opportunity_score": 78}}, config)
    assert c.opportunity_score == 78


def test_authority_metadata_is_carried_through(config):
    c = norm({**ANNOUNCEMENT, "authority": {"final_score": 0.82}}, config)
    assert c.authority_metadata == {"final_score": 0.82}


# ── Purity ──────────────────────────────────────────────────────────────────

def test_normalization_makes_no_llm_or_network_call(config, monkeypatch):
    import agent.llm_ops as LLM

    def explode(*a, **k):
        raise AssertionError("the adapter must not call an LLM or the network")

    monkeypatch.setattr(LLM, "chat", explode)
    monkeypatch.setattr(LLM, "requests", type("R", (), {"post": staticmethod(explode)}))
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", explode)

    assert norm(ANNOUNCEMENT, config).canonical_topic_id


def test_normalization_writes_no_history(config, monkeypatch):
    import agent.feed_authority as FA

    def explode(*a, **k):
        raise AssertionError("the adapter must not write history")

    monkeypatch.setattr(FA, "record_domain_success", explode)
    monkeypatch.setattr(FA, "save_domain_authority", explode)
    assert norm(ANNOUNCEMENT, config)


# ── Orchestration ───────────────────────────────────────────────────────────

def test_normalize_and_score_wires_the_adapter_to_the_scorer(config):
    candidate, confidence = normalize_and_score(ANNOUNCEMENT, config=config, now=NOW)
    assert candidate.canonical_topic_id == "openai:model_release:gpt-5"
    assert 0 <= confidence.score <= 100
    assert confidence.components["primary_source"].score == 30


def test_the_scorer_does_not_import_the_adapter():
    """One-way dependency: the scorer must stay independently testable.

    Checked against the AST, not the file text — a mention in a comment is not
    an import, and matching on text would fail for the wrong reason.
    """
    import ast

    import agent.editorial.source_confidence as SC

    tree = ast.parse(open(SC.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)

    assert not any("candidate_adapter" in name for name in imported), sorted(imported)
    assert "models" in {n.lstrip(".") for n in imported} or ".models" in imported


# ── Configuration validation ────────────────────────────────────────────────

def test_the_shipped_config_loads(config):
    assert config.version == 1
    assert config.rules and config.org_aliases


def test_an_unknown_development_type_in_a_rule_is_rejected(tmp_path, raw_config):
    raw_config["development_type_rules"][0]["type"] = "teleportation"
    assert any("unknown type 'teleportation'" in p
               for p in problems_from(tmp_path, raw_config))


def test_an_invalid_regex_is_rejected(tmp_path, raw_config):
    raw_config["development_type_rules"][0]["title_patterns"] = ["([unclosed"]
    assert any("invalid regex" in p for p in problems_from(tmp_path, raw_config))


def test_a_rule_with_no_conditions_is_rejected(tmp_path, raw_config):
    raw_config["development_type_rules"].append({"type": "general_news"})
    assert any("no conditions" in p for p in problems_from(tmp_path, raw_config))


def test_an_alias_without_domains_or_names_is_rejected(tmp_path, raw_config):
    raw_config["organization_aliases"]["ghost"] = {"display": "Ghost"}
    assert any("at least one domain or name" in p
               for p in problems_from(tmp_path, raw_config))


def test_an_out_of_range_confidence_is_rejected(tmp_path, raw_config):
    raw_config["subject_org"]["confidence"]["repository_owner"] = 5
    assert any("within 0-1" in p for p in problems_from(tmp_path, raw_config))


def test_an_unknown_claim_type_mapping_is_rejected(tmp_path, raw_config):
    raw_config["claims"]["event_claim_types"]["model_release"] = "vibes"
    assert any("unknown claim type 'vibes'" in p
               for p in problems_from(tmp_path, raw_config))


def test_an_unknown_month_bucket_type_is_rejected(tmp_path, raw_config):
    raw_config["topic"]["month_bucket_types"].append("teleportation")
    assert any("month_bucket_types" in p for p in problems_from(tmp_path, raw_config))


def test_an_unsupported_version_is_rejected(tmp_path, raw_config):
    raw_config["version"] = 99
    assert any("unsupported version" in p for p in problems_from(tmp_path, raw_config))


def test_a_missing_config_file_is_reported(tmp_path):
    with pytest.raises(NormalizationConfigError) as exc:
        load_normalization_config(tmp_path / "absent.yaml")
    assert any("not found" in p for p in exc.value.problems)


def test_every_config_problem_is_reported(tmp_path, raw_config):
    broken = copy.deepcopy(raw_config)
    broken["version"] = 99
    broken["development_type_rules"][0]["type"] = "nope"
    broken["organization_aliases"]["ghost"] = {}
    assert len(problems_from(tmp_path, broken)) >= 3


# ── Dormancy ────────────────────────────────────────────────────────────────

def test_stage_two_five_changes_nothing_while_the_flag_is_false():
    import content_formats as CF
    from agent.editorial import editorial_slots_enabled

    assert editorial_slots_enabled() is False
    assert len(CF.NEWS_FORMATS) == 8
    assert not (set(CF.EDITORIAL_FORMATS) & set(CF.NEWS_FORMATS))
