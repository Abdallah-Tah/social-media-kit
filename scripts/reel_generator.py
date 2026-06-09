#!/usr/bin/env python3
"""Reel generator — build a vertical 9:16 voiceover+motion reel from an article.

Pipeline: OpenAI TTS narration -> Pillow caption cards -> ffmpeg assembly
(blurred-fill cover background + slow zoom + persistent title + timed captions
+ voiceover [+ optional background music]) -> 1080x1920 H.264 mp4.

Standalone:
  python3 scripts/reel_generator.py --cover cover.png --title "..." \
      --script "spoken narration..." --captions "Line 1|Line 2|Line 3" --out reel.mp4
"""
import os
import sys
import json
import math
import subprocess
import tempfile
import argparse
import requests

W, H = 1080, 1920
FPS = 30
TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1-hd")
TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "onyx")


def _font(size, bold=True):
    from PIL import ImageFont
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def tts(text, out_path, voice=None):
    """OpenAI TTS -> mp3. Returns out_path or None."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        try:
            r = requests.post(
                f"{os.environ.get('OPENAI_BASE_URL','https://api.openai.com/v1')}/audio/speech",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": TTS_MODEL, "voice": voice or TTS_VOICE,
                      "input": text, "response_format": "mp3"},
                timeout=120,
            )
            if r.ok:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return out_path
            print(f"❌ TTS error ({r.status_code}): {r.text[:200]}")
        except requests.RequestException as e:
            print(f"❌ TTS request failed: {e}")
    else:
        print("❌ OPENAI_API_KEY not set — trying edge-tts fallback")

    edge_voice = os.environ.get("EDGE_TTS_VOICE", "en-US-GuyNeural")
    try:
        res = subprocess.run(
            [
                "edge-tts",
                "--voice", edge_voice,
                "--text", text,
                "--write-media", out_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            print(f"✅ Voiceover generated via edge-tts ({edge_voice})")
            return out_path
        print(f"❌ edge-tts failed: {(res.stderr or res.stdout)[-300:]}")
    except (OSError, subprocess.SubprocessError) as e:
        print(f"❌ edge-tts request failed: {e}")
    return None


def _duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _text_card(text, out_path, *, size=64, pad=36, max_w=960,
               fg=(255, 255, 255, 255), box=(10, 22, 40, 200), accent=None):
    """Render wrapped text on a rounded translucent card (transparent PNG)."""
    from PIL import Image, ImageDraw
    font = _font(size)
    tmp = Image.new("RGBA", (10, 10)); d = ImageDraw.Draw(tmp)
    lines = _wrap(d, text, font, max_w)
    lh = int(size * 1.3)
    tw = max((d.textlength(ln, font=font) for ln in lines), default=10)
    cw, ch = int(tw + pad * 2), int(lh * len(lines) + pad * 2)
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0)); dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([0, 0, cw, ch], radius=28, fill=box)
    if accent:
        dr.rounded_rectangle([0, 0, 12, ch], radius=6, fill=accent)
    y = pad
    for ln in lines:
        lw = dr.textlength(ln, font=font)
        x = (cw - lw) / 2
        dr.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 160))  # shadow
        dr.text((x, y), ln, font=font, fill=fg)
        y += lh
    img.save(out_path)
    return cw, ch


def make_reel(title, script, captions, cover, out_path, voice=None, music=None):
    """Assemble the reel. captions: list[str] shown timed across the narration."""
    if not os.path.exists(cover):
        print(f"❌ cover not found: {cover}")
        return None
    work = tempfile.mkdtemp(prefix="reel_")
    # 1) Voiceover
    voice_mp3 = os.path.join(work, "vo.mp3")
    have_vo = tts(script, voice_mp3, voice=voice) is not None
    if not have_vo:
        print("❌ voiceover unavailable — refusing to build a silent reel")
        return None
    dur = max(_duration(voice_mp3) + 0.8, 6.0) if have_vo else 18.0
    dur = min(dur, 90.0)

    # 2) Cards (Pillow)
    title_png = os.path.join(work, "title.png")
    _text_card(title, title_png, size=58, max_w=920, box=(37, 99, 235, 230))  # brand blue
    cap_pngs = []
    for i, c in enumerate(captions or []):
        p = os.path.join(work, f"cap{i}.png")
        _text_card(c, p, size=60, max_w=940, accent=(37, 99, 235, 255))
        cap_pngs.append(p)

    # 3) ffmpeg filtergraph
    nframes = int(dur * FPS)
    inputs = ["-loop", "1", "-t", f"{dur}", "-i", cover,
              "-loop", "1", "-t", f"{dur}", "-i", title_png]
    for p in cap_pngs:
        inputs += ["-loop", "1", "-t", f"{dur}", "-i", p]
    fc = []
    # blurred fill background + slow zoom (Ken Burns)
    fc.append(
        f"[0:v]scale=1350:2400:force_original_aspect_ratio=increase,crop=1350:2400,"
        f"boxblur=24:4,zoompan=z='min(1+0.0009*on,1.18)':d={nframes}:s={W}x{H}:fps={FPS},"
        f"setsar=1[bg]"
    )
    # sharp cover fit to width, centered
    fc.append(f"[0:v]scale={W-120}:-1:force_original_aspect_ratio=decrease[cov]")
    fc.append("[bg][cov]overlay=(W-w)/2:(H-h)/2-120[base]")
    # persistent title near top
    fc.append("[base][1:v]overlay=(W-w)/2:150[t]")
    # timed captions near bottom
    last = "t"
    seg = dur / max(len(cap_pngs), 1)
    for i in range(len(cap_pngs)):
        a, b = i * seg, (i + 1) * seg + 0.05
        lbl = f"c{i}"
        idx = 2 + i
        fc.append(
            f"[{last}][{idx}:v]overlay=(W-w)/2:1430:enable='between(t,{a:.2f},{b:.2f})'[{lbl}]"
        )
        last = lbl
    vmap = f"[{last}]"

    cmd = ["ffmpeg", "-y", *inputs]
    if have_vo:
        cmd += ["-i", voice_mp3]
    if music and os.path.exists(music):
        cmd += ["-i", music]

    audio_inputs = []
    base_audio_idx = 1 + 1 + len(cap_pngs)  # cover + title + captions
    if have_vo:
        audio_inputs.append(base_audio_idx)
    if music and os.path.exists(music):
        midx = base_audio_idx + (1 if have_vo else 0)
        # duck music under the voice
        fc.append(f"[{midx}:a]volume=0.18,afade=t=out:st={dur-1.5}:d=1.5[mus]")
        if have_vo:
            fc.append(f"[{base_audio_idx}:a][mus]amix=inputs=2:duration=first:dropout_transition=0[aout]")
            amap = "[aout]"
        else:
            amap = "[mus]"
    else:
        amap = f"{base_audio_idx}:a" if have_vo else None  # raw input stream (no brackets)

    cmd += ["-filter_complex", ";".join(fc), "-map", vmap]
    if amap:
        cmd += ["-map", amap, "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-movflags", "+faststart", "-t", f"{dur}", out_path]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("❌ ffmpeg failed:\n" + res.stderr[-1200:])
        return None
    print(f"✅ Reel created: {out_path} ({dur:.1f}s, {os.path.getsize(out_path)//1024}KB)")
    return {"path": out_path, "duration": dur, "voiceover": have_vo}


def main():
    ap = argparse.ArgumentParser(description="Generate a 9:16 voiceover reel")
    ap.add_argument("--cover", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--script", required=True, help="Spoken narration")
    ap.add_argument("--captions", default="", help="On-screen lines, '|'-separated")
    ap.add_argument("--out", default="content/assets/reel.mp4")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--music", default=None)
    args = ap.parse_args()
    try:
        sys.path.insert(0, os.path.expanduser("~/social-media-kit"))
        from agent.config import load_env; load_env()
    except Exception:
        pass
    caps = [c.strip() for c in args.captions.split("|") if c.strip()]
    r = make_reel(args.title, args.script, caps, args.cover, args.out,
                  voice=args.voice, music=args.music)
    sys.exit(0 if r else 1)


if __name__ == "__main__":
    main()
