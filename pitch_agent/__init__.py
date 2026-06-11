"""The Pitch Agent — independent World Cup analytics.

The Pitch Agent is an independent analytics project and is not affiliated
with FIFA, FIFA World Cup, or any official tournament organizer.
"""

__version__ = "1.1.0"

# The scoring model is now "Form Index v1.1". MODEL_VERSION is the
# machine identifier stored in the database; MODEL_VERSION_LABEL is the public,
# human-facing name used in charts, content metadata, and the methodology page.
# v1.1 changes: minutes=-1 (unknown) handling instead of fabricated 90/0,
# and the unknown-minutes multiplier is configurable.
MODEL_VERSION = "1.1.0"
MODEL_VERSION_LABEL = "Form Index v1.1"

FORM_INDEX_PUBLIC_EXPLANATION = (
    "Form Index v1.1 is a simple 0–100 player performance score based on "
    "goals, assists, minutes, cards, clean sheet impact, and team result. "
    "Unknown minutes (free-tier data) receive a 0.90 multiplier."
)

TRADEMARK_DISCLAIMER = (
    "The Pitch Agent is an independent analytics project and is not affiliated "
    "with FIFA, FIFA World Cup, or any official tournament organizer."
)