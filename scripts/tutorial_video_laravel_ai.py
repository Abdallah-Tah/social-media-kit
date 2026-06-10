#!/usr/bin/env python3
"""Generate a tutorial-style short video: "Building AI Agents with Laravel".

Multi-scene vertical (1080x1920) tutorial built on the same Playwright + ffmpeg
pipeline as the Shorts Visual Agent. Renders each scene HTML to PNG, generates an
edge-tts voiceover, and crossfades the scenes into a single MP4.

Source: content/drafts/2026-06-05_building-ai-agents-with-laravel-no-python-required.md
Run:    /usr/bin/python3 scripts/tutorial_video_laravel_ai.py
"""

import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORTS_DIR = ROOT / "content" / "assets" / "shorts"
TEMPLATES_DIR = ROOT / "templates" / "shorts"
SCRIPTS_DIR = ROOT / "scripts"

WATERMARK = '<span class="wm-text">BWA</span>'

# Scene definitions. Variable names match the shorts templates exactly:
#   title_card.html      -> title, caption, main_idea, progress, watermark
#   code_card.html       -> title, caption, code, takeaway, progress, watermark
#   terminal_window.html -> title, caption, commands, takeaway, progress, watermark
#   cta_card.html        -> title, caption, cta, url, progress, watermark
SCENES = [
    {
        "template": "title_card.html",
        "title": "Build AI Agents in Laravel",
        "caption": "No Python required.",
        "main_idea": "The first-party Laravel AI SDK gives PHP developers a "
                     "complete agent framework — tools, memory, streaming, RAG.",
        "progress": "1/9",
        "duration_seconds": 8,
    },
    {
        "template": "title_card.html",
        "title": "Why PHP Felt Left Out",
        "caption": "Every agent tutorial pointed to Python.",
        "main_idea": "LangChain set the vocabulary — chains, tools, memory, "
                     "vector stores — and it was Python-only. PHP devs were "
                     "stuck calling microservices or raw APIs.",
        "progress": "2/9",
        "duration_seconds": 12,
    },
    {
        "template": "title_card.html",
        "title": "Meet the Laravel AI SDK",
        "caption": "One idiomatic PHP API. 14 providers.",
        "main_idea": "OpenAI, Anthropic, Gemini, Groq, Mistral, Ollama and more "
                     "— behind a single first-party package built on Laravel's "
                     "queues, filesystem and Eloquent.",
        "progress": "3/9",
        "duration_seconds": 12,
    },
    {
        "template": "code_card.html",
        "title": "Define an Agent",
        "caption": "An agent is just a PHP class",
        "code": (
            "namespace App\\Agents;\n"
            "\n"
            "use Laravel\\Ai\\Agent;\n"
            "\n"
            "class SupportAgent extends Agent\n"
            "{\n"
            "    public function instructions(): string\n"
            "    {\n"
            "        return 'You are a helpful support assistant.';\n"
            "    }\n"
            "\n"
            "    public function tools(): array\n"
            "    {\n"
            "        return [new SearchOrders];\n"
            "    }\n"
            "}"
        ),
        "takeaway": "Instructions and tools live in the class — define once, call anywhere",
        "progress": "4/9",
        "duration_seconds": 14,
    },
    {
        "template": "code_card.html",
        "title": "Tools Are PHP Classes",
        "caption": "The model decides when to call them",
        "code": (
            "use Laravel\\Ai\\Tool;\n"
            "\n"
            "class SearchOrders extends Tool\n"
            "{\n"
            "    public string $description =\n"
            "        'Look up a customer order';\n"
            "\n"
            "    public function handle(string $id): array\n"
            "    {\n"
            "        return Order::findOrFail($id)\n"
            "            ->toArray();\n"
            "    }\n"
            "}"
        ),
        "takeaway": "The SDK runs the tool and feeds the result back to the model automatically",
        "progress": "5/9",
        "duration_seconds": 13,
    },
    {
        "template": "code_card.html",
        "title": "Structured Output",
        "caption": "Typed, validated JSON back from the model",
        "code": (
            "use Laravel\\Ai\\Concerns\\\n"
            "    HasStructuredOutput;\n"
            "\n"
            "class Classifier extends Agent\n"
            "{\n"
            "    use HasStructuredOutput;\n"
            "\n"
            "    public function schema(): array\n"
            "    {\n"
            "        return [\n"
            "            'sentiment' => 'string',\n"
            "            'priority'  => 'int',\n"
            "        ];\n"
            "    }\n"
            "}"
        ),
        "takeaway": "Declare the shape — get back validated keys with the types you asked for",
        "progress": "6/9",
        "duration_seconds": 13,
    },
    {
        "template": "terminal_window.html",
        "title": "Run It",
        "caption": "Tool call + answer, end to end",
        "commands": (
            '<span class="prompt">$</span> php artisan tinker\n'
            '\n'
            '>>> SupportAgent::run(\'Track order 1042\')\n'
            '\n'
            '  → calling tool: SearchOrders(id=1042)\n'
            '  ← Order #1042 ships tomorrow\n'
            '\n'
            '  "Your order #1042 is on its way\n'
            '   and ships tomorrow!"\n'
            '\n'
            '<span class="prompt">$</span> _'
        ),
        "takeaway": "The agent picks the tool, runs it, and writes the final reply",
        "progress": "7/9",
        "duration_seconds": 13,
    },
    {
        "template": "title_card.html",
        "title": "Built In, Not Bolted On",
        "caption": "The rest comes for free",
        "main_idea": "Conversation memory, streaming to the browser, queued agents, "
                     "provider failover, pgvector RAG, and a full fake layer for "
                     "tests — plus five multi-agent patterns.",
        "progress": "8/9",
        "duration_seconds": 13,
    },
    {
        "template": "cta_card.html",
        "title": "Start Building Agents",
        "caption": "Full walkthrough on the blog",
        "cta": "Follow Build With Abdallah",
        "url": "buildwithabdallah.com",
        "progress": "9/9",
        "duration_seconds": 6,
    },
]

