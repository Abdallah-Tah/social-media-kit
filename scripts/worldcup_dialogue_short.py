"""Two-voice dialogue World Cup Shorts — the engagement upgrade.

Builds a vertical 1080x1920 video from:
  * a host/analyst DIALOGUE (two ElevenLabs voices, word-level timestamps)
  * word-by-word karaoke captions burned in (~70% of Shorts watched muted)
  * animated branded scenes (CSS keyframes scrubbed frame-by-frame via
    record_frames.mjs — deterministic, smooth even on the Pi)

Content safety identical to worldcup_short.py: 100% original graphics,
no footage, no betting language. Output is review-only by default.

Fallback chain per voice segment: ElevenLabs with-timestamps →
ElevenLabs plain (estimated word timing) → edge-tts (estimated timing).
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
TEMPLATES_DIR = ROOT / "templates" / "shorts"
SHORTS_DIR = ROOT / "content" / "assets" / "shorts"

sys.path.insert(0, str(SCRIPTS_DIR))
from worldcup_short import _load_secrets_env, WATERMARK  # noqa: E402

FPS = 20
ANIM_SECONDS = 4.2          # animated head of each scene; tail holds + zooms
CAPTION_WORDS_PER_LINE = 3

# /usr/bin/ffmpeg has libass (needed for the `ass` caption filter);
# the linuxbrew ffmpeg that shadows it on PATH does not.
FFMPEG = os.environ.get("FFMPEG_BIN") or (
    "/usr/bin/ffmpeg" if Path("/usr/bin/ffmpeg").exists() else "ffmpeg")

# Two distinct, natural ElevenLabs voices (overridable via env).
VOICES = {
    "host":    os.environ.get("ELEVENLABS_VOICE_HOST", "c6SfcYrb2t09NHXiT80T"),   # Jarnathan — Confident & Versatile
    "analyst": os.environ.get("ELEVENLABS_VOICE_ANALYST", "21m00Tcm4TlvDq8ikWAM"),  # Rachel
}
EDGE_VOICES = {"host": "en-US-AndrewNeural", "analyst": "en-US-AriaNeural"}
MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# ASS colors are &HBBGGRR. Host = white, Analyst = brand light blue.
ASS_STYLES = {
    "host":    "Style: HostCap,Inter,64,&H00FFFFFF,&H00788CA0,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,4,4,2,2,90,90,620,1",
    "analyst": "Style: AnalystCap,Inter,64,&H00FFA77A,&H00788CA0,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,4,4,2,2,90,90,620,1",
}
ASS_STYLE_NAME = {"host": "HostCap", "analyst": "AnalystCap"}


def tts_segment(speaker: str, text: str, out_path: Path) -> tuple[Path, list[tuple[str, float, float]] | None]:
    """TTS one dialogue line. Returns (mp3_path, word_timings or None).

    word_timings: [(word, start_s, end_s)] relative to this segment.
    """
    _load_secrets_env()
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = VOICES[speaker]

    if api_key:
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={"text": text, "model_id": MODEL_ID,
                      "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.4}},
                timeout=180,
            )
            if r.status_code == 200:
                payload = r.json()
                out_path.write_bytes(base64.b64decode(payload["audio_base64"]))
                return out_path, _words_from_alignment(payload.get("alignment") or {})
            print(f"⚠️  with-timestamps HTTP {r.status_code}: {r.text[:150]}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"⚠️  with-timestamps failed: {e}", file=sys.stderr)

        # Plain ElevenLabs (no timing info)
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={"text": text, "model_id": MODEL_ID,
                      "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.4}},
                timeout=180,
            )
            if r.status_code == 200:
                out_path.write_bytes(r.content)
                return out_path, None
            print(f"⚠️  ElevenLabs HTTP {r.status_code} — edge-tts fallback", file=sys.stderr)
        except requests.RequestException as e:
            print(f"⚠️  ElevenLabs failed: {e} — edge-tts fallback", file=sys.stderr)

    r = subprocess.run(
        ["edge-tts", "--voice", EDGE_VOICES[speaker], "--text", text,
         "--write-media", str(out_path)],
        capture_output=True, text=True, timeout=180,
    )
    if r.returncode != 0:
        raise RuntimeError(f"All TTS engines failed for segment: {r.stderr[-200:]}")
    return out_path, None


def _words_from_alignment(alignment: dict) -> list[tuple[str, float, float]] | None:
    chars = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not chars or not starts or not ends:
        return None
    words, word, w_start, w_end = [], "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if word:
                words.append((word, w_start, w_end))
                word, w_start = "", None
            continue
        if w_start is None:
            w_start = s
        word += ch
        w_end = e
    if word:
        words.append((word, w_start, w_end))
    return words or None


def _estimate_words(text: str, duration: float) -> list[tuple[str, float, float]]:
    """No alignment available — spread words proportionally to their length."""
    words = text.split()
    total_chars = sum(len(w) + 1 for w in words)
    t, out = 0.0, []
    for w in words:
        d = duration * (len(w) + 1) / total_chars
        out.append((w, t, t + d))
        t += d
    return out


def _media_duration(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    return float(json.loads(probe.stdout)["format"]["duration"])


def _ass_time(t: float) -> str:
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(caption_words: list[tuple[str, str, float, float]], out_path: Path) -> Path:
    """Karaoke captions: groups of words, the active word fills with the
    speaker color. caption_words: [(speaker, word, abs_start, abs_end)]."""
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "WrapStyle: 2\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{ASS_STYLES['host']}\n{ASS_STYLES['analyst']}\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    i = 0
    while i < len(caption_words):
        speaker = caption_words[i][0]
        group = []
        while (i < len(caption_words) and caption_words[i][0] == speaker
               and len(group) < CAPTION_WORDS_PER_LINE):
            group.append(caption_words[i])
            i += 1
        start, end = group[0][2], group[-1][3]
        parts = []
        for _, word, ws, we in group:
            k_cs = max(1, int(round((we - ws) * 100)))
            parts.append(f"{{\\k{k_cs}}}{word}")
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
            f"{ASS_STYLE_NAME[speaker]},,0,0,0,,{' '.join(parts)}"
        )
    out_path.write_text(header + "\n".join(events) + "\n")
    return out_path


def render_animated_scene(spec: dict, index: int, duration: float, work: Path) -> Path:
    """Animated head (scrubbed CSS keyframes) + frozen zooming tail."""
    html_src = (TEMPLATES_DIR / "animated_panel.html").read_text()
    for key in ("title", "caption", "rows", "stat", "progress"):
        html_src = html_src.replace("{{" + key + "}}", spec.get(key, ""))
    html_src = html_src.replace("{{watermark}}", WATERMARK)

    html_path = work / f"scene_{index}.html"
    html_path.write_text(html_src)
    frames_dir = work / f"frames_{index}"
    anim = min(ANIM_SECONDS, duration)
    r = subprocess.run(
        ["node", str(SCRIPTS_DIR / "record_frames.mjs"), str(html_path),
         str(frames_dir), f"{anim:.2f}", str(FPS), "1080", "1920"],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"frame render failed: {r.stderr[-300:]}")

    clip = work / f"scene_{index}.mp4"
    tail = duration - anim
    if tail > 0.05:
        # Hold the final frame with a slow ken-burns zoom for the remainder.
        # zoompan MUST use d=1 with a looped still — a large d multiplies
        # every input frame and explodes the frame count.
        last_frame = sorted(frames_dir.glob("f_*.png"))[-1]
        kb = (f"zoompan=z='min(zoom+0.0005,1.08)':d=1:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS}")
        fc = (f"[0:v]fps={FPS},settb=AVTB[a];"
              f"[1:v]{kb},settb=AVTB[b];[a][b]concat=n=2:v=1[v]")
        cmd = [FFMPEG, "-y",
               "-framerate", str(FPS), "-i", str(frames_dir / "f_%05d.png"),
               "-framerate", str(FPS), "-loop", "1", "-t", f"{tail:.2f}", "-i", str(last_frame),
               "-filter_complex", fc, "-map", "[v]",
               "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)]
    else:
        cmd = [FFMPEG, "-y", "-framerate", str(FPS),
               "-i", str(frames_dir / "f_%05d.png"),
               "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"scene encode failed: {r.stderr[-300:]}")
    return clip


def _mix_audio(dialogue_audio: Path, sfx_events: list[tuple[float, str]], work: Path) -> Path:
    """Mix the dialogue with SFX (ding/buzzer, synthesized — copyright-free)
    and, when ``content/assets/music/shorts_bg.mp3`` exists, a ducked
    background music bed. Returns the final audio path."""
    music = ROOT / "content" / "assets" / "music" / "shorts_bg.mp3"
    if not sfx_events and not music.exists():
        return dialogue_audio

    # Synthesize the two SFX once per build (pure tones, nothing licensed).
    sfx_files = {}
    if sfx_events:
        ding = work / "sfx_ding.wav"
        subprocess.run([FFMPEG, "-y", "-f", "lavfi",
                        "-i", "sine=frequency=1320:duration=0.35",
                        "-af", "afade=t=out:st=0.08:d=0.27,volume=0.5", str(ding)],
                       capture_output=True, timeout=30)
        buzzer = work / "sfx_buzzer.wav"
        subprocess.run([FFMPEG, "-y", "-f", "lavfi",
                        "-i", "sine=frequency=140:duration=0.45",
                        "-af", "tremolo=f=30:d=0.9,afade=t=out:st=0.25:d=0.2,volume=0.6",
                        str(buzzer)],
                       capture_output=True, timeout=30)
        sfx_files = {"ding": ding, "buzzer": buzzer}

    cmd = [FFMPEG, "-y", "-i", str(dialogue_audio)]
    filters, mix_labels, idx = [], ["[0:a]"], 1
    for t, kind in sfx_events:
        if kind not in sfx_files:
            continue
        cmd += ["-i", str(sfx_files[kind])]
        ms = int(t * 1000)
        filters.append(f"[{idx}:a]adelay={ms}|{ms}[s{idx}]")
        mix_labels.append(f"[s{idx}]")
        idx += 1
    if music.exists():
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        filters.append(f"[{idx}:a]volume=0.10[mus]")
        mix_labels.append("[mus]")
        idx += 1
    filters.append(
        "".join(mix_labels) + f"amix=inputs={len(mix_labels)}:normalize=0:duration=first[aout]"
    )
    mixed = work / "audio_mixed.m4a"
    cmd += ["-filter_complex", ";".join(filters), "-map", "[aout]",
            "-c:a", "aac", "-b:a", "160k", str(mixed)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"⚠️  SFX mix failed ({r.stderr[-200:]}) — using plain dialogue", file=sys.stderr)
        return dialogue_audio
    print(f"🔔 mixed {len(sfx_events)} SFX" + (" + music bed" if music.exists() else ""))
    return mixed


def build_dialogue_short(slug: str, dialogue: list[tuple[str, str]],
                         scenes: list[dict], title: str) -> Path:
    """dialogue: [(speaker, text)]. scenes: [{segments: (i, j), title, ...}]."""
    out_dir = SHORTS_DIR / f"worldcup-{slug}"
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    # ── 1. Voice all segments, collect absolute word timings ─────────
    seg_paths, seg_durs, caption_words = [], [], []
    offset = 0.0
    for i, (speaker, text) in enumerate(dialogue):
        # Cache key includes the text hash — edited lines re-voice,
        # unchanged ones reuse the existing audio (saves TTS quota).
        import hashlib
        h = hashlib.sha1(f"{speaker}:{text}".encode()).hexdigest()[:10]
        mp3 = work / f"seg_{i:02d}_{h}.mp3"
        words_cache = work / f"seg_{i:02d}_{h}.words.json"
        cached = mp3.exists() and words_cache.exists()
        if cached:
            # Reuse voiced segments on re-runs — don't burn TTS quota.
            print(f"🎙️  seg {i} [{speaker}]: cached")
            words = [tuple(w) for w in json.loads(words_cache.read_text())] or None
        else:
            print(f"🎙️  seg {i} [{speaker}]: {text[:46]}…")
            mp3, words = tts_segment(speaker, text, mp3)
        dur = _media_duration(mp3)
        if words is None:
            words = _estimate_words(text, dur)
        if not cached:
            words_cache.write_text(json.dumps(words))
        caption_words += [(speaker, w, offset + s, offset + e) for w, s, e in words]
        seg_paths.append(mp3)
        seg_durs.append(dur)
        offset += dur

    concat_list = work / "audio.txt"
    concat_list.write_text("".join(f"file '{p}'\n" for p in seg_paths))
    audio = work / "dialogue.m4a"
    r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                        "-c:a", "aac", "-b:a", "160k", str(audio)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"audio concat failed: {r.stderr[-300:]}")
    total = _media_duration(audio)
    print(f"🔊 dialogue: {total:.1f}s, {len(dialogue)} lines")

    # ── 2. Captions ───────────────────────────────────────────────────
    ass_path = build_ass(caption_words, work / "captions.ass")

    # ── 3. Scenes (durations follow the dialogue segments they cover) ─
    scene_durs = []
    for idx, spec in enumerate(scenes, 1):
        a, b = spec["segments"]
        dur = sum(seg_durs[a:b + 1])
        if idx == len(scenes):  # absorb rounding into the last scene
            covered = sum(sum(seg_durs[s["segments"][0]:s["segments"][1] + 1])
                          for s in scenes[:-1])
            dur = max(dur, total - covered)
        scene_durs.append(dur)

    # SFX events: scene specs may carry sfx=[(t_rel_seconds, "ding"|"buzzer")]
    # — a ding for RIGHT reveals, a buzzer for WRONG ones.
    sfx_events, t0 = [], 0.0
    for spec, dur in zip(scenes, scene_durs):
        for t_rel, kind in spec.get("sfx", []):
            sfx_events.append((t0 + t_rel, kind))
        t0 += dur
    audio = _mix_audio(audio, sfx_events, work)

    clips = []
    for idx, (spec, dur) in enumerate(zip(scenes, scene_durs), 1):
        spec.setdefault("progress", f"{idx}/{len(scenes)}")
        print(f"🎬 scene {idx}: {dur:.1f}s — {spec.get('title','')[:40]}")
        clips.append(render_animated_scene(spec, idx, dur, work))

    scenes_list = work / "scenes.txt"
    scenes_list.write_text("".join(f"file '{c}'\n" for c in clips))

    # ── 4. Concat (hard cuts — keeps caption/audio sync exact) + burn ─
    out_video = out_dir / f"worldcup-{slug}.mp4"
    r = subprocess.run(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(scenes_list),
         "-i", str(audio),
         "-vf", f"ass={ass_path}",
         "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-shortest", str(out_video)],
        capture_output=True, text=True, timeout=900, cwd=str(work),
    )
    if r.returncode != 0:
        raise RuntimeError(f"final assembly failed: {r.stderr[-400:]}")

    (out_dir / "metadata.json").write_text(json.dumps({
        "slug": f"worldcup-{slug}", "title": title,
        "duration_seconds": round(_media_duration(out_video), 1),
        "format": "dialogue+karaoke-captions+animated", "vertical": "1080x1920",
        "copyright_safe": True,
    }, indent=2))
    print(f"\n✅ {out_video}")
    return out_video
