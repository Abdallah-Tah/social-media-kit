"""Stage 7C.8 — Structured Evidence Extraction.

Parse fetched evidence into structured SourceRef, Claim, and practical-signal
data using bounded LLM extraction with grounding validation.

Pipeline:
  retrieve evidence → extract structured evidence → validate extraction →
  merge into Candidate → rerun source relationships → rerun source confidence →
  rerun admission

Grounding rules:
- Every material claim must reference at least one supplied source URL
- Every claim must include a short supporting excerpt found verbatim in fetched text
- Reject claims whose excerpts cannot be matched
- Never invent missing dates, versions, prices, benchmarks, or API details
- Vendor claims remain vendor_claim unless independent evidence supports them
- Independent corroboration requires separate organization and added evidence
- Commentary alone is not independent evidence
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent import llm_ops
from .evidence_merge import merge_extraction_into_candidate
from .models import Candidate

KIT = Path(__file__).resolve().parents[2]
EXTRACTION_CACHE_PATH = KIT / "content" / "feed" / "evidence_extraction_cache.json"
EXTRACTION_SCHEMA_VERSION = 1

# Configuration defaults
# LLM extraction is OFF by default (paid); enable explicitly.
DEFAULT_EXTRACTION_ENABLED = False
DEFAULT_MAX_CANDIDATES_PER_RUN = 10
DEFAULT_MAX_INPUT_CHARS = 50000
DEFAULT_DAILY_BUDGET_USD = 5.0
DEFAULT_MODEL = "gpt-4o-mini"  # Cost-efficient for structured extraction


@dataclass(frozen=True)
class ExtractionConfig:
    """Configuration for structured evidence extraction."""
    enabled: bool = DEFAULT_EXTRACTION_ENABLED
    max_candidates_per_run: int = DEFAULT_MAX_CANDIDATES_PER_RUN
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS
    daily_budget_usd: float = DEFAULT_DAILY_BUDGET_USD
    model: str = DEFAULT_MODEL
    cache_path: Path = EXTRACTION_CACHE_PATH


def load_extraction_config() -> ExtractionConfig:
    """Load config from environment or use defaults."""
    return ExtractionConfig(
        enabled=os.environ.get("EDITORIAL_EVIDENCE_EXTRACTION_ENABLED", "false").lower() in ("true", "1", "yes"),
        max_candidates_per_run=int(os.environ.get("EDITORIAL_EVIDENCE_EXTRACTION_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES_PER_RUN)),
        max_input_chars=int(os.environ.get("EDITORIAL_EVIDENCE_EXTRACTION_MAX_INPUT_CHARS", DEFAULT_MAX_INPUT_CHARS)),
        daily_budget_usd=float(os.environ.get("EDITORIAL_EVIDENCE_EXTRACTION_DAILY_BUDGET_USD", DEFAULT_DAILY_BUDGET_USD)),
        model=os.environ.get("EDITORIAL_EVIDENCE_EXTRACTION_MODEL", DEFAULT_MODEL),
    )


def candidate_fingerprint(candidate: dict[str, Any]) -> str:
    """Fingerprint candidate for caching."""
    basis = json.dumps({
        "title": candidate.get("title", ""),
        "url": candidate.get("url", ""),
        "source": candidate.get("source", ""),
    }, sort_keys=True)
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def evidence_fingerprint(fetched_evidence: list[dict[str, Any]]) -> str:
    """Fingerprint fetched evidence for caching."""
    basis = json.dumps([
        {"url": e.get("url", ""), "content": e.get("content", "")[:1000]}
        for e in fetched_evidence
    ], sort_keys=True)
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def build_extraction_prompt(candidate: dict[str, Any], config: ExtractionConfig,
                            cleaned_evidence: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """Build LLM prompt for structured evidence extraction.

    If cleaned_evidence is provided (boilerplate-stripped article text), it is
    used instead of the raw fetched content, so the size limit applies to clean
    article text rather than raw HTML.
    """
    fetched_evidence = (cleaned_evidence if cleaned_evidence is not None
                        else candidate.get("metadata", {}).get("fetched_evidence", []))
    
    # Build bounded evidence text
    evidence_text = ""
    source_urls = []
    for e in fetched_evidence:
        url = e.get("url", "")
        content = e.get("content", "")
        if url and content:
            source_urls.append(url)
            evidence_text += f"\n\n=== SOURCE: {url} ===\n{content[:5000]}"
    
    # Truncate to max input chars
    evidence_text = evidence_text[:config.max_input_chars]
    
    system_prompt = """You are a structured evidence extraction system for technical news candidates.

