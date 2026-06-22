#!/usr/bin/env python3
"""'explainer' pillar — short-form football RULES explainers for first-time
World Cup watchers. Mirrors the daily/prediction shorts: render-from-props +
single Jarnathan VO + (parametrized) crosspost.

EDITORIAL HARD RULE: the factual rule text lives in content/explainers/topics.json
(`rule_text`, hand-vetted from IFAB). The LLM only writes FRAMING (hook, beats,
CTA) by paraphrasing that text — it never originates or alters rule facts. If
`rule_text` is empty, this refuses to run. Publish target is parametrized in
config/explainer.yaml and gated by `channel_ready` (no accidental main-channel posts).

  /usr/bin/python3 scripts/explainer_short.py --topic offside            # draft -> review -> render (local)
  /usr/bin/python3 scripts/explainer_short.py                            # next unposted topic
  /usr/bin/python3 scripts/explainer_short.py --topic offside --approve  # render after reviewing the draft
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402

REMOTION = KIT / "remotion"
TOPICS = KIT / "content" / "explainers" / "topics.json"
POSTED = KIT / "content" / "explainers" / "explainer_posts.json"
OUT_DIR = KIT / "content" / "assets" / "shorts" / "explainers"
CONFIG = KIT / "config" / "explainer.yaml"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"


def _load_topics() -> list[dict]:
    return json.loads(TOPICS.read_text()).get("topics", [])


def _posted() -> set:
    try:
        return set(json.loads(POSTED.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _mark(tid: str) -> None:
    seen = _posted(); seen.add(tid)
    POSTED.write_text(json.dumps(sorted(seen)))


def _config() -> dict:
    try:
        import yaml
        return yaml.safe_load(CONFIG.read_text()) or {}
    except Exception:
        return {}


def select_topic(tid: str | None) -> dict | None:
    topics = _load_topics()
    if tid:
        return next((t for t in topics if t["id"] == tid), None)
    posted = _posted()
    return next((t for t in topics if t["id"] not in posted), None)


# ── LLM framing (paraphrase ONLY — never originate facts) ────────────────────
# The LLM writes ONLY the low-stakes hook + CTA. Rule-stating captions come
# verbatim from the vetted bank (topic["beats"]) — never model-generated.
SYSTEM = (
    "You write only a HOOK and a CTA for a football-rules explainer aimed at "
    "first-time World Cup viewers (US/Canada newcomers). You do NOT write any "
    "rule facts. No betting language, no hype. Return STRICT JSON: "
    "{\"hook\": str, \"cta\": str}. Hook <= 70 chars, CTA <= 60 chars."
)
HYPE = ("game-changing", "revolutionary", "supercharge", "shocking", "guaranteed",
        "must bet", "lock", "easy money", "insane", "you won't believe")


def require_vetted(topic: dict) -> None:
    """Refuse to render unless rule_text is present AND vetted==true."""
    if not (topic.get("rule_text") or "").strip():
        raise SystemExit(
            f"[explainer] rule_text for '{topic['id']}' is EMPTY — fill it from a "
            f"vetted source (IFAB) in {TOPICS}. The model never writes rule facts.")
    if topic.get("vetted") is not True:
        raise SystemExit(
            f"[explainer] topic '{topic['id']}' is NOT vetted (vetted != true). "
            f"Abdallah must final-check its rule_text + beats against IFAB and set "
            f"vetted: true in {TOPICS} before it can render.")


def draft_framing(topic: dict) -> dict:
    """Hook + CTA only. Falls back to a deterministic template (no LLM needed),
    so the daily pipeline never fails on a missing key / API error."""
    template = {"hook": f"{topic['title']} - in 30 seconds.",
                "cta": "Follow for World Cup explainers"}
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return template
    try:
        import requests
        prompt = (f"TOPIC: {topic['title']}\nContext (do NOT restate as fact): {topic['rule_text'][:300]}\n"
                  "Write the hook + CTA now.")
        r = requests.post(
            os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": os.environ.get("SHORTS_LLM_MODEL", "gpt-4o-mini"),
                  "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                  "temperature": 0.5, "max_tokens": 160, "response_format": {"type": "json_object"}},
            timeout=60)
        r.raise_for_status()
        out = json.loads(r.json()["choices"][0]["message"]["content"])
        return {"hook": (out.get("hook") or template["hook"])[:80],
                "cta": (out.get("cta") or template["cta"])[:70]}
    except Exception as exc:  # noqa: BLE001
        print(f"[explainer] hook/cta LLM failed ({exc}); using template", file=sys.stderr)
        return template


def gate(draft: dict, topic: dict) -> list[str]:
    """Editorial gate. Hype check on the LLM hook/CTA only; bank captions are
    pre-vetted so they are not length/word gated."""
    issues = []
    blob = (draft.get("hook", "") + " " + draft.get("cta", "")).lower()
    issues += [f"hype phrase in hook/cta: {h}" for h in HYPE if h in blob]
    beats = topic.get("beats") or []
    if not (3 <= len(beats) <= 6):
        issues.append(f"bank needs 3-6 beats, got {len(beats)}")
    return issues


def build_props(topic: dict, draft: dict) -> dict:
    # captions come VERBATIM from the vetted bank; each beat uses the topic's
    # primitive (optionally overriding params per beat).
    beats = []
    for b in topic.get("beats", []):
        vis = dict(topic["visual"])
        if b.get("params"):
            vis = {**vis, "params": {**vis.get("params", {}), **b["params"]}}
        beats.append({"caption": b.get("caption", ""), "visual": vis,
                      "stress_words": b.get("stress_words", [])})
    return {"title": topic["title"], "beats": beats,
            "cta": draft.get("cta", "Follow for World Cup explainers"),
            "brand": "light_brand"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--approve", action="store_true", help="render after reviewing the draft")
    ap.add_argument("--publish", action="store_true", help="publish (only if channel_ready in config)")
    args = ap.parse_args()
    load_env()

    topic = select_topic(args.topic)
    if not topic:
        print("[explainer] no topic to do (all posted or unknown id)"); return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    require_vetted(topic)                               # refuse if empty/unvetted
    draft = draft_framing(topic)                        # hook + cta only
    issues = gate(draft, topic)
    print("=== DRAFT (hook/CTA only; captions are vetted-bank) ===")
    print(json.dumps({"hook": draft["hook"], "cta": draft["cta"],
                      "captions": [b["caption"] for b in topic.get("beats", [])]}, indent=2))
    if issues:
        print("[explainer] GATE ISSUES:\n - " + "\n - ".join(issues))
        print("[explainer] fix the topic/framing; not rendering."); return 1
    if not args.approve:
        print("[explainer] review above, then re-run with --approve to render."); return 0

    props = build_props(topic, draft)
    props_path = OUT_DIR / f"{topic['id']}_props.json"
    props_path.write_text(json.dumps(props, indent=2))

    # single Jarnathan VO from hook + captions + cta
    import reel_generator
    vo_text = " ".join([draft.get("hook", "")] + [b["caption"] for b in props["beats"]] + [props["cta"]])
    vo = OUT_DIR / f"{topic['id']}_vo.mp3"
    rendered = reel_generator.tts(vo_text, str(vo))
    has_vo = bool(rendered and Path(rendered).exists())
    # durations: one per beat + CTA card
    props["durations"] = [5] * len(props["beats"]) + [4]
    props["hasAudio"] = has_vo
    props["audioFile"] = f"{topic['id']}_vo.mp3"
    props_path.write_text(json.dumps(props, indent=2))

    out = OUT_DIR / f"{topic['id']}.mp4"
    cmd = [NODE, str(REMOTION / "render.mjs"), "--id", "Explainer",
           "--props", str(props_path), "--out", str(out)]
    if has_vo:
        cmd += ["--audio", str(vo)]
    if subprocess.run(cmd, cwd=str(REMOTION)).returncode != 0:
        print("[explainer] render failed"); return 1
    print(f"✅ [explainer] {out}")

    cfg = _config()
    pub = cfg.get("publish", {}) or {}
    if not args.publish:
        print("[explainer] rendered (no --publish). Local mp4 only."); return 0
    if cfg.get("channel_ready") is not True:
        print("[explainer] channel_ready is false — not publishing. Set it in config/explainer.yaml."); return 0

    import re
    title = f"{topic['title']} | Soccer Rules Explained"[:100]
    desc = (f"{draft.get('hook','')}\n\n{topic['title']} - explained for first-time fans, "
            f"one quick animated Short. Independent. Not affiliated with FIFA.\n\n"
            f"{draft.get('cta','')}\n\n#Soccer #Football #SoccerRules #WorldCup2026 #{topic['id']} #Shorts #Explained")
    profile = pub.get("youtube_profile", "main")
    try:
        from worldcup_thumbnail import generate_thumbnail
        thumb = generate_thumbnail(
            OUT_DIR / f"{topic['id']}_thumb.jpg",
            title=topic["title"],
            kind="SOCCER RULES",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[explainer] thumbnail failed (non-fatal): {exc}")
        thumb = None
    up = subprocess.run(
        ["/usr/bin/python3", str(KIT / "scripts" / "youtube_shorts_publisher.py"), "upload",
         "--video", str(out), "--title", title, "--description", desc,
         "--privacy", pub.get("privacy", "public"), "--profile", profile, "--category-id", "17",
         "--tags", "soccer,football,soccer rules,world cup 2026,offside,explained,shorts"]
        + (["--thumbnail", str(thumb)] if thumb else []),
        capture_output=True, text=True)
    print(up.stdout[-300:])
    if up.returncode != 0:
        print(f"[explainer] YouTube upload failed: {up.stderr[-300:]}"); return 1
    m = re.search(r"https://www\.youtube\.com/shorts/[\w-]+", up.stdout)
    yt = m.group(0) if m else ""

    if pub.get("crosspost_facebook") and yt:
        try:
            frame = OUT_DIR / f"{topic['id']}_fb.png"
            subprocess.run(["/usr/bin/ffmpeg", "-y", "-ss", "2", "-i", str(out), "-frames:v", "1", str(frame)], capture_output=True)
            from football_crosspost import crosspost
            crosspost(f"⚽ {topic['title']} — explained for new fans. {draft.get('cta','')}",
                      youtube_url=yt, image_path=str(frame) if frame.exists() else None, title=title)
        except Exception as exc:  # noqa: BLE001
            print(f"[explainer] FB crosspost failed (non-fatal): {exc}")
    # LinkedIn intentionally OFF for this pillar.

    _mark(topic["id"])
    print(f"✅ [explainer] PUBLISHED {topic['id']} -> {yt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
