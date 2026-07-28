"""Editorial decision layer (Phase 1) — dormant until the cadence cutover.

Sits between the existing feed intelligence (agent/feed_authority.py,
agent/feed_clustering.py, agent/feed_opportunity.py) and the existing
publishers. Composes them; does not replace them.

Stage 1 ships the feature flag, the slot configuration loader, and the twelve
editorial formats. Scoring, saturation, admission, readiness, and the brief
generators arrive in later stages.

Nothing here runs in production while EDITORIAL_SLOTS_ENABLED is false, and the
editorial formats are structurally isolated from the live rotation registries
regardless of that flag — see tests/test_editorial_dormancy.py.
"""
from .flags import (
    editorial_shadow_mode,
    editorial_slots_enabled,
    editorial_timezone,
    editorial_zoneinfo,
)
from .candidate_adapter import (
    NormalizationConfig,
    NormalizationConfigError,
    load_normalization_config,
    normalize_and_score,
    normalize_candidate,
    normalize_many,
)
from .models import (
    DEVELOPMENT_TYPES,
    NormalizationError,
)
from .slots import (
    ContentType,
    Slot,
    SlotConfig,
    SlotConfigError,
    load_slots,
)
from .source_confidence import (
    Candidate,
    Claim,
    Component,
    ScoringConfig,
    ScoringConfigError,
    SourceConfidence,
    SourceRef,
    load_scoring_config,
    registrable_domain,
    score_source_confidence,
)

__all__ = [
    "DEVELOPMENT_TYPES",
    "Candidate",
    "Claim",
    "Component",
    "ContentType",
    "NormalizationConfig",
    "NormalizationConfigError",
    "NormalizationError",
    "load_normalization_config",
    "normalize_and_score",
    "normalize_candidate",
    "normalize_many",
    "ScoringConfig",
    "ScoringConfigError",
    "Slot",
    "SlotConfig",
    "SlotConfigError",
    "SourceConfidence",
    "SourceRef",
    "editorial_shadow_mode",
    "editorial_slots_enabled",
    "editorial_timezone",
    "editorial_zoneinfo",
    "load_scoring_config",
    "load_slots",
    "registrable_domain",
    "score_source_confidence",
]