Extract structured evidence from fetched source content. You must ground every claim in the supplied text.

GROUNDING RULES (CRITICAL):
1. Every material claim MUST reference at least one supplied source URL
2. Every claim MUST include a short supporting excerpt found VERBATIM in the fetched text
3. NEVER invent missing dates, versions, prices, benchmarks, or API details
4. Vendor claims MUST be labeled "vendor_claim" unless independent evidence supports them
5. Independent corroboration requires a separate organization AND added evidence
6. Commentary alone is NOT independent evidence

OUTPUT FORMAT (JSON):
{
  "event": {
    "development_type": "model_release|api_release|product_release|repository_release|research_paper|security_issue|pricing_change|licensing_change|documentation_update|deployment_availability|compatibility_change|funding_or_company_news|unknown",
    "subject_org": "openai|anthropic|google|microsoft|... (lowercase)",
    "subject_name": "GPT-5|Claude 4|... (specific product/version)",
    "release_or_event_id": "version number, CVE ID, PR number, or empty",
    "event_time": "YYYY-MM-DD or null if not found",
    "availability_status": "available|beta|preview|announced|unknown"
  },
  "claims": [
    {
      "text": "concise claim statement",
      "claim_type": "version_fact|pricing|benchmark|security|feature|performance|availability|other",
      "material": true,
      "vendor_provided": false,
      "verification": "verified|vendor_claim|independently_supported|unknown",
      "source_urls": ["https://..."],
      "evidence_quotes": ["exact excerpt from fetched text"]
    }
  ],
  "practical_signals": {
    "has_code_change": false,
    "has_api_change": false,
    "has_repository_reference": false,
    "has_documentation_reference": false,
    "has_deployment_impact": false,
    "has_compatibility_impact": false,
    "has_migration_requirement": false,
    "has_security_action": false,
    "has_pricing_impact": false,
    "has_reproducible_test": false,
    "has_architecture_implication": false,
    "has_developer_decision": false,
    "has_tooling_impact": false
  },
  "recommended_artifact_types": ["technical_analysis|intelligence_brief|tutorial_deep_dive|..."],
  "warnings": ["any extraction issues"]
}

VALIDATION:
- Only include claims with verbatim excerpts from the fetched text
- Only include practical signals supported by claims
- If evidence is insufficient, return empty claims array with warnings
"""

    user_prompt = f"""CANDIDATE:
Title: {candidate.get('title', '')}
Summary: {candidate.get('summary', '')}
Source: {candidate.get('source', '')}
URL: {candidate.get('url', '')}

SUPPLIED SOURCE URLS:
{json.dumps(source_urls, indent=2)}

FETCHED EVIDENCE TEXT:
{evidence_text}

