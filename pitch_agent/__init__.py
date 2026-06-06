"""The Pitch Agent — independent World Cup analytics.

The Pitch Agent is an independent analytics project and is not affiliated
with FIFA, FIFA World Cup, or any official tournament organizer.
"""

__version__ = "1.0.0-lite"

# The scoring model is frozen as "Form Index v1.0 Lite". MODEL_VERSION is the
# machine identifier stored in the database; MODEL_VERSION_LABEL is the public,
# human-facing name used in charts, content metadata, and the methodology page.
MODEL_VERSION = "1.0.0-lite"
MODEL_VERSION_LABEL = "Form Index v1.0 Lite"

FORM_INDEX_PUBLIC_EXPLANATION = (
    "Form Index v1.0 Lite is a simple 0–100 player performance score based on "
    "goals, assists, minutes, cards, clean sheet impact, and team result."
)

TRADEMARK_DISCLAIMER = (
    "The Pitch Agent is an independent analytics project and is not affiliated "
    "with FIFA, FIFA World Cup, or any official tournament organizer."
)