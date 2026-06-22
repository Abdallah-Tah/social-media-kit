"""Content Intelligence Engine for smkit.

Phase 1: discover, score, and prioritize content opportunities.
No content generation here — only intelligence and scoring.
"""

from .engine import IntelligenceEngine, run_intelligence

__all__ = ["IntelligenceEngine", "run_intelligence"]
