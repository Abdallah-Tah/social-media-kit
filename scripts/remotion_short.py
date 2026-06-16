#!/usr/bin/env python3
"""Render an animated Build With Abdallah Short via Remotion (motion graphics).

Pipeline: generate the ElevenLabs voiceover (brand standard, conversational),
then render real animated scenes with Remotion (React/TSX, light_brand theme).
Replaces the static-PNG + ffmpeg-Ken-Burns path for higher retention.

  /usr/bin/python3 scripts/remotion_short.py --plan <short_plan.json> [--out <mp4>]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402

REMOTION = KIT / "remotion"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"


def _voiceover(plan: dict, out_dir: Path) -> Path | None:
    text = str(plan.get("voiceover") or "").strip()
    if not text:
        return None
    out = out_dir / "voiceover.mp3"
    if out.exists():
        return out
    import reel_generator  # type: ignore
    rendered = reel_generator.tts(text, str(out))
    return Path(rendered) if rendered and Path(rendered).exists() else None


def render(plan_path: Path, out: Path | None = None) -> Path:
    load_env()
    import json
    plan = json.loads(plan_path.read_text())
    out_dir = plan_path.parent
    out = out or (out_dir / f"{plan.get('source', {}).get('slug', 'short')}_remotion.mp4")
    voice = _voiceover(plan, out_dir)
    cmd = [NODE, str(REMOTION / "render.mjs"), "--plan", str(plan_path), "--out", str(out)]
    if voice:
        cmd += ["--audio", str(voice)]
    print(f"[remotion] {'with ElevenLabs voice' if voice else 'no voiceover'} -> {out}")
    res = subprocess.run(cmd, cwd=str(REMOTION))
    if res.returncode != 0:
        raise SystemExit(f"remotion render failed (rc={res.returncode})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    out = render(Path(args.plan), Path(args.out) if args.out else None)
    print(f"✅ {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
