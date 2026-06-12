"""Taco's self-improvement loop: act → log → evaluate → reflect → propose →
human gate → apply → measure.

Pure Python + SQLite, no new dependencies. Follows the conventions of
``pitch_agent`` (IF-NOT-EXISTS schema, idempotent migrations, explicit
version constants, manual grading).

The journal database is separate from ``pitch_agent.db`` on purpose: the
reflection loop must never be able to touch the scoring schema.
"""

__version__ = "1.0.0"