# Voiceover script — one paragraph per scene, in order.
VOICEOVER = """
Want to build AI agents but you're a PHP developer? You no longer need Python. The first-party Laravel AI SDK gives you a complete agent framework, right inside Laravel.

For years, every agent tutorial pointed to Python. LangChain set the vocabulary, chains, tools, memory, vector stores, and it was Python only. PHP developers were stuck building microservices or making raw API calls.

The Laravel AI SDK changes that. One idiomatic PHP API across fourteen providers, OpenAI, Anthropic, Gemini, Groq, Mistral, Ollama and more, all built on Laravel's queues, filesystem, and Eloquent.

Here's the core idea. An agent is just a PHP class. You give it instructions and a list of tools, define it once, and call it anywhere through the service container.

Tools are PHP classes too. You write a description and a handle method. The model decides when to call the tool, the SDK runs it, and feeds the result straight back to the model.

Need typed data instead of free text? Add the structured output trait and declare a schema. You get back validated keys with exactly the types you asked for.

Run it, and the agent picks the right tool, executes it, and writes the final answer, end to end.

And the rest comes built in. Conversation memory, streaming to the browser, queued agents, provider failover, vector search for RAG, a full fake layer for testing, and five multi-agent patterns.

PHP developers can finally build real AI agents without leaving Laravel. Follow Build With Abdallah for the full walkthrough.
""".strip()


def render_scene(scene: dict, index: int, out_dir: Path) -> Path:
    """Render a single scene HTML to a 1080x1920 PNG via render_card.mjs."""
    tmpl_path = TEMPLATES_DIR / scene["template"]
    html_src = tmpl_path.read_text()

    # Plain-text replacements common to all templates.
    for key in ("title", "caption", "main_idea", "takeaway", "cta", "url", "progress"):
        if key in scene:
            html_src = html_src.replace("{{" + key + "}}", scene[key])
    html_src = html_src.replace("{{watermark}}", WATERMARK)

    # Code card: HTML-escape the source, then wrap each line in a div so blank
    # lines keep their height. (PHP uses <, >, & which would break the markup.)
    if scene["template"] == "code_card.html":
        lines = scene["code"].split("\n")
        code_html = "".join(f"<div>{html.escape(line) or '&nbsp;'}</div>" for line in lines)
        html_src = html_src.replace("{{code}}", code_html)

    # Terminal: commands already contain intentional <span> markup, so wrap
    # lines without escaping. Authors must hand-escape any literal angle brackets.
    if scene["template"] == "terminal_window.html":
        lines = scene["commands"].split("\n")
        cmd_html = "".join(f"<div>{line or '&nbsp;'}</div>" for line in lines)
        html_src = html_src.replace("{{commands}}", cmd_html)

    # Strip any unfilled placeholders so they never show on screen.
    while "{{" in html_src and "}}" in html_src:
        start = html_src.index("{{")
        end = html_src.index("}}", start) + 2
        html_src = html_src[:start] + html_src[end:]

    html_path = out_dir / f"scene_{index:02d}.html"
    html_path.write_text(html_src)

    png_path = out_dir / f"scene_{index:02d}.png"
    result = subprocess.run(
        ["node", str(SCRIPTS_DIR / "render_card.mjs"), str(html_path), str(png_path), "1080", "1920"],
        capture_output=True, text=True, timeout=90,
    )
    if result.returncode != 0:
        print(f"⚠️  Scene {index} render issue: {result.stderr[-300:]}", file=sys.stderr)
    if not png_path.exists():
        raise RuntimeError(f"Scene {index} PNG not generated: {png_path}")
    return png_path


