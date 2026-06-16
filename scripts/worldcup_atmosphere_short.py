"""Matchday Short with real football atmosphere background.

Pipeline:
  1. Fetch a Pexels CC0 football atmosphere clip (vertical, commercial safe)
  2. Render animated brand card(s) as transparent-background overlays
  3. Composite card on atmosphere with ffmpeg (card scales to fill while
     atmosphere plays behind it)
  4. Mix ElevenLabs dialogue + SFX
  5. Burn karaoke captions

This replaces the static white-card-only approach: the atmosphere clip gives
the "live football feel" while 100% original graphics keep it copyright-safe.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from gen_atmosphere import fetch_atmosphere  # noqa: E402
from worldcup_dialogue_short import (  # noqa: E402
    _load_secrets_env, FFMPEG, FPS,
    tts_segment, _estimate_words, build_ass, _mix_audio,
    _media_duration,
)
import hashlib, json as _json

XFADE = 0.45  # cross-dissolve between scenes (kept local; kit dialogue uses hard cuts)

SHORTS_DIR = ROOT / "content" / "assets" / "shorts"
SCRIPTS_DIR = ROOT / "scripts"


def build_atmosphere_short(
    slug: str,
    dialogue: list[tuple[str, str]],
    scenes: list[dict],
    title: str,
    voices: dict | None = None,
    atmosphere_query: str = "football stadium night lights",
) -> Path:
    """Build a full matchday Short with atmosphere background."""
    _load_secrets_env()

    out_dir = SHORTS_DIR / f"worldcup-{slug}"
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    # ── 1. Fetch atmosphere clip ─────────────────────────────────────
    print("🏟️  Fetching atmosphere clip from Pexels…")
    atm_path = work / "atmosphere.mp4"
    if not atm_path.exists():
        fetch_atmosphere(atmosphere_query, str(atm_path), duration=18)
    else:
        print("🏟️  Atmosphere clip cached")

    # ── 2. Voice all dialogue segments (kit's module VOICES = Jarnathan) ─
    seg_paths, seg_durs, caption_words = [], [], []
    offset = 0.0
    for i, (speaker, text) in enumerate(dialogue):
        h = hashlib.sha1(f"{speaker}:{text}".encode()).hexdigest()[:10]
        mp3 = work / f"seg_{i:02d}_{h}.mp3"
        wc = work / f"seg_{i:02d}_{h}.words.json"
        if mp3.exists() and wc.exists():
            print(f"🎙️  seg {i} [{speaker}]: cached")
            words = [tuple(w) for w in _json.loads(wc.read_text())] or None
        else:
            print(f"🎙️  seg {i} [{speaker}]: {text[:46]}…")
            mp3, words = tts_segment(speaker, text, mp3)
        dur = _media_duration(mp3)
        if words is None:
            words = _estimate_words(text, dur)
        if not (mp3.exists() and wc.exists()):
            wc.write_text(_json.dumps(words))
        caption_words += [(speaker, w, offset + s, offset + e) for w, s, e in words]
        seg_paths.append(mp3); seg_durs.append(dur); offset += dur

    concat_list = work / "audio.txt"
    concat_list.write_text("".join(f"file '{p}'\n" for p in seg_paths))
    audio = work / "dialogue.m4a"
    subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                    "-c:a", "aac", "-b:a", "160k", str(audio)],
                   capture_output=True, timeout=300, check=True)
    total = _media_duration(audio)
    print(f"🔊 {total:.1f}s dialogue")

    # ── 3. Captions ───────────────────────────────────────────────────
    ass_path = build_ass(caption_words, work / "captions.ass")

    # ── 4. Scene clips (brand cards) ─────────────────────────────────
    from worldcup_dialogue_short import render_animated_scene
    n = len(scenes)
    scene_durs = []
    for idx, sc in enumerate(scenes, 1):
        a, b = sc["segments"]
        dur = sum(seg_durs[a:b + 1])
        if idx == n:
            covered = sum(sum(seg_durs[s["segments"][0]:s["segments"][1] + 1]) for s in scenes[:-1])
            dur = max(dur, total - covered)
        scene_durs.append(dur)

    sfx_events, t0 = [], 0.0
    for sc, dur in zip(scenes, scene_durs):
        for t_rel, kind in sc.get("sfx", []):
            sfx_events.append((t0 + t_rel, kind))
        t0 += dur
    audio = _mix_audio(audio, sfx_events, work)

    card_clips = []
    for idx, (sc, dur) in enumerate(zip(scenes, scene_durs), 1):
        sc.setdefault("progress", f"{idx}/{n}")
        render_len = dur + (XFADE if idx < n else 0.0)
        print(f"🎬 card {idx}: {dur:.1f}s — {sc.get('title','')[:38]}")
        card_clips.append(render_animated_scene(sc, idx, render_len, work))

    # ── 5. Cross-dissolve the card clips ─────────────────────────────
    raw_cards = work / "cards_raw.mp4"
    if n == 1:
        raw_cards = card_clips[0]
    else:
        inputs = []
        for c in card_clips: inputs += ["-i", str(c)]
        parts, prev, cum = [], "[0:v]", 0.0
        for k in range(1, n):
            cum += scene_durs[k - 1]
            out_lbl = "[vmrg]" if k == n - 1 else f"[vx{k}]"
            parts.append(f"{prev}[{k}:v]xfade=transition=fade:duration={XFADE}:offset={cum:.3f}{out_lbl}")
            prev = out_lbl
        r = subprocess.run(
            [FFMPEG, "-y", *inputs, "-filter_complex", ";".join(parts),
             "-map", prev, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw_cards)],
            capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"card xfade failed: {r.stderr[-300:]}")

    # ── 6. Composite: atmosphere full background, brand card FLOATING ─
    # The white card is scaled to 86% and centred so the live stadium frames
    # it (a premium broadcast look) — clearly visible atmosphere, fully
    # readable content. A rounded mask + shadow makes the card float.
    out_video = out_dir / f"worldcup-{slug}.mp4"
    card_dur = _media_duration(raw_cards)
    CARD_W, CARD_H = 928, 1648          # 86% of 1080x1920
    px, py = (1080 - CARD_W) // 2, (1920 - CARD_H) // 2
    r = subprocess.run(
        [FFMPEG, "-y",
         "-stream_loop", "-1", "-t", f"{card_dur:.3f}", "-i", str(atm_path),  # looped atmosphere
         "-i", str(raw_cards),             # brand cards
         "-i", str(audio),                 # dialogue + SFX
         "-filter_complex",
         # Atmosphere fills the frame; a soft dark scrim improves card contrast.
         "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
         "crop=1080:1920,setpts=PTS-STARTPTS,"
         "eq=brightness=-0.05:saturation=1.15[bg];"
         # Card scaled down and centred so the live stadium frames it.
         f"[1:v]scale={CARD_W}:{CARD_H}[card];"
         f"[bg][card]overlay={px}:{py}[pre];"
         f"[pre]ass={ass_path.name}[vout]",
         "-map", "[vout]", "-map", "2:a",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-shortest",
         str(out_video)],
        capture_output=True, text=True, timeout=900, cwd=str(work))
    if r.returncode != 0:
        raise RuntimeError(f"composite failed: {r.stderr[-400:]}")

    print(f"\n✅ {out_video}")
    return out_video
