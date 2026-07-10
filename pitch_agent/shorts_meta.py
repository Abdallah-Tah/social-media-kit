"""Shorts metadata + hook-variant generation for the World Cup prediction Shorts.

Football-first / curiosity-first. The AI/software identity SUPPORTS the hook; it
never leads with "I built a tool". Produces the structured fields the pipeline
and YouTube need, plus an A/B-testable bank of hook variants.

Hard rule: NO betting language. `assert_no_betting` guards every generated string.

Input `data` is the model read for a match (compatible with
`football_prediction_shorts.build_props` output / the predictions table):

    {
      "home": "England", "away": "Croatia", "competition": "World Cup 2026",
      "leader": "England",            # model's favoured side (or None for a draw)
      "verdict": "England to win",    # winner-only, never a scoreline
      "confidence": 58,               # leader win probability, %
      "factors": ["...", "...", "..."],
      "ledger": "16-10 · 61.5%",      # from pitch_agent.cli accuracy (immutable)
    }
"""
from __future__ import annotations

# Banned everywhere — this is an analytics/AI channel, not gambling.
BETTING_WORDS = (
    "odds", "lock", "tip", "best bet", "stake", "guaranteed", "parlay",
    "wager", "bet", "betting", "gamble", "gambling", "bookie", "bookmaker",
)

CTA_TEXT = "Follow BuildWithAbdallah for the next AI World Cup prediction."
TOP_CHIP = "AI MODEL • WORLD CUP PREDICTION"


class BettingLanguageError(ValueError):
    """Raised when generated copy contains banned gambling language."""


def assert_no_betting(*texts: str) -> None:
    import re
    for t in texts:
        if not t:
            continue
        low = t.lower()
        for w in BETTING_WORDS:
            if re.search(rf"\b{re.escape(w)}\b", low):
                raise BettingLanguageError(f"banned betting word {w!r} in: {t!r}")


def _underdog(d: dict) -> str:
    leader = d.get("leader")
    if leader == d.get("home"):
        return d["away"]
    if leader == d.get("away"):
        return d["home"]
    return d.get("away", "")


# ── Hook bank — football-first. Each returns ONE opening line. ────────────────
HOOK_BANK = {
    "factor_first": lambda d: f"One stat changed the {d['home']} vs {d['away']} prediction.",
    "match_tension": lambda d: f"{d['leader']} is favored — but {_underdog(d)} has one dangerous edge.",
    "result_curiosity": lambda d: f"My AI picked {d['leader']} — but it was closer than expected.",
    "model_surprise": lambda d: f"The model found one factor that could flip {d['home']} vs {d['away']}.",
    "fan_conflict": lambda d: (f"{d['leader']} fans will like the prediction. "
                               f"{_underdog(d)} fans will like the warning."),
}

# ── Template variants (the 3 with full frame treatments) ─────────────────────
VARIANTS = {
    "key-factor": {
        "name": "Key Factor Mystery",
        "hook_variant": "factor_first",
        "subheadline": "The model still favors {leader} — but not by much.",
        "factor_label": "THE STAT THAT CHANGED IT",
        "highlight_factor": True,   # emphasise one factor card
    },
    "match-tension": {
        "name": "Match Tension",
        "hook_variant": "match_tension",
        "subheadline": "The model backs {leader} — the warning is in the details.",
        "factor_label": "WHERE {underdog} CAN HURT {leader}",
        "highlight_factor": False,
    },
    "result-curiosity": {
        "name": "Result Curiosity",
        "hook_variant": "result_curiosity",
        "subheadline": "A narrow margin the model kept flagging.",
        "factor_label": "WHY IT WAS CLOSER THAN IT LOOKS",
        "highlight_factor": False,
    },
}
DEFAULT_VARIANT = "key-factor"


def select_template(variant: str | None) -> tuple[str, dict]:
    """Resolve a variant id to (id, config); falls back to the default."""
    vid = variant if variant in VARIANTS else DEFAULT_VARIANT
    return vid, VARIANTS[vid]


def generate_hook_variants(data: dict) -> list[dict]:
    """All hook variants for a match as structured, A/B-testable data (>=3)."""
    out = []
    for hv, fn in HOOK_BANK.items():
        hook = fn(data)
        assert_no_betting(hook)
        out.append({"hook_variant": hv, "hook": hook})
    return out


def _hashtags(data: dict) -> list[str]:
    def tag(s):
        return "#" + "".join(ch for ch in s.title() if ch.isalnum())
    base = ["#WorldCup2026", tag(data["home"]), tag(data["away"]),
            "#FootballAnalytics", "#AI", "#Soccer", "#Shorts"]
    seen, uniq = set(), []
    for t in base:
        if t.lower() not in seen:
            seen.add(t.lower()); uniq.append(t)
    return uniq


def generate_metadata(data: dict, variant: str | None = None) -> dict:
    """The full metadata bundle for one match + variant (task #7 fields)."""
    vid, cfg = select_template(variant)
    leader = data.get("leader") or data["home"]
    under = _underdog(data)
    hook = HOOK_BANK[cfg["hook_variant"]](data)
    sub = cfg["subheadline"].format(leader=leader, underdog=under)
    h, a = data["home"], data["away"]

    short_title = {
        "key-factor": f"One stat changed the {h} vs {a} prediction",
        "match-tension": f"{leader} favored — but {under} has one dangerous edge",
        "result-curiosity": f"My AI picked {leader} — closer than expected",
    }[vid]
    youtube_title = {
        "key-factor": f"AI World Cup Prediction: The Stat That Changed {h} vs {a}",
        "match-tension": f"{h} vs {a}: The AI Model's Warning",
        "result-curiosity": f"AI World Cup Prediction: {h} vs {a}",
    }[vid]
    youtube_description = (
        f"{hook} {sub}\n\n"
        f"The model's World Cup 2026 read on {h} vs {a}: the verdict "
        f"({data.get('verdict', leader + ' to win')}), the win probability, and the key "
        f"factors behind it.\n\n"
        f"An AI model that predicts every match and keeps a public record "
        f"({data.get('ledger', '')}). Independent analytics, not affiliated with FIFA.\n\n"
        f"{CTA_TEXT}\n\n" + " ".join(_hashtags(data))
    )
    pinned_comment = {
        "key-factor": (f"One factor made this {h} vs {a} call closer than it looks. "
                       f"Follow BuildWithAbdallah for the next World Cup prediction — agree with the model?"),
        "match-tension": (f"{leader} fans will like the verdict, {under} fans will like the warning. "
                          f"Follow BuildWithAbdallah for the next World Cup prediction."),
        "result-curiosity": (f"The model picked {leader}, but it was close. "
                             f"Follow BuildWithAbdallah for the next World Cup prediction."),
    }[vid]

    meta = {
        "match": f"{h} vs {a}",
        "variant": vid,
        "hook_variant": cfg["hook_variant"],
        "hook": hook,
        "subheadline": sub,
        "factor_label": cfg["factor_label"].format(leader=leader, underdog=under),
        "top_chip": TOP_CHIP,
        "credibility_chip": f"AI record {data.get('ledger', '')}".rstrip(),
        "short_title": short_title,
        "youtube_title": youtube_title,
        "youtube_description": youtube_description,
        "pinned_comment": pinned_comment,
        "hashtags": _hashtags(data),
        "cta_text": CTA_TEXT,
        "hook_variants": generate_hook_variants(data),
    }
    assert_no_betting(hook, sub, short_title, youtube_title, youtube_description,
                      pinned_comment, *meta["hashtags"])
    return meta
