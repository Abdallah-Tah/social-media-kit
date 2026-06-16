#!/usr/bin/env python3
"""Full-screen World Cup prediction Short (clean sports-analytics product).

The ENTIRE 1080x1920 canvas IS the prediction card (Mexico-vs-South-Africa
style) — NOT a small card inside a poster. Renders 5 animated full-screen
scenes via Remotion (Prediction composition): match setup -> model read ->
probability bars -> key factors -> final call/CTA, with an ElevenLabs voice.

  /usr/bin/python3 scripts/prediction_short.py            # Iran vs NZ demo + Telegram
  /usr/bin/python3 scripts/prediction_short.py --no-telegram
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402

REMOTION = KIT / "remotion"
PUBLIC = REMOTION / "public"
OUT_DIR = KIT / "content" / "assets" / "shorts" / "prediction"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"

# ── the match (example: Iran vs New Zealand) ─────────────────────────────────
MATCH = {
    "home": "Iran", "away": "New Zealand", "homeCode": "ir", "awayCode": "nz",
    "competition": "World Cup 2026",
    "hook": "Our model sees one clear edge.",
    "lean": "Iran 1 – 0 New Zealand",
    "confidence": "Slight Iran edge",
    "reasons": ["Defensive structure", "Transition risk", "First goal matters"],
    "probs": {"homeP": 46, "drawP": 30, "awayP": 24},
    "factors": [
        "Group stage pressure",
        "First goal changes the game",
        "Iran rate higher in our model",
        "New Zealand threaten in transition",
    ],
    "finalCall": "Iran 1 – 0",
    "durations": [4, 6, 6, 6, 5],
}

VOICEOVER = (
    "Match prediction. {home} versus {away} at the World Cup. Our model sees one clear edge. "
    "The model leans {home}, one nil — a slight edge in a close matchup. "
    "The reasons: defensive structure, transition risk, and the first goal really matters here. "
    "On the numbers, {home} holds the higher win probability, with a genuine draw chance, "
    "and an upset path for {away}. "
    "The key factors: group stage pressure, the first goal changing the game, {home} rating higher "
    "in our model, and {away}'s threat in transition. "
    "Final model call: {home} one nil. An independent model prediction. "
    "Comment your score, and follow for daily World Cup model calls."
)


def fetch_flag(code: str, dest: Path) -> bool:
    url = f"https://flagcdn.com/w640/{code.lower()}.png"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            dest.write_bytes(r.read())
        return dest.stat().st_size > 0
    except Exception as exc:  # noqa: BLE001
        print(f"[prediction] flag {code} download failed: {exc}")
        return False


def voiceover(text: str, out: Path) -> Path | None:
    import reel_generator  # type: ignore
    rendered = reel_generator.tts(text, str(out))
    return Path(rendered) if rendered and Path(rendered).exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-telegram", action="store_true")
    args = ap.parse_args()
    load_env()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)

    # flags -> remotion/public (staticFile)
    fetch_flag(MATCH["homeCode"], PUBLIC / "flag_home.png")
    fetch_flag(MATCH["awayCode"], PUBLIC / "flag_away.png")

    # props for the Prediction composition
    props = {
        "home": MATCH["home"], "away": MATCH["away"], "competition": MATCH["competition"],
        "hook": MATCH["hook"], "lean": MATCH["lean"], "confidence": MATCH["confidence"],
        "reasons": MATCH["reasons"], "probs": MATCH["probs"], "factors": MATCH["factors"],
        "finalCall": MATCH["finalCall"], "durations": MATCH["durations"],
        "homeFlag": "flag_home.png", "awayFlag": "flag_away.png",
    }
    props_path = OUT_DIR / "prediction_props.json"
    props_path.write_text(json.dumps(props, indent=2))

    # ElevenLabs voiceover
    vo_text = VOICEOVER.format(home=MATCH["home"], away=MATCH["away"])
    vo = voiceover(vo_text, OUT_DIR / "voiceover.mp3")
    print(f"[prediction] voiceover: {'ElevenLabs ok' if vo else 'none'}")

    out = OUT_DIR / "prediction_short.mp4"
    cmd = [NODE, str(REMOTION / "render.mjs"), "--id", "Prediction",
           "--props", str(props_path), "--out", str(out)]
    if vo:
        cmd += ["--audio", str(vo)]
    res = subprocess.run(cmd, cwd=str(REMOTION))
    if res.returncode != 0:
        raise SystemExit(f"remotion render failed (rc={res.returncode})")
    print(f"✅ {out} ({out.stat().st_size // 1024} KB)")

    if not args.no_telegram:
        tok_file = os.path.expanduser("~/.telegram-bot-token")
        if os.path.exists(tok_file):
            t = open(tok_file).read().strip()
            os.environ["TELEGRAM_BOT_TOKEN"] = t
            os.environ["TELEGRAM_TOKEN"] = t
        os.environ.setdefault("TELEGRAM_CHAT_ID", "-1003948211258")
        os.environ.setdefault("TELEGRAM_MESSAGE_THREAD_ID", "14119")
        import telegram_poster as TG
        cap = (f"🎬 PREVIEW — {MATCH['home']} vs {MATCH['away']} prediction Short.\n"
               "Full-screen analytics card (5 animated scenes) + ElevenLabs voice. NOT uploaded.")
        TG.post_video(str(out), caption=cap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