def generate_voiceover(text: str, out_path: Path) -> Path | None:
    """Generate a voiceover MP3 with edge-tts, if available."""
    import shutil
    if not shutil.which("edge-tts"):
        print("⚠️  edge-tts not found, skipping voiceover")
        return None
    cmd = ["edge-tts", "--voice", "en-US-GuyNeural", "--text", text, "--write-media", str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        print(f"⚠️  edge-tts failed: {result.stderr[-300:]}", file=sys.stderr)
        return None
    return out_path


def assemble_video(scene_paths: list[tuple[Path, float]], voice_path: Path | None, out_video: Path) -> None:
    """Crossfade the scene PNGs into a vertical MP4, muxing the voiceover."""
    has_voice = bool(voice_path and voice_path.exists())
    xfade_dur = 0.4
    scale_vf = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2")

    inputs: list[str] = []
    for png, dur in scene_paths:
        inputs += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(png)]

    # xfade chain; scale+pad applied as the final filter (can't mix -vf here).
    fc_parts: list[str] = []
    cumulative = 0.0
    prev = "[0:v]"
    for i in range(1, len(scene_paths)):
        cumulative += scene_paths[i - 1][1] - xfade_dur
        out_label = f"[v{i}]" if i < len(scene_paths) - 1 else "[voutscale]"
        fc_parts.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={xfade_dur}:offset={cumulative:.3f}{out_label}"
        )
        prev = out_label
    fc_parts.append(f"[voutscale]{scale_vf}[vout]")
    filter_complex = ";".join(fc_parts)

    cmd = ["ffmpeg", "-y"] + inputs
    if has_voice:
        cmd += ["-i", str(voice_path)]
    cmd += ["-filter_complex", filter_complex, "-map", "[vout]"]
    if has_voice:
        cmd += ["-map", f"{len(scene_paths)}:a", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_video)]

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr[-700:]}")


def main():
    slug = "building-ai-agents-with-laravel-tutorial"
    out_dir = SHORTS_DIR / slug
    scenes_dir = out_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    print(f"🎬 Rendering {len(SCENES)} scenes...")
    scene_paths = []
    for i, scene in enumerate(SCENES, 1):
        print(f"   Scene {i}/{len(SCENES)}: {scene['template']:20s} — {scene.get('title','')[:46]}")
        png = render_scene(scene, i, scenes_dir)
        scene_paths.append((png, float(scene["duration_seconds"])))

    print("\n🎙️  Generating voiceover...")
    voice_path = generate_voiceover(VOICEOVER, out_dir / "voiceover.mp3")
    print(f"   {'✅ ' + str(voice_path) if voice_path else '⚠️  visual-only (no voiceover)'}")

    total = sum(d for _, d in scene_paths)
    print(f"\n🎞️  Assembling video ({total:.0f}s of scenes)...")
    out_video = out_dir / f"{slug}.mp4"
    assemble_video(scene_paths, voice_path, out_video)

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(out_video)],
        capture_output=True, text=True, timeout=15,
    )
    duration = json.loads(probe.stdout or "{}").get("format", {}).get("duration", "?")

    print(f"\n✅ Tutorial video: {out_video}")
    print(f"   Duration: {duration}s · Scenes: {len(SCENES)} · Voiceover: {'yes' if voice_path else 'no'}")

    (out_dir / "metadata.json").write_text(json.dumps({
        "slug": slug,
        "title": "Building AI Agents with Laravel: No Python Required",
        "scenes": len(SCENES),
        "duration_seconds": duration,
        "voiceover": bool(voice_path),
    }, indent=2))
    print("\n📤 Ready for review. Send the MP4 to Abdallah before publishing.")


if __name__ == "__main__":
    main()
