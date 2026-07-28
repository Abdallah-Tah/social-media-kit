"""Phase 1 Stage 5 — Deterministic editorial-quality scoring.

Evaluates a generated draft AFTER topic admission and BEFORE publication
readiness. Separate from source confidence, opportunity score, saturation,
and topic admission. Deterministic 0-100 score with explainable components.

Guarantees:
  * deterministic — same input, same output
  * no LLM, no network, no content generation
  * no writes to live publication history while EDITORIAL_SLOTS_ENABLED=false
  * uses existing quality_issues() and FORBIDDEN_PHRASES — no second registry
  * artifact-specific word ranges (not one universal floor)
  * hard failures fire regardless of numeric score
  * padding does not improve score
  * high prose quality cannot override evidence failures
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

KIT = Path(__file__).resolve().parents[2]
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

import yaml

# Import existing quality infrastructure — do NOT duplicate.
from scripts.content_formats import FORBIDDEN_PHRASES, quality_issues


# ── Constants ───────────────────────────────────────────────────────────────

CONFIG_PATH = KIT / "config" / "quality.yaml"

STATUS_PASS = "pass"
STATUS_WARNING = "warning"
STATUS_FAIL = "fail"

# Component names.
FORMAT_CONFORMANCE = "format_conformance"
SPECIFICITY_EVIDENCE = "specificity_evidence"
PRACTICAL_VALUE = "practical_value"
STRUCTURE_READABILITY = "structure_readability"
LANGUAGE_ORIGINALITY = "language_originality"

ALL_COMPONENTS = (
    FORMAT_CONFORMANCE,
    SPECIFICITY_EVIDENCE,
    PRACTICAL_VALUE,
    STRUCTURE_READABILITY,
    LANGUAGE_ORIGINALITY,
)

# Stable component issue/warning codes.
ISSUE_MISSING_REQUIRED_SECTION = "missing_required_section"
ISSUE_BELOW_WORD_RANGE = "below_word_range"
ISSUE_REQUIRES_CODE_BLOCK = "requires_code_block"
ISSUE_REQUIRES_PRACTICAL_SECTION = "requires_practical_section"
ISSUE_TITLE_MISSING = "title_missing"
ISSUE_NO_CONCRETE_SIGNALS = "no_concrete_signals"
ISSUE_SOURCES_SECTION_MISSING = "sources_section_missing"
ISSUE_VENDOR_BENCHMARK_UNATTRIBUTED = "vendor_benchmark_unattributed"
ISSUE_REQUIRES_PRACTICAL_GUIDANCE = "requires_practical_guidance"
ISSUE_REQUIRES_CODE_EXAMPLES = "requires_code_examples"
ISSUE_ACTION_SECTION_LACKS_SUBSTANCE = "action_section_lacks_substance"
ISSUE_MALFORMED_MARKDOWN = "malformed_markdown"
ISSUE_FORBIDDEN_PHRASE = "forbidden_phrase"
ISSUE_PROMPT_LEAKAGE = "prompt_leakage"
ISSUE_SOURCE_COPY_SIMILARITY = "source_copy_similarity"

WARNING_ABOVE_WORD_RANGE = "above_word_range"
WARNING_SUMMARY_MISSING = "summary_missing"
WARNING_ONE_CONCRETE_SIGNAL = "only_one_concrete_signal"
WARNING_NUMERIC_CLAIMS_WITHOUT_SOURCES = "numeric_claims_without_sources"
WARNING_INTELLIGENCE_GUIDANCE_MISSING = "intelligence_guidance_missing"
WARNING_TRUNCATED_SENTENCE = "truncated_sentence"
WARNING_GENERIC_FILLER = "generic_filler"
WARNING_LONG_PARAGRAPH = "long_paragraph"
WARNING_GENERIC_INTRO = "generic_intro"
WARNING_EXCESSIVE_HEDGING = "excessive_hedging"
WARNING_TITLE_BODY_LOW_OVERLAP = "title_body_low_overlap"

# Hard-failure reason codes.
HF_MISSING_PRIMARY_SOURCES = "missing_required_primary_sources"
HF_FABRICATED_NUMERIC = "fabricated_numeric_claim"
HF_MALFORMED_OUTPUT = "malformed_or_incomplete_output"
HF_BLANK_REQUIRED_SECTION = "blank_required_section"
HF_PROMPT_LEAKAGE = "prompt_leakage"
HF_CONTRADICTS_FACTS = "contradicts_confirmed_facts"
HF_VENDOR_AS_VERIFIED = "vendor_claim_as_verified"
HF_COPIED_PASSAGE = "copied_passage_beyond_similarity_allowance"
HF_UNSUPPORTED_SECURITY = "unsupported_security_legal_claim"

ALL_HARD_FAILURES = (
    HF_MISSING_PRIMARY_SOURCES,
    HF_FABRICATED_NUMERIC,
    HF_MALFORMED_OUTPUT,
    HF_BLANK_REQUIRED_SECTION,
    HF_PROMPT_LEAKAGE,
    HF_CONTRADICTS_FACTS,
    HF_VENDOR_AS_VERIFIED,
    HF_COPIED_PASSAGE,
    HF_UNSUPPORTED_SECURITY,
)

# Prompt leakage indicators.
PROMPT_LEAKAGE_INDICATORS = (
    "system prompt",
    "user prompt",
    "assistant:",
    "you are a",
    "instructions:",
    "do not",
    "you must",
)

# Generic filler phrases (not forbidden, but signal low information density).
FILLER_PHRASES = (
    "it is important to note",
    "in this article",
    "as we can see",
    "let's dive in",
    "dive deep",
    "without further ado",
    "in today's world",
    "harness the power",
)


# ── Configuration ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class QualityConfig:
    schema_version: int
    weights: dict[str, int]
    thresholds: dict[str, int]
    hard_failures: frozenset[str]
    similarity_allowance: float
    artifacts: dict[str, dict[str, Any]]
    format_references: frozenset[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "weights": self.weights,
            "thresholds": self.thresholds,
            "hard_failures": sorted(self.hard_failures),
            "similarity_allowance": self.similarity_allowance,
            "artifacts": self.artifacts,
            "format_references": sorted(self.format_references),
        }


class QualityConfigError(Exception):
    """Configuration validation error."""
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"quality config invalid: {len(problems)} problem(s)")


def load_quality_config(path: Path | None = None) -> QualityConfig:
    """Load and validate the quality config. All problems reported at once."""
    path = path or CONFIG_PATH
    with open(path) as f:
        raw = yaml.safe_load(f)

    problems: list[str] = []

    # Schema version.
    schema_version = raw.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        problems.append("schema_version must be a positive integer")

    # Weights.
    weights = raw.get("weights", {})
    if not isinstance(weights, dict):
        problems.append("weights must be a dict")
        weights = {}
    else:
        for comp in ALL_COMPONENTS:
            if comp not in weights:
                problems.append(f"missing weight for {comp}")
            elif not isinstance(weights[comp], int) or not (0 <= weights[comp] <= 100):
                problems.append(f"weight for {comp} must be 0-100")
        total = sum(weights.get(c, 0) for c in ALL_COMPONENTS)
        if total != 100:
            problems.append(f"weights must total 100, got {total}")

    # Thresholds.
    thresholds = raw.get("thresholds", {})
    if not isinstance(thresholds, dict):
        problems.append("thresholds must be a dict")
        thresholds = {}
    else:
        for key in ("pass", "warning", "fail"):
            if key not in thresholds:
                problems.append(f"missing threshold: {key}")
            elif not isinstance(thresholds[key], int) or not (0 <= thresholds[key] <= 100):
                problems.append(f"threshold {key} must be 0-100")
        pass_t = thresholds.get("pass", 0)
        warn_t = thresholds.get("warning", 0)
        if pass_t <= warn_t:
            problems.append(f"pass threshold ({pass_t}) must exceed warning ({warn_t})")

    # Hard failures.
    hard_failures = raw.get("hard_failures", [])
    if not isinstance(hard_failures, list):
        problems.append("hard_failures must be a list")
        hard_failures = []
    else:
        for hf in hard_failures:
            if hf not in ALL_HARD_FAILURES:
                problems.append(f"unknown hard failure: {hf}")
    hard_failures_set = frozenset(hard_failures)

    # Similarity allowance.
    sim_raw = raw.get("similarity_allowance", {})
    if not isinstance(sim_raw, dict):
        problems.append("similarity_allowance must be a dict")
        sim_allowance = 0.15
    else:
        sim_allowance = sim_raw.get("max_exact_copy_ratio", 0.15)
        if not isinstance(sim_allowance, (int, float)) or not (0.0 <= sim_allowance <= 1.0):
            problems.append("similarity_allowance must be 0.0-1.0")
            sim_allowance = 0.15

    # Artifacts.
    artifacts_raw = raw.get("artifacts", {})
    if not isinstance(artifacts_raw, dict):
        problems.append("artifacts must be a dict")
        artifacts_raw = {}
    artifacts: dict[str, dict[str, Any]] = {}
    for name, spec in artifacts_raw.items():
        if not isinstance(spec, dict):
            problems.append(f"artifact {name} must be a dict")
            continue
        # Word range.
        wr = spec.get("word_range", {})
        if not isinstance(wr, dict):
            problems.append(f"artifact {name}: word_range must be a dict")
        else:
            wmin = wr.get("min", 0)
            wmax = wr.get("max", 0)
            if not isinstance(wmin, int) or wmin < 0:
                problems.append(f"artifact {name}: word_range.min must be >= 0")
            if not isinstance(wmax, int) or wmax < 0:
                problems.append(f"artifact {name}: word_range.max must be >= 0")
            if wmin >= wmax:
                problems.append(f"artifact {name}: word_range.min must be < max")
        # Required sections.
        req = spec.get("required_sections", [])
        if not isinstance(req, list):
            problems.append(f"artifact {name}: required_sections must be a list")
        # Optional sections.
        opt = spec.get("optional_sections", [])
        if not isinstance(opt, list):
            problems.append(f"artifact {name}: optional_sections must be a list")
        artifacts[name] = spec

    # Format references.
    fmt_refs = raw.get("format_references", [])
    if not isinstance(fmt_refs, list):
        problems.append("format_references must be a list")
        fmt_refs = []
    valid_formats = {"tutorial", "news"}
    for fr in fmt_refs:
        if fr not in valid_formats:
            problems.append(f"unknown format reference: {fr}")
    fmt_refs_set = frozenset(fmt_refs)

    if problems:
        raise QualityConfigError(problems)

    return QualityConfig(
        schema_version=schema_version,
        weights=weights,
        thresholds=thresholds,
        hard_failures=hard_failures_set,
        similarity_allowance=sim_allowance,
        artifacts=artifacts,
        format_references=fmt_refs_set,
    )


# ── Draft input ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DraftInput:
    """The input to the quality scorer."""
    title: str
    body: str
    summary: str
    artifact_type: str
    format_id: str
    slot_objective: str
    sources: tuple[dict[str, Any], ...] = ()
    claims: tuple[dict[str, Any], ...] = ()
    confirmed_facts: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body_length": len(self.body),
            "summary_length": len(self.summary),
            "artifact_type": self.artifact_type,
            "format_id": self.format_id,
            "slot_objective": self.slot_objective,
            "source_count": len(self.sources),
            "claim_count": len(self.claims),
            "confirmed_fact_count": len(self.confirmed_facts),
        }


# ── Component result ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class QualityNote:
    """Stable machine-readable note with a human-readable explanation."""
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class ComponentResult:
    """Score for one component."""
    name: str
    score: int  # 0 - max_weight
    max_weight: int
    issues: tuple[str, ...]
    warnings: tuple[str, ...]
    issue_details: tuple[QualityNote, ...] = ()
    warning_details: tuple[QualityNote, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "max_weight": self.max_weight,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "issue_details": [note.to_dict() for note in self.issue_details],
            "warning_details": [note.to_dict() for note in self.warning_details],
        }


# ── Quality result ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class QualityResult:
    """The full quality evaluation."""
    score: int  # 0-100
    status: str  # pass | warning | fail
    components: tuple[ComponentResult, ...]
    hard_failures: tuple[str, ...]
    issues: tuple[str, ...]
    warnings: tuple[str, ...]
    artifact_type: str
    format_id: str
    issue_details: tuple[QualityNote, ...] = ()
    warning_details: tuple[QualityNote, ...] = ()
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "status": self.status,
            "components": {c.name: c.to_dict() for c in self.components},
            "hard_failures": list(self.hard_failures),
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "issue_details": [note.to_dict() for note in self.issue_details],
            "warning_details": [note.to_dict() for note in self.warning_details],
            "artifact_type": self.artifact_type,
            "format_id": self.format_id,
            "version": self.version,
        }


def _add_note(notes: list[QualityNote], texts: list[str], code: str, message: str) -> None:
    notes.append(QualityNote(code=code, message=message))
    texts.append(message)


# ── Scoring engine ──────────────────────────────────────────────────────────

def _count_words(text: str) -> int:
    """Count words in text, handling Markdown."""
    # Strip code blocks first (don't count code as prose).
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Strip inline code.
    text = re.sub(r"`[^`]*`", "", text)
    # Strip Markdown headers.
    text = re.sub(r"^#+\s", "", text, flags=re.MULTILINE)
    # Strip links.
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Split on whitespace.
    words = text.split()
    return len(words)


def _count_code_blocks(text: str) -> int:
    """Count fenced code blocks."""
    return text.count("```") // 2


def _has_malformed_markdown(text: str) -> bool:
    """Check for malformed Markdown structure."""
    # Unmatched code fences.
    if text.count("```") % 2 != 0:
        return True
    # Heading without space after #.
    if re.search(r"^#{1,6}[^#\s]", text, re.MULTILINE):
        return True
    # List item without space after -.
    if re.search(r"^-\S", text, re.MULTILINE):
        return True
    return False


def _has_truncated_sentence(text: str) -> bool:
    """Check for sentences that end abruptly (no punctuation before EOF)."""
    lines = text.strip().split("\n")
    if not lines:
        return False
    last_line = lines[-1].strip()
    if not last_line:
        return False
    # Last non-empty line should end with sentence-ending punctuation.
    if not re.search(r"[.!?]$", last_line):
        # Unless it's a code block end or list item.
        if not (last_line.startswith("```") or last_line.startswith("-")):
            return True
    return False


def _detect_repetitive_filler(text: str) -> list[str]:
    """Detect generic filler phrases."""
    low = text.lower()
    found = []
    for phrase in FILLER_PHRASES:
        if phrase in low:
            found.append(phrase)
    return found


def _detect_prompt_leakage(text: str) -> list[str]:
    """Detect prompt/system instructions in the output."""
    low = text.lower()
    found = []
    for indicator in PROMPT_LEAKAGE_INDICATORS:
        if indicator in low:
            found.append(indicator)
    return found


def _compute_similarity_ratio(draft: str, sources: Sequence[dict[str, Any]]) -> float:
    """Compute max exact-copy ratio to any single source.

    Simple word-level overlap: for each source, compute what fraction of the
    draft's words appear in the source text. Returns the maximum.
    """
    if not sources:
        return 0.0

    # Tokenize draft into words.
    draft_words = set(re.findall(r"\b\w+\b", draft.lower()))
    if not draft_words:
        return 0.0

    max_ratio = 0.0
    for src in sources:
        src_text = src.get("text", "") or src.get("excerpt", "") or ""
        if not src_text:
            continue
        src_words = set(re.findall(r"\b\w+\b", src_text.lower()))
        if not src_words or len(src_words) < 5:
            # Skip very short sources to avoid false positives.
            continue
        overlap = draft_words & src_words
        ratio = len(overlap) / len(draft_words)
        max_ratio = max(max_ratio, ratio)

    return max_ratio


def _score_format_conformance(
        draft: DraftInput,
        config: QualityConfig,
        artifact_spec: dict[str, Any],
) -> ComponentResult:
    """Component 1: Format conformance (0-25)."""
    issues: list[str] = []
    warnings: list[str] = []
    issue_details: list[QualityNote] = []
    warning_details: list[QualityNote] = []
    max_weight = config.weights[FORMAT_CONFORMANCE]

    # Use existing quality_issues() for section/format checks.
    # Only works for artifact types registered in content_formats.py.
    # Unknown types get a warning but don't fail.
    try:
        existing_issues = quality_issues(draft.artifact_type, draft.body, draft.format_id)
        issues.extend(existing_issues)
    except (ValueError, KeyError):
        # Unknown artifact type — skip content_formats checks.
        pass

    # Check required sections.
    required = artifact_spec.get("required_sections", [])
    body_lower = draft.body.lower()
    for section in required:
        if section.lower() not in body_lower:
            if f"missing section: {section}" not in issues:
                _add_note(
                    issue_details, issues, ISSUE_MISSING_REQUIRED_SECTION,
                    f"missing required section: {section}")

    # Word count — artifact-specific range.
    word_count = _count_words(draft.body)
    wr = artifact_spec.get("word_range", {})
    wmin = wr.get("min", 0)
    wmax = wr.get("max", 0)
    if word_count < wmin:
        _add_note(
            issue_details, issues, ISSUE_BELOW_WORD_RANGE,
            f"below {wmin} words ({word_count})")
    elif word_count > wmax:
        _add_note(
            warning_details, warnings, WARNING_ABOVE_WORD_RANGE,
            f"above {wmax} words ({word_count}) — may be padding")

    # Code block requirement.
    if artifact_spec.get("requires_code_block"):
        code_blocks = _count_code_blocks(draft.body)
        if code_blocks == 0:
            _add_note(
                issue_details, issues, ISSUE_REQUIRES_CODE_BLOCK,
                "requires code block but none found")

    # Practical section requirement.
    if artifact_spec.get("requires_practical_section"):
        practical_markers = ("action items", "migration steps", "compatibility notes",
                             "what you need to know", "takeaway")
        has_practical = any(m in body_lower for m in practical_markers)
        if not has_practical:
            _add_note(
                issue_details, issues, ISSUE_REQUIRES_PRACTICAL_SECTION,
                "requires practical section but none found")

    # Title present.
    if not draft.title.strip():
        _add_note(issue_details, issues, ISSUE_TITLE_MISSING, "title is missing")

    # Summary present.
    if not draft.summary.strip():
        _add_note(warning_details, warnings, WARNING_SUMMARY_MISSING, "summary is missing")

    # Compute score: start at max, deduct for issues.
    issue_codes = {note.code for note in issue_details}
    score = max_weight
    section_issues = [
        note for note in issue_details if note.code == ISSUE_MISSING_REQUIRED_SECTION
    ]
    score -= len(section_issues) * 5
    if ISSUE_BELOW_WORD_RANGE in issue_codes:
        score -= 5
    if ISSUE_REQUIRES_CODE_BLOCK in issue_codes:
        score -= 5
    if ISSUE_REQUIRES_PRACTICAL_SECTION in issue_codes:
        score -= 5
    if ISSUE_TITLE_MISSING in issue_codes:
        score -= 10

    score = max(0, min(max_weight, score))

    return ComponentResult(
        name=FORMAT_CONFORMANCE,
        score=score,
        max_weight=max_weight,
        issues=tuple(issues),
        warnings=tuple(warnings),
        issue_details=tuple(issue_details),
        warning_details=tuple(warning_details),
    )


def _score_specificity_evidence(
        draft: DraftInput,
        config: QualityConfig,
) -> ComponentResult:
    """Component 2: Specificity and evidence use (0-20)."""
    issues: list[str] = []
    warnings: list[str] = []
    issue_details: list[QualityNote] = []
    warning_details: list[QualityNote] = []
    max_weight = config.weights[SPECIFICITY_EVIDENCE]

    body_lower = draft.body.lower()

    # Check for concrete signals: versions, dates, APIs, repos, commands.
    has_version = bool(re.search(r"v?\d+\.\d+", draft.body))
    has_date = bool(re.search(r"\d{4}-\d{2}-\d{2}", draft.body))
    has_api = bool(re.search(r"\b(api|endpoint|route|method)\b", body_lower))
    has_repo = bool(re.search(r"github\.com/\S+", draft.body))
    has_command = "```" in draft.body  # Code blocks imply commands.

    concrete_count = sum([has_version, has_date, has_api, has_repo, has_command])
    if concrete_count == 0:
        _add_note(
            issue_details, issues, ISSUE_NO_CONCRETE_SIGNALS,
            "no concrete signals (versions, dates, APIs, repos, commands)")
    elif concrete_count == 1:
        _add_note(
            warning_details, warnings, WARNING_ONE_CONCRETE_SIGNAL,
            "only one concrete signal — consider adding more")

    # Check that sources are referenced.
    has_sources_section = "## sources" in body_lower
    if not has_sources_section and draft.sources:
        _add_note(
            issue_details, issues, ISSUE_SOURCES_SECTION_MISSING,
            "has sources but no ## Sources section")

    # Check for unsupported numeric claims.
    # Look for numbers not near a source reference.
    numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", draft.body)
    # (Simplified check — full implementation would map numbers to source refs.)
    if numbers and not draft.sources:
        _add_note(
            warning_details, warnings, WARNING_NUMERIC_CLAIMS_WITHOUT_SOURCES,
            "numeric claims present but no sources provided")

    # Check for vendor claims without attribution.
    vendor_claims = re.findall(r"\b(?:performance|speed|throughput|latency|accuracy)\s+(?:is|was|reaches?|improved?|increased?|decreased?|dropped?)\s+\d+", body_lower)
    if vendor_claims:
        # Check if near "according to" or "claimed by" or similar.
        has_attribution = any(phrase in body_lower for phrase in
                              ("according to", "claimed by", "reported by", "vendor states"))
        if not has_attribution:
            _add_note(
                issue_details, issues, ISSUE_VENDOR_BENCHMARK_UNATTRIBUTED,
                "vendor benchmark without attribution")

    # Compute score.
    issue_codes = {note.code for note in issue_details}
    warning_codes = {note.code for note in warning_details}
    score = max_weight
    if ISSUE_NO_CONCRETE_SIGNALS in issue_codes:
        score -= 10
    if ISSUE_SOURCES_SECTION_MISSING in issue_codes:
        score -= 5
    if ISSUE_VENDOR_BENCHMARK_UNATTRIBUTED in issue_codes:
        score -= 10
    if WARNING_ONE_CONCRETE_SIGNAL in warning_codes:
        score -= 3

    score = max(0, min(max_weight, score))

    return ComponentResult(
        name=SPECIFICITY_EVIDENCE,
        score=score,
        max_weight=max_weight,
        issues=tuple(issues),
        warnings=tuple(warnings),
        issue_details=tuple(issue_details),
        warning_details=tuple(warning_details),
    )


def _score_practical_value(
        draft: DraftInput,
        config: QualityConfig,
        artifact_spec: dict[str, Any],
) -> ComponentResult:
    """Component 3: Practical value (0-20)."""
    issues: list[str] = []
    warnings: list[str] = []
    issue_details: list[QualityNote] = []
    warning_details: list[QualityNote] = []
    max_weight = config.weights[PRACTICAL_VALUE]

    body_lower = draft.body.lower()

    # Check for practical signals based on artifact objective.
    requires_practical = artifact_spec.get("requires_practical_section", False)

    practical_signals = (
        "step-by-step", "how to", "run this", "execute", "install",
        "configure", "migrate", "update to", "upgrade", "fix by",
        "workaround", "compatibility", "breaking change", "deprecated",
    )
    has_practical = any(signal in body_lower for signal in practical_signals)

    # For intelligence brief, don't require code blocks.
    if draft.artifact_type == "intelligence_brief":
        # Must explain what to watch/do, but not necessarily code.
        watch_signals = ("should watch", "developers should", "impact on",
                         "what this means", "takeaway", "action")
        has_watch = any(s in body_lower for s in watch_signals)
        if not has_watch:
            _add_note(
                warning_details, warnings, WARNING_INTELLIGENCE_GUIDANCE_MISSING,
                "intelligence brief lacks developer guidance")
    elif requires_practical and not has_practical:
        _add_note(
            issue_details, issues, ISSUE_REQUIRES_PRACTICAL_GUIDANCE,
            "requires practical guidance but none found")

    # Check for code examples when required.
    if artifact_spec.get("requires_code_block") and "```" not in draft.body:
        _add_note(
            issue_details, issues, ISSUE_REQUIRES_CODE_EXAMPLES,
            "requires code examples but none provided")

    # Check for empty action sections (present but lacking substance).
    # This is a hard failure: artifact requires actionability but has none.
    action_section_keywords = ("## action items", "## migration steps", "## compatibility notes", "## what you need to know")
    has_action_header = any(kw in body_lower for kw in action_section_keywords)
    if has_action_header:
        # Check if the action section has substantive content (more than 20 words).
        for kw in action_section_keywords:
            if kw in body_lower:
                idx = body_lower.find(kw)
                if idx >= 0:
                    # Get content after the header until next ## or EOF.
                    after_header = body_lower[idx + len(kw):]
                    next_section = after_header.find("\n## ")
                    if next_section > 0:
                        section_content = after_header[:next_section].strip()
                    else:
                        section_content = after_header.strip()
                    # Count words in the section.
                    words = len(section_content.split())
                    if words < 20:
                        _add_note(
                            issue_details, issues, ISSUE_ACTION_SECTION_LACKS_SUBSTANCE,
                            "action section present but lacks substance")
                        break

    # Compute score.
    issue_codes = {note.code for note in issue_details}
    warning_codes = {note.code for note in warning_details}
    score = max_weight
    if ISSUE_REQUIRES_PRACTICAL_GUIDANCE in issue_codes:
        score -= 15
    if ISSUE_REQUIRES_CODE_EXAMPLES in issue_codes:
        score -= 8
    if ISSUE_ACTION_SECTION_LACKS_SUBSTANCE in issue_codes:
        score -= 25  # Severe penalty for empty action sections.
    if WARNING_INTELLIGENCE_GUIDANCE_MISSING in warning_codes:
        score -= 3

    score = max(0, min(max_weight, score))

    return ComponentResult(
        name=PRACTICAL_VALUE,
        score=score,
        max_weight=max_weight,
        issues=tuple(issues),
        warnings=tuple(warnings),
        issue_details=tuple(issue_details),
        warning_details=tuple(warning_details),
    )


def _score_structure_readability(
        draft: DraftInput,
        config: QualityConfig,
) -> ComponentResult:
    """Component 4: Structure and readability (0-15)."""
    issues: list[str] = []
    warnings: list[str] = []
    issue_details: list[QualityNote] = []
    warning_details: list[QualityNote] = []
    max_weight = config.weights[STRUCTURE_READABILITY]

    # Check for malformed Markdown.
    if _has_malformed_markdown(draft.body):
        _add_note(
            issue_details, issues, ISSUE_MALFORMED_MARKDOWN,
            "malformed Markdown detected")

    # Check for truncated sentences.
    if _has_truncated_sentence(draft.body):
        _add_note(
            warning_details, warnings, WARNING_TRUNCATED_SENTENCE,
            "truncated sentence at end")

    # Check for repetitive filler.
    filler = _detect_repetitive_filler(draft.body)
    if filler:
        _add_note(
            warning_details, warnings, WARNING_GENERIC_FILLER,
            f"generic filler detected: {', '.join(filler[:3])}")

    # Check for excessively long paragraphs (>200 words).
    paragraphs = draft.body.split("\n\n")
    long_paras = [p for p in paragraphs if len(p.split()) > 200]
    if long_paras:
        _add_note(
            warning_details, warnings, WARNING_LONG_PARAGRAPH,
            f"{len(long_paras)} paragraph(s) exceed 200 words")

    # Check for duplicated intro/conclusion (simple heuristic).
    if draft.body.startswith("In this article") or draft.body.startswith("In this tutorial"):
        _add_note(
            warning_details, warnings, WARNING_GENERIC_INTRO,
            "generic intro pattern detected")

    # Compute score.
    issue_codes = {note.code for note in issue_details}
    warning_codes = {note.code for note in warning_details}
    score = max_weight
    if ISSUE_MALFORMED_MARKDOWN in issue_codes:
        score -= 5
    if WARNING_TRUNCATED_SENTENCE in warning_codes:
        score -= 3
    # Scale filler penalty: -2 per filler, max -8
    if filler:
        score -= min(8, len(filler) * 2)
    if long_paras:
        score -= 2
    if WARNING_GENERIC_INTRO in warning_codes:
        score -= 2

    score = max(0, min(max_weight, score))

    return ComponentResult(
        name=STRUCTURE_READABILITY,
        score=score,
        max_weight=max_weight,
        issues=tuple(issues),
        warnings=tuple(warnings),
        issue_details=tuple(issue_details),
        warning_details=tuple(warning_details),
    )


def _score_language_originality(
        draft: DraftInput,
        config: QualityConfig,
) -> ComponentResult:
    """Component 5: Language discipline and originality (0-20)."""
    issues: list[str] = []
    warnings: list[str] = []
    issue_details: list[QualityNote] = []
    warning_details: list[QualityNote] = []
    max_weight = config.weights[LANGUAGE_ORIGINALITY]

    # Check forbidden phrases directly (no dependency on content_formats registry).
    body_lower = draft.body.lower()
    forbidden_found = []
    for phrase in FORBIDDEN_PHRASES:
        if phrase in body_lower:
            _add_note(
                issue_details, issues, ISSUE_FORBIDDEN_PHRASE,
                f"forbidden phrase: {phrase}")
            forbidden_found.append(phrase)

    # Check for prompt leakage.
    leakage = _detect_prompt_leakage(draft.body)
    if leakage:
        _add_note(
            issue_details, issues, ISSUE_PROMPT_LEAKAGE,
            f"prompt leakage detected: {', '.join(leakage)}")

    # Check for excessive hedging.
    hedges = re.findall(r"\b(maybe|perhaps|possibly|might|could|seems|appears)\b", draft.body.lower())
    if len(hedges) > 10:
        _add_note(
            warning_details, warnings, WARNING_EXCESSIVE_HEDGING,
            f"excessive hedging ({len(hedges)} instances)")

    # Check for title-body mismatch.
    if draft.title and draft.body:
        title_words = set(re.findall(r"\b\w+\b", draft.title.lower()))
        body_words = set(re.findall(r"\b\w+\b", draft.body.lower()))
        overlap = title_words & body_words
        if len(title_words) > 3 and len(overlap) / len(title_words) < 0.3:
            _add_note(
                warning_details, warnings, WARNING_TITLE_BODY_LOW_OVERLAP,
                "title and body have low word overlap")

    # Check for source-copy similarity.
    sim_ratio = _compute_similarity_ratio(draft.body, draft.sources)
    if sim_ratio > config.similarity_allowance:
        _add_note(
            issue_details, issues, ISSUE_SOURCE_COPY_SIMILARITY,
            f"source-copy similarity {sim_ratio:.2f} exceeds allowance {config.similarity_allowance}")

    # Compute score.
    issue_codes = {note.code for note in issue_details}
    warning_codes = {note.code for note in warning_details}
    score = max_weight
    # Each forbidden phrase = -3.
    score -= len(forbidden_found) * 3
    if ISSUE_PROMPT_LEAKAGE in issue_codes:
        score -= 10
    if WARNING_EXCESSIVE_HEDGING in warning_codes:
        score -= 3
    if WARNING_TITLE_BODY_LOW_OVERLAP in warning_codes:
        score -= 2
    if ISSUE_SOURCE_COPY_SIMILARITY in issue_codes:
        score -= 10

    score = max(0, min(max_weight, score))

    return ComponentResult(
        name=LANGUAGE_ORIGINALITY,
        score=score,
        max_weight=max_weight,
        issues=tuple(issues),
        warnings=tuple(warnings),
        issue_details=tuple(issue_details),
        warning_details=tuple(warning_details),
    )


# ── Hard-failure checks ─────────────────────────────────────────────────────

def _check_hard_failures(
        draft: DraftInput,
        config: QualityConfig,
) -> tuple[list[str], list[str]]:
    """Check for hard failures. Returns (hard_failures, issues)."""
    hard_failures: list[str] = []
    issues: list[str] = []

    # HF_MISSING_PRIMARY_SOURCES: has claims but no sources.
    if draft.claims and not draft.sources:
        hard_failures.append(HF_MISSING_PRIMARY_SOURCES)
        issues.append("hard failure: missing required primary sources")
    # Also check for numeric claims indicated by metadata.
    if draft.metadata.get("has_numeric_claims") and not draft.sources:
        if HF_MISSING_PRIMARY_SOURCES not in hard_failures:
            hard_failures.append(HF_MISSING_PRIMARY_SOURCES)
            issues.append("hard failure: missing required primary sources")

    # HF_FABRICATED_NUMERIC: numeric claims with no source.
    numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", draft.body)
    if numbers and not draft.sources and draft.metadata.get("has_numeric_claims"):
        hard_failures.append(HF_FABRICATED_NUMERIC)
        issues.append("hard failure: ungrounded numeric claim")

    # HF_MALFORMED_OUTPUT: malformed Markdown.
    if _has_malformed_markdown(draft.body):
        hard_failures.append(HF_MALFORMED_OUTPUT)
        issues.append("hard failure: malformed output")

    # HF_BLANK_REQUIRED_SECTION: required section present but empty.
    body_lower = draft.body.lower()
    for section_match in re.finditer(r"^## (.+)$", draft.body, re.MULTILINE):
        section_name = section_match.group(1).strip()
        # Find content after this heading until next heading or EOF.
        start = section_match.end()
        next_heading = re.search(r"^## ", draft.body[start:], re.MULTILINE)
        if next_heading:
            content = draft.body[start:start + next_heading.start()].strip()
        else:
            content = draft.body[start:].strip()
        if not content:
            hard_failures.append(HF_BLANK_REQUIRED_SECTION)
            issues.append(f"hard failure: blank required section: {section_name}")
            break  # One is enough.

    # HF_PROMPT_LEAKAGE.
    leakage = _detect_prompt_leakage(draft.body)
    if leakage:
        hard_failures.append(HF_PROMPT_LEAKAGE)
        issues.append(f"hard failure: prompt leakage: {', '.join(leakage)}")

    # HF_CONTRADICTS_FACTS: article contradicts confirmed facts.
    # (Simplified — full implementation would compare claims to facts.)
    if draft.metadata.get("contradicts_confirmed"):
        hard_failures.append(HF_CONTRADICTS_FACTS)
        issues.append("hard failure: contradicts confirmed facts")

    # HF_VENDOR_AS_VERIFIED: vendor claim presented as independently verified.
    vendor_claims = re.findall(r"\b(?:performance|speed|throughput|latency|accuracy)\s+(?:is|was|reaches?|improved?|increased?|decreased?|dropped?)\s+\d+", draft.body.lower())
    if vendor_claims and not any(phrase in draft.body.lower() for phrase in
                                  ("according to", "claimed by", "vendor states")):
        hard_failures.append(HF_VENDOR_AS_VERIFIED)
        issues.append("hard failure: vendor claim as verified")

    # HF_COPIED_PASSAGE: similarity exceeds allowance.
    sim_ratio = _compute_similarity_ratio(draft.body, draft.sources)
    if sim_ratio > config.similarity_allowance:
        hard_failures.append(HF_COPIED_PASSAGE)
        issues.append(f"hard failure: copied passage ({sim_ratio:.2f} > {config.similarity_allowance})")

    # HF_UNSUPPORTED_SECURITY: security/legal claim without source.
    security_keywords = ("vulnerability", "cve", "exploit", "security issue", "legal risk")
    has_security = any(kw in draft.body.lower() for kw in security_keywords)
    if has_security and not draft.sources:
        hard_failures.append(HF_UNSUPPORTED_SECURITY)
        issues.append("hard failure: unsupported security/legal claim")

    return hard_failures, issues


# ── Main scoring function ───────────────────────────────────────────────────

def evaluate_quality(
        draft: DraftInput,
        config: QualityConfig | None = None,
) -> QualityResult:
    """Score a draft. Deterministic, no LLM, no network, no writes."""
    if config is None:
        config = load_quality_config()

    # Get artifact-specific policy.
    artifact_spec = config.artifacts.get(draft.artifact_type, {})

    # Check hard failures first.
    hard_failures, hard_issues = _check_hard_failures(draft, config)

    # Score each component.
    c1 = _score_format_conformance(draft, config, artifact_spec)
    c2 = _score_specificity_evidence(draft, config)
    c3 = _score_practical_value(draft, config, artifact_spec)
    c4 = _score_structure_readability(draft, config)
    c5 = _score_language_originality(draft, config)

    components = (c1, c2, c3, c4, c5)
    total_score = sum(c.score for c in components)

    # Collect all issues and warnings.
    all_issues = list(hard_issues)
    all_warnings: list[str] = []
    all_issue_details: list[QualityNote] = []
    all_warning_details: list[QualityNote] = []
    for c in components:
        all_issues.extend(c.issues)
        all_warnings.extend(c.warnings)
        all_issue_details.extend(c.issue_details)
        all_warning_details.extend(c.warning_details)

    # Determine status.
    if hard_failures:
        status = STATUS_FAIL
    elif total_score >= config.thresholds["pass"]:
        status = STATUS_PASS
    elif total_score >= config.thresholds["warning"]:
        status = STATUS_WARNING
    else:
        status = STATUS_FAIL

    return QualityResult(
        score=total_score,
        status=status,
        components=components,
        hard_failures=tuple(hard_failures),
        issues=tuple(all_issues),
        warnings=tuple(all_warnings),
        issue_details=tuple(all_issue_details),
        warning_details=tuple(all_warning_details),
        artifact_type=draft.artifact_type,
        format_id=draft.format_id,
        version=1,
    )
