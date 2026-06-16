"""Content packaging for The Pitch Agent World Cup shorts.

Generates the things that actually win views: curiosity-gap titles,
thumbnail text, a 1.5-second hook, and a caption with the retention-loop
CTA — all built around the prediction-accountability angle (see
WORLDCUP_GROWTH_STRATEGY.md).

Pure text generation. Publishes NOTHING. No network, no LLM — fully
deterministic and testable so it can be wired into the publish path later
with confidence. The running "Report Card" line is read from real graded
predictions via backtest.evaluate (read-only).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "pitch_agent.db"

_OUTCOME_WORD = {"home": "win", "away": "win", "draw": "draw"}


def report_card_line(db_path: Path | None = None) -> str:
    """The running accountability tally to stamp on every video.

    Returns e.g. "The Pitch Agent: 9/15 calls correct - Brier 0.21
    (beating the coin-flip)". Falls back gracefully before any games are
    graded. Read-only.
    """
    from pitch_agent.backtest import evaluate, load_graded

    path = db_path or DB_PATH
    if not Path(path).exists():
        return "The Pitch Agent: tracking every World Cup call"
    conn = sqlite3.connect(path)
    try:
        m = evaluate(load_graded(conn))
    finally:
        conn.close()
    if not m or m.get("n", 0) == 0:
        return "The Pitch Agent: tracking every World Cup call"
    correct = round(m["accuracy"] * m["n"])
    edge = m["baseline_uniform_brier"] - m["brier"]
    tail = "beating the coin-flip" if edge > 0 else "learning fast"
    return (f"The Pitch Agent: {correct}/{m['n']} calls correct "
            f"- Brier {m['brier']:.2f} ({tail})")


def confidence_tier(prob: float, margin: float) -> str:
    """How confident the model is, in plain words (drives the title verb)."""
    if margin < 0.06:
        return "tossup"
    if prob >= 0.55:
        return "strong"
    if prob >= 0.45:
        return "lean"
    return "slight"


def pre_match_titles(
    home: str, away: str, predicted: str, prob: float,
    second_prob: float, favorite_is_lower_elo: bool = False,
) -> list[str]:
    """Curiosity-gap title candidates for a PRE-kickoff prediction short."""
    pct = round(prob * 100)
    tier = confidence_tier(prob, prob - second_prob)
    pick = {"home": home, "away": away, "draw": "a draw"}[predicted]
    titles: list[str] = []

    if favorite_is_lower_elo and predicted != "draw":
        titles.append(f"Our AI is calling an UPSET: {home} vs {away} \U0001F916")
        titles.append(f"The AI thinks {pick} shocks {away if predicted=='home' else home} today")
    if tier == "tossup":
        titles.append(f"{home} vs {away}: even our AI can't split it \U0001F916")
        titles.append(f"The AI says {home} vs {away} is a coin-flip. Here's its lean")
    elif tier == "strong":
        titles.append(f"Our AI is {pct}% sure about {home} vs {away}")
        titles.append(f"The AI has no doubt about {home} vs {away} \U0001F916")
    else:
        titles.append(f"Our AI's call for {home} vs {away} might surprise you")
        titles.append(f"{home} vs {away}: what the AI is predicting \U0001F916")
    titles.append(f"AI predicts {home} vs {away} — result tonight")
    # De-dup, keep order, cap length
    seen, out = set(), []
    for t in titles:
        if t not in seen and len(t) <= 90:
            seen.add(t); out.append(t)
    return out


def post_match_titles(home: str, away: str, hs: int, as_: int, correct: bool) -> list[str]:
    """Payoff title candidates for a POST-result short."""
    score = f"{hs}-{as_}"
    if correct:
        return [
            f"Called it. \U0001F916 {home} {score} {away}",
            f"Our AI nailed {home} vs {away} ({score})",
            f"The AI was RIGHT about {home} vs {away}",
        ]
    return [
        f"The AI got cooked \U0001F480 {home} {score} {away}",
        f"Our AI was WRONG about {home} vs {away} ({score})",
        f"Welp. The AI missed {home} vs {away} — here's why",
    ]


def thumbnail_text(predicted: str, home: str, away: str, correct: bool | None = None) -> str:
    """<=4 words, high-contrast, for the in-feed/search thumbnail."""
    from pitch_agent.poisson import TEAM_CODES
    if correct is True:
        return "CALLED IT"
    if correct is False:
        return "AI WAS WRONG"
    if predicted == "draw":
        return "AI: DRAW?"
    pick = home if predicted == "home" else away
    # Use the FIFA code for long names so the thumbnail never truncates mid-word.
    label = pick.upper() if len(pick) <= 9 else TEAM_CODES.get(pick, pick[:9].upper())
    return f"AI: {label}"


def hook(home: str, away: str, predicted: str, prob: float) -> str:
    """The first ~1.5 seconds of narration — the whole video lives or dies here."""
    pct = round(prob * 100)
    if predicted == "draw":
        return f"Our AI thinks {home} and {away} cancel each other out."
    pick = home if predicted == "home" else away
    return f"Our AI says {pick} wins this — and it's {pct}% sure."


def caption(home: str, away: str, kind: str, db_path: Path | None = None) -> str:
    """Caption + retention-loop CTA + hashtags. kind: 'pre' or 'post'."""
    cta = ("Result drops tonight — follow to see if it nailed it."
           if kind == "pre" else
           "New call every match. Follow the run.")
    tags = "#WorldCup2026 #footballpredictions #ai #soccer #worldcup"
    return f"{report_card_line(db_path)}\n{cta}\n\n{tags}"


if __name__ == "__main__":  # quick manual demo
    print("REPORT CARD:", report_card_line())
    print("\nPRE titles (upset, lean):")
    for t in pre_match_titles("Morocco", "Spain", "home", 0.44, 0.33, favorite_is_lower_elo=True):
        print("  -", t)
    print("\nPOST titles (wrong):")
    for t in post_match_titles("Canada", "Bosnia-H.", 1, 1, correct=False):
        print("  -", t)
    print("\nthumbnail:", thumbnail_text("home", "Morocco", "Spain"))
    print("hook:", hook("Morocco", "Spain", "home", 0.44))
    print("\ncaption(pre):\n", caption("Morocco", "Spain", "pre"))
