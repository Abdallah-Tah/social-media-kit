"""Performance signal collectors for the Content Intelligence Engine."""
from __future__ import annotations

from .pitch_agent import collect_pitch_agent_metrics, generate_pitch_report

__all__ = ["collect_pitch_agent_metrics", "generate_pitch_report"]