Extract structured evidence following the grounding rules. Return valid JSON only."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def validate_extraction(
    extraction: dict[str, Any],
    fetched_evidence: list[dict[str, Any]],
    source_urls: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Validate extraction against grounding rules.
    
    Returns (validated_extraction, rejection_reasons).
    """
    rejections = []
    
    # Validate claims
    validated_claims = []
    for claim in extraction.get("claims", []):
        # Check source URLs were supplied
        claim_urls = claim.get("source_urls", [])
        if not claim_urls:
            rejections.append(f"Claim has no source URLs: {claim.get('text', '')[:50]}")
            continue
        if not all(url in source_urls for url in claim_urls):
            rejections.append(f"Claim references unsupplied URL: {claim_urls}")
            continue
        
        # Check evidence quotes exist in fetched text
        evidence_quotes = claim.get("evidence_quotes", [])
        if not evidence_quotes:
            rejections.append(f"Claim has no evidence quotes: {claim.get('text', '')[:50]}")
            continue
        
        # Verify at least one quote exists verbatim in fetched text
        fetched_text = "\n".join(e.get("content", "") for e in fetched_evidence)
        quote_found = any(quote in fetched_text for quote in evidence_quotes)
        if not quote_found:
            rejections.append(f"Claim excerpt not found in fetched text: {evidence_quotes[0][:50]}")
            continue
        
        validated_claims.append(claim)
    
    extraction["claims"] = validated_claims
    
    # Validate practical signals (must be supported by claims)
    if not validated_claims:
        # No claims = no signals
        extraction["practical_signals"] = {k: False for k in extraction.get("practical_signals", {})}
    
    return extraction, rejections


def extract_structured_evidence(
    candidates: list[dict[str, Any]],
    config: ExtractionConfig | None = None,
) -> tuple[list[Candidate], dict[str, Any]]:
    """Extract structured evidence from fetched evidence using LLM.
    
    Converts dict candidates to Candidate objects, extracts evidence,
    validates, merges into new immutable Candidates, and returns merged Candidates.
    
    Returns (merged_candidates, metrics).
    """
    if config is None:
        config = load_extraction_config()
    
    if not config.enabled:
        # Convert to Candidate objects without extraction
        from .candidate_adapter import normalize_candidate
        return [normalize_candidate(c) for c in candidates], {"enabled": False}
    
    # Load cache
    cache: dict[str, Any] = {}
    if config.cache_path.exists():
        try:
            cache = json.loads(config.cache_path.read_text())
        except Exception:
            cache = {}
    
    # Select top candidates
    top_candidates = candidates[:config.max_candidates_per_run]
    remaining = candidates[config.max_candidates_per_run:]
    
    metrics: dict[str, Any] = {
        "enabled": True,
        "candidates_extracted": 0,
        "claims_accepted": 0,
        "claims_rejected": 0,
        "cache_hits": 0,
        "llm_calls": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "total_latency_ms": 0,
        "validation_failures": [],
        "candidates_merged": 0,
    }
    
    merged_candidates: list[Candidate] = []
    
    # Convert remaining candidates without extraction
    from .candidate_adapter import normalize_candidate
    for candidate_dict in remaining:
        try:
            merged_candidates.append(normalize_candidate(candidate_dict))
        except Exception:
            pass  # Skip invalid candidates
    
    # Process top candidates with extraction
    for candidate_dict in top_candidates:
        fetched_evidence = candidate_dict.get("metadata", {}).get("fetched_evidence", [])
        
        # Convert to Candidate object
        try:
            candidate = normalize_candidate(candidate_dict)
        except Exception as e:
            metrics["validation_failures"].append(f"Failed to adapt candidate: {e}")
            continue
        
        if not fetched_evidence:
            merged_candidates.append(candidate)
            continue

        # Clean the fetched evidence (strip page boilerplate) before extraction so
        # the input budget is spent on article text, not raw HTML chrome.
        from .content_cleaning import assess_source_quality, clean_fetched_evidence
        from agent.feed import canonical_url
        fallback_text = str(candidate_dict.get("summary", "") or candidate_dict.get("title", "") or "")
        cleaned_evidence, cleaning_diags = clean_fetched_evidence(
            fetched_evidence, fallback_text=fallback_text)
        metrics.setdefault("cleaning_diagnostics", []).extend(cleaning_diags)

        # Source-quality filter: skip low-value sources BEFORE any paid extraction
        # (aggregator redirects, JS-only pages, no readable body, insufficient
        # text, duplicate canonical URLs, unsupported domains). Skip reasons are
        # recorded without an LLM call.
        seen_canonical: set[str] = set()
        filtered_evidence: list[dict[str, Any]] = []
        for raw, cleaned, diag in zip(fetched_evidence, cleaned_evidence, cleaning_diags):
            url = raw.get("url", "")
            usable, skip_reason = assess_source_quality(
                url, raw.get("content", ""), diag, seen_canonical)
            if usable:
                filtered_evidence.append(cleaned)
                canonical = canonical_url(url)
                if canonical:
                    seen_canonical.add(canonical)
            else:
                metrics.setdefault("source_quality_skips", []).append(
                    {"url": url, "skip_reason": skip_reason})
        cleaned_evidence = filtered_evidence

        if not cleaned_evidence:
            # No usable evidence after filtering; skip extraction (no LLM call).
            merged_candidates.append(candidate)
            continue

        # Check cache
        cand_fp = candidate_fingerprint(candidate_dict)
        evidence_fp = evidence_fingerprint(fetched_evidence)
        cache_key = f"{cand_fp}_{evidence_fp}_v{EXTRACTION_SCHEMA_VERSION}_{config.model}"
        
        if cache_key in cache:
            extraction = cache[cache_key]
            metrics["cache_hits"] += 1
        else:
            # Build prompt and call LLM (using cleaned article text)
            messages = build_extraction_prompt(candidate_dict, config, cleaned_evidence=cleaned_evidence)
            result = llm_ops.chat(
                messages,
                model=config.model,
                temperature=0.1,
                json_mode=True,
                timeout=60,
                job_id="editorial_evidence_extraction",
            )
            
            metrics["llm_calls"] += 1
            metrics["total_tokens"] += (result.input_tokens or 0) + (result.output_tokens or 0)
            metrics["total_cost_usd"] += result.cost_usd or 0.0
            metrics["total_latency_ms"] += result.duration_ms
            
            if not result.ok:
                metrics["validation_failures"].append(f"LLM call failed: {result.error}")
                merged_candidates.append(candidate)
                continue
            
            # Parse JSON
            try:
                extraction = result.json()
            except Exception:
                metrics["validation_failures"].append("Malformed JSON from LLM")
                merged_candidates.append(candidate)
                continue
            
            # Validate extraction (quotes must appear in the cleaned text the model saw)
            source_urls = [e.get("url", "") for e in cleaned_evidence if e.get("url")]
            extraction, rejections = validate_extraction(extraction, cleaned_evidence, source_urls)
            metrics["validation_failures"].extend(rejections)
            metrics["claims_rejected"] += len(rejections)
            
            # Cache extraction
            cache[cache_key] = extraction
        
        # Merge extraction into Candidate (source excerpts come from cleaned text)
        try:
            merged_candidate = merge_extraction_into_candidate(candidate, extraction, cleaned_evidence)
            merged_candidates.append(merged_candidate)
            metrics["candidates_extracted"] += 1
            metrics["candidates_merged"] += 1
            metrics["claims_accepted"] += len(extraction.get("claims", []))
        except Exception as e:
            metrics["validation_failures"].append(f"Merge failed: {e}")
            merged_candidates.append(candidate)  # Preserve original on merge failure
    
    # Save cache
    try:
        config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        config.cache_path.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass

    # Persist cleaning diagnostics (raw vs clean size, method, boilerplate ratio,
    # usable flag, failure reason) for the latest run.
    cleaning_diags = metrics.get("cleaning_diagnostics")
    if cleaning_diags:
        try:
            diag_path = config.cache_path.parent / "evidence_cleaning.json"
            diag_path.write_text(json.dumps(cleaning_diags, indent=2))
        except Exception:
            pass

    return merged_candidates, metrics
