"""Technical YouTube Shorts planner, validator, and renderer.

The visual shorts pipeline is deliberately practical: it turns an article into
a concrete teaching plan, renders HTML scenes with Playwright, then assembles a
vertical MP4 with ffmpeg. No AI-generated text images and no hype trailers.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import ROOT, load_env

ALLOWED_SHORT_TYPES = {
    "before_after_code",
    "terminal_workflow",
    "architecture_diagram",
    "mistake_fix",
    "tool_test_result",
    "article_summary_with_practical_takeaway",
}

HYPE_WORDS = [
    "game-changing",
    "game changer",
    "revolutionary",
    "unlock the power",
    "boost your skills",
    "supercharge",
    "cutting-edge",
    "next-generation",
]

TEMPLATES_DIR = ROOT / "templates" / "shorts"
ASSETS_DIR = ROOT / "content" / "assets"
SHORTS_DIR = ASSETS_DIR / "shorts"
SITE = "https://buildwithabdallah.com"


@dataclass
class Article:
    slug: str
    title: str
    body: str
    excerpt: str = ""
    url: str = ""


class ShortsError(RuntimeError):
    """Raised when a short cannot be planned, rendered, or published safely."""


def slugify(text: str, max_len: int = 80) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:max_len].strip("-") or "short"


def find_article(slug_or_path: str) -> Article:
    """Load an article by local Markdown path, local draft slug, or blog slug."""
    load_env()
    source = Path(slug_or_path)
    if source.exists():
        body = source.read_text(encoding="utf-8")
        title = _first_heading(body) or source.stem.replace("-", " ").title()
        return Article(slug=slugify(source.stem), title=title, body=body, url="")

    slug = slug_or_path.strip().removeprefix("/tutorials/").strip("/")
    draft = _find_local_draft(slug)
    if draft:
        body = draft.read_text(encoding="utf-8")
        title = _first_heading(body) or slug.replace("-", " ").title()
        return Article(slug=slug, title=title, body=body, url=f"{SITE}/tutorials/{slug}")

    post = _fetch_post(slug)
    if post:
        return Article(
            slug=post.get("slug") or slug,
            title=post.get("title") or slug.replace("-", " ").title(),
            body=post.get("body") or post.get("content") or "",
            excerpt=post.get("excerpt") or "",
            url=f"{SITE}/tutorials/{post.get('slug') or slug}",
        )
    raise ShortsError(f"article not found: {slug_or_path}")


def plan_short(article: Article, out_path: str | Path | None = None) -> dict[str, Any]:
    """Generate and validate a concrete short plan for an article."""
    plan = _llm_plan(article) or _fallback_plan(article)
    plan.setdefault("source", {})
    plan["source"].update({
        "slug": article.slug,
        "title": article.title,
        "url": article.url,
    })
    plan["short_type"] = _normalise_short_type(plan.get("short_type"))
    plan["scenes"] = _normalise_scenes(plan)
    plan["captions"] = _short_lines(plan.get("captions") or [], limit=8, max_chars=58)
    plan["voiceover"] = _clean_text(plan.get("voiceover") or _voiceover_from_scenes(plan), 900)
    # Ensure voiceover covers all scenes — if it's suspiciously short, rebuild it
    scene_count = len(plan.get("scenes", []))
    total_duration = sum(s.get("duration_seconds", 4) for s in plan.get("scenes", []))
    if len(plan["voiceover"]) < scene_count * 40 or len(plan["voiceover"]) < total_duration * 8:
        plan["voiceover"] = _voiceover_from_scenes(plan)
    plan["cta"] = _clean_text(plan.get("cta") or "Read the full tutorial at buildwithabdallah.com", 120)
    plan["publish_metadata"] = _normalise_metadata(plan, article)
    issues = validate_plan(plan)
    if issues:
        raise ShortsError("short rejected:\n- " + "\n- ".join(issues))
    if out_path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plan


def render_short(plan_path: str | Path, out_video: str | Path | None = None) -> dict[str, Any]:
    """Render scene PNGs with Playwright and assemble a vertical MP4."""
    plan = _load_plan(plan_path)
    issues = validate_plan(plan)
    if issues:
        raise ShortsError("short rejected:\n- " + "\n- ".join(issues))
    _require_binary("node")
    _require_binary("ffmpeg")

    slug = plan.get("source", {}).get("slug") or slugify(plan.get("hook", "short"))
    out_dir = SHORTS_DIR / slug
    scenes_dir = out_dir / "scenes"
    html_dir = out_dir / "html"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)
    out_video = Path(out_video or out_dir / f"{slug}.mp4")
    out_video.parent.mkdir(parents=True, exist_ok=True)

    scene_paths = []
    for idx, scene in enumerate(plan["scenes"], start=1):
        html_path = html_dir / f"scene_{idx:02d}.html"
        png_path = scenes_dir / f"scene_{idx:02d}.png"
        html_path.write_text(render_scene_html(plan, scene, idx), encoding="utf-8")
        _render_png(html_path, png_path)
        scene_paths.append((png_path, float(scene.get("duration_seconds", 4.0))))

    concat_file = out_dir / "ffmpeg_images.txt"
    concat_file.write_text(_concat_file(scene_paths), encoding="utf-8")
    voice_path = _voiceover_audio(plan, out_dir)
    _assemble_video(concat_file, out_video, voice_path)
    meta = {
        "video": str(out_video),
        "scenes": [str(p) for p, _ in scene_paths],
        "plan": str(plan_path),
        "has_voiceover": bool(voice_path),
    }
    (out_dir / "render_result.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def preview_short(video: str | Path, plan_path: str | Path | None = None) -> None:
    """Send a Telegram preview. Publishing remains a separate approval step."""
    load_env()
    sys.path.insert(0, str(ROOT / "scripts"))
    import telegram_poster  # type: ignore

    video = Path(video)
    if not video.exists():
        raise ShortsError(f"video not found: {video}")
    plan = _load_plan(plan_path) if plan_path else {}
    title = plan.get("publish_metadata", {}).get("title") or video.name
    msg = (
        "Shorts preview ready for approval:\n"
        f"{title}\n\n"
        f"Local file: {video}\n"
        "Reply with approval before running the publish command."
    )
    if hasattr(telegram_poster, "post_video"):
        sent = telegram_poster.post_video(str(video), caption=msg)
    else:
        sent = telegram_poster.post_message(msg)
    if sent is None:
        raise ShortsError("Telegram preview failed or Telegram credentials are missing")


def publish_short(provider: str, video: str | Path, plan_path: str | Path | None = None) -> None:
    """Publish an approved short to the requested provider."""
    video = Path(video)
    if provider != "youtube":
        raise ShortsError(f"unsupported shorts provider: {provider}")
    if not video.exists():
        raise ShortsError(f"video not found: {video}")
    plan = _load_plan(plan_path) if plan_path else {}
    metadata = plan.get("publish_metadata", {})
    title = metadata.get("title") or video.stem.replace("-", " ").title()
    description = metadata.get("description") or ""
    tags = ",".join(metadata.get("tags") or ["BuildWithAbdallah", "Programming", "Shorts"])
    category = str(metadata.get("category_id") or "28")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "youtube_shorts_publisher.py"),
        "upload",
        "--video", str(video),
        "--title", title,
        "--description", description,
        "--privacy", metadata.get("privacy") or "public",
        "--tags", tags,
        "--category-id", category,
    ]
    res = subprocess.run(cmd, cwd=str(ROOT), text=True)
    if res.returncode != 0:
        raise ShortsError("YouTube Shorts upload failed")


def validate_plan(plan: dict[str, Any]) -> list[str]:
    """Return validation issues. Empty means the short is safe to render."""
    issues: list[str] = []
    short_type = plan.get("short_type")
    if short_type not in ALLOWED_SHORT_TYPES:
        issues.append(f"invalid short_type: {short_type}")
    combined = " ".join(_walk_strings(plan)).lower()
    for phrase in HYPE_WORDS:
        if phrase in combined:
            issues.append(f"hype phrase used: {phrase}")
    scenes = plan.get("scenes") or []
    if len(scenes) < 3:
        issues.append("needs at least 3 useful scenes")
    has_code = any((s.get("code") or s.get("before_code") or s.get("after_code")) for s in scenes)
    has_terminal = any(s.get("commands") for s in scenes)
    has_diagram = any(s.get("diagram") or s.get("nodes") for s in scenes)
    has_takeaway = bool(plan.get("main_idea") or any(s.get("takeaway") for s in scenes))
    if not (has_code or has_terminal or has_diagram or has_takeaway):
        issues.append("needs code, terminal commands, a diagram, or a practical takeaway")
    useful_before_cta = [s for s in scenes[:-1] if s.get("kind") not in {"cta", "cta_card"}]
    if not useful_before_cta:
        issues.append("CTA appears before useful content")
    if scenes and scenes[0].get("kind") in {"cta", "cta_card"}:
        issues.append("CTA cannot be the first scene")
    for i, scene in enumerate(scenes, start=1):
        for field in ("caption", "title"):
            value = str(scene.get(field) or "")
            if len(value) > 90:
                issues.append(f"scene {i} {field} is too long for readable captions")
        for field in ("code", "before_code", "after_code", "commands"):
            value = scene.get(field)
            lines = value if isinstance(value, list) else str(value or "").splitlines()
            if len(lines) > 14:
                issues.append(f"scene {i} has too many {field} lines for a Short")
            if any(len(str(line)) > 74 for line in lines):
                issues.append(f"scene {i} has tiny-text risk in {field}; shorten long lines")
    return sorted(set(issues))


def render_scene_html(plan: dict[str, Any], scene: dict[str, Any], index: int) -> str:
    kind = scene.get("kind") or _kind_for_type(plan.get("short_type"))
    template = TEMPLATES_DIR / f"{kind}.html"
    if not template.exists():
        template = TEMPLATES_DIR / "title_card.html"
    values = {
        "brand": "Build With Abdallah",
        "watermark": _watermark_html(),
        "progress": html.escape(f"{index}/{len(plan.get('scenes') or [])}"),
        "short_type": html.escape(str(plan.get("short_type", ""))),
        "hook": html.escape(str(plan.get("hook", ""))),
        "main_idea": html.escape(str(plan.get("main_idea", ""))),
        "title": html.escape(str(scene.get("title") or plan.get("hook") or "")),
        "caption": html.escape(str(scene.get("caption") or "")),
        "takeaway": html.escape(str(scene.get("takeaway") or "")),
        "code": _highlight_code(scene.get("code") or ""),
        "before_code": _highlight_code(scene.get("before_code") or ""),
        "after_code": _highlight_code(scene.get("after_code") or ""),
        "commands": _terminal_lines(scene.get("commands") or []),
        "diagram": _diagram_html(scene),
        "cta": html.escape(str(plan.get("cta") or "Read the full guide")),
        "url": html.escape(str(plan.get("source", {}).get("url") or "buildwithabdallah.com")),
    }
    raw = template.read_text(encoding="utf-8")
    for key, value in values.items():
        raw = raw.replace("{{" + key + "}}", str(value))
    return raw


def _llm_plan(article: Article) -> dict[str, Any] | None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    prompt = _planner_prompt(article)
    try:
        r = requests.post(
            os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("SHORTS_LLM_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.35,
                "max_tokens": 1800,
                "response_format": {"type": "json_object"},
            },
            timeout=90,
        )
        if not r.ok:
            print(f"short planner LLM failed ({r.status_code}): {r.text[:200]}")
            return None
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        print(f"short planner LLM failed ({exc}); using deterministic fallback")
        return None


def _planner_prompt(article: Article) -> str:
    return (
        "Create a technical YouTube Short plan for Build With Abdallah. "
        "Return STRICT JSON only. The Short must teach one concrete developer idea, "
        "not promote the article. Avoid hype words. CTA only at the end.\n\n"
        f"Allowed short_type values: {', '.join(sorted(ALLOWED_SHORT_TYPES))}\n\n"
        "Required JSON keys: short_type, hook, main_idea, scenes, voiceover, captions, cta, publish_metadata.\n"
        "Scene keys: kind, title, caption, duration_seconds, and one of code, commands, before_code/after_code, diagram, takeaway.\n"
        "Use <= 6 scenes. Keep code/terminal lines short and readable on 1080x1920.\n\n"
        "CRITICAL: The \"captions\" key must be an array of SHORT SENTENCES or PHRASES, "
        "one per scene. Each caption must be 5-58 characters. "
        "Do NOT split text into single characters. "
        "Example: [\"Set up the project\", \"Add the coroutine\", \"See it run\"]\n\n"
        f"TITLE: {article.title}\nURL: {article.url}\nARTICLE:\n{article.body[:6000]}"
    )


def _fallback_plan(article: Article) -> dict[str, Any]:
    snippets = _extract_code_blocks(article.body)
    commands = [s for s in snippets if s["lang"] in {"bash", "sh", "shell", "zsh", "console"}]
    code = [s for s in snippets if s["lang"] not in {"bash", "sh", "shell", "zsh", "console"}]
    if commands:
        short_type = "terminal_workflow"
        command_lines = _short_code(commands[0]["code"], max_lines=7)
        practical = "Run the workflow in small checks instead of guessing from a long setup."
        scenes = [
            {"kind": "title_card", "title": article.title, "caption": "One practical workflow", "duration_seconds": 3},
            {"kind": "terminal_window", "title": "Run the core commands", "commands": command_lines, "caption": "Start with the smallest working path.", "duration_seconds": 6},
            {"kind": "mistake_fix", "title": "Common mistake", "caption": "Skipping verification makes failures harder to debug.", "takeaway": "Verify each step before moving on.", "duration_seconds": 4},
            {"kind": "cta_card", "title": "Full guide", "caption": "Read the full tutorial for the complete setup.", "duration_seconds": 3},
        ]
    elif code:
        short_type = "before_after_code"
        lines = _short_code(code[0]["code"], max_lines=9)
        split = max(1, len(lines) // 2)
        practical = "Keep the important logic visible and remove the part that hides the decision."
        scenes = [
            {"kind": "title_card", "title": article.title, "caption": "One code idea worth keeping", "duration_seconds": 3},
            {"kind": "before_after", "title": "Before and after", "before_code": lines[:split], "after_code": lines[split:] or lines, "caption": "Compare the change, not the whole file.", "duration_seconds": 7},
            {"kind": "code_card", "title": "The useful part", "code": lines[:8], "caption": "This is the piece to reuse.", "duration_seconds": 6},
            {"kind": "cta_card", "title": "Full guide", "caption": "Read the full tutorial for the complete implementation.", "duration_seconds": 3},
        ]
    else:
        short_type = "article_summary_with_practical_takeaway"
        practical = _first_sentence(article.body) or "Pick one practical decision from the tutorial and test it in a small project."
        scenes = [
            {"kind": "title_card", "title": article.title, "caption": "Practical takeaway", "duration_seconds": 3},
            {"kind": "architecture_diagram", "title": "The mental model", "diagram": ["Input", "Process", "Result"], "caption": "Understand the flow before coding.", "duration_seconds": 5},
            {"kind": "mistake_fix", "title": "What to avoid", "caption": "Do not copy the pattern before knowing the tradeoff.", "takeaway": practical[:120], "duration_seconds": 5},
            {"kind": "cta_card", "title": "Full guide", "caption": "Read the article for the complete details.", "duration_seconds": 3},
        ]
    return {
        "short_type": short_type,
        "hook": _short_hook(article.title),
        "main_idea": practical,
        "scenes": scenes,
        "voiceover": " ".join([s.get("caption", "") for s in scenes if s.get("caption")]),
        "captions": [s.get("caption", "") for s in scenes if s.get("caption")],
        "cta": "Read the full guide at buildwithabdallah.com",
        "publish_metadata": _metadata(article, short_type),
    }


def _normalise_scenes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    scenes = plan.get("scenes") or []
    out: list[dict[str, Any]] = []
    for raw in scenes[:6]:
        if not isinstance(raw, dict):
            continue
        scene = dict(raw)
        scene["kind"] = _normalise_kind(scene.get("kind") or _kind_for_type(plan.get("short_type")))
        # Fix LLM putting code on title_card scenes
        if scene["kind"] == "title_card":
            if scene.get("before_code") and scene.get("after_code"):
                scene["kind"] = "before_after"
            elif scene.get("code") or scene.get("before_code") or scene.get("after_code"):
                scene["kind"] = "code_card"
            elif scene.get("commands"):
                scene["kind"] = "terminal_window"
        # code_card template only has {{code}}; merge before/after into code
        if scene["kind"] == "code_card" and not scene.get("code"):
            parts = []
            if scene.get("before_code"):
                parts.append("// BEFORE")
                bc = scene["before_code"]
                parts.extend(bc if isinstance(bc, list) else str(bc).splitlines())
            if scene.get("after_code"):
                parts.append("// AFTER")
                ac = scene["after_code"]
                parts.extend(ac if isinstance(ac, list) else str(ac).splitlines())
            if parts:
                scene["code"] = parts
        scene["title"] = _clean_text(scene.get("title") or "", 70)
        scene["caption"] = _clean_text(scene.get("caption") or scene.get("takeaway") or "", 86)
        scene["duration_seconds"] = max(2.0, min(float(scene.get("duration_seconds") or 4.0), 8.0))
        for field in ("code", "before_code", "after_code", "commands"):
            if field in scene:
                scene[field] = _short_code(scene[field], max_lines=12)
        out.append(scene)
    if not out or out[-1].get("kind") != "cta_card":
        out.append({"kind": "cta_card", "title": "Full guide", "caption": "Read the full tutorial.", "duration_seconds": 3})
    return out


def _normalise_metadata(plan: dict[str, Any], article: Article) -> dict[str, Any]:
    meta = dict(plan.get("publish_metadata") or {})
    fallback = _metadata(article, plan.get("short_type") or "technical_short")
    for key, value in fallback.items():
        meta.setdefault(key, value)
    title = _clean_text(str(meta.get("title") or fallback["title"]), 95)
    if "#Shorts" not in title:
        title = (title[:86].rstrip() + " #Shorts").strip()
    meta["title"] = title
    meta["privacy"] = meta.get("privacy") or "public"
    meta["category_id"] = str(meta.get("category_id") or "28")
    tags = meta.get("tags") or fallback["tags"]
    meta["tags"] = [str(t).lstrip("#") for t in tags][:12]
    return meta


def _metadata(article: Article, short_type: str) -> dict[str, Any]:
    return {
        "title": f"{article.title[:82]} #Shorts",
        "description": f"{article.title}\n{article.url}\n\n#Shorts #BuildWithAbdallah",
        "tags": ["BuildWithAbdallah", "Programming", "Tutorial", "Shorts", short_type],
        "privacy": "public",
        "category_id": "28",
    }


def _render_png(html_path: Path, png_path: Path) -> None:
    cmd = ["node", str(ROOT / "scripts" / "render_card.mjs"), str(html_path), str(png_path), "1080", "1920"]
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise ShortsError(f"Playwright render failed for {html_path.name}:\n{res.stderr or res.stdout}")


def _voiceover_audio(plan: dict[str, Any], out_dir: Path) -> Path | None:
    if os.environ.get("SHORTS_SKIP_VOICEOVER") == "1":
        return None
    voiceover = str(plan.get("voiceover") or "").strip()
    if not voiceover:
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import reel_generator  # type: ignore
        out = out_dir / "voiceover.mp3"
        rendered = reel_generator.tts(voiceover, str(out))
        return Path(rendered) if rendered else None
    except Exception as exc:
        print(f"voiceover skipped: {exc}")
        return None


def _assemble_video(concat_file: Path, out_video: Path, voice_path: Path | None) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
    ]
    has_voice = voice_path and voice_path.exists()
    if has_voice:
        # Loop voiceover audio to fill the full video duration
        cmd += ["-stream_loop", "-1", "-i", str(voice_path)]
    cmd += [
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "-r", "30",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
    ]
    if has_voice:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    cmd += [str(out_video)]
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=180)
    if res.returncode != 0:
        raise ShortsError("ffmpeg failed:\n" + (res.stderr[-1200:] or res.stdout[-1200:]))


def _concat_file(scene_paths: list[tuple[Path, float]]) -> str:
    lines = []
    for path, duration in scene_paths:
        lines.append(f"file '{path.resolve()}'")
        lines.append(f"duration {duration:.2f}")
    if scene_paths:
        lines.append(f"file '{scene_paths[-1][0].resolve()}'")
    return "\n".join(lines) + "\n"


def _load_plan(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require_binary(name: str) -> None:
    if not shutil.which(name):
        raise ShortsError(f"{name} is required for shorts rendering")


def _find_local_draft(slug: str) -> Path | None:
    drafts = ROOT / "content" / "drafts"
    matches = sorted(drafts.glob(f"*{slug}*.md")) if drafts.exists() else []
    return matches[-1] if matches else None


def _fetch_post(slug: str) -> dict[str, Any] | None:
    base = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
    headers = {"Accept": "application/json"}
    if os.environ.get("BLOG_API_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['BLOG_API_TOKEN']}"
    try:
        r = requests.get(base + "/posts", params={"per_page": 80}, headers=headers, timeout=20)
        if not r.ok:
            return None
        for post in r.json().get("data", []):
            if post.get("slug") == slug:
                return post
    except Exception:
        return None
    return None


def _first_heading(body: str) -> str:
    m = re.search(r"^#\s+(.+)$", body or "", flags=re.MULTILINE)
    return m.group(1).strip() if m else ""


def _first_sentence(body: str) -> str:
    plain = re.sub(r"`{3}[\s\S]*?`{3}", "", body or "")
    plain = re.sub(r"[*#>`_\[\]()]|https?://\S+", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain.split(". ")[0][:180] if plain else ""


def _short_hook(title: str) -> str:
    return _clean_text(f"Here is one practical idea from {title}", 86)


def _extract_code_blocks(body: str) -> list[dict[str, str]]:
    blocks = []
    for m in re.finditer(r"```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```", body or ""):
        blocks.append({"lang": (m.group(1) or "text").lower(), "code": m.group(2).strip()})
    return blocks


def _short_code(value: Any, max_lines: int = 10) -> list[str]:
    if isinstance(value, list):
        lines = [str(v).rstrip() for v in value]
    else:
        lines = str(value or "").splitlines()
    clean = [line.rstrip()[:74] for line in lines if line.strip()]
    return clean[:max_lines]


def _clean_text(value: Any, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for phrase in HYPE_WORDS:
        text = re.sub(re.escape(phrase), "practical", text, flags=re.IGNORECASE)
    return text[:max_chars].rstrip()


def _short_lines(values: list[Any], limit: int, max_chars: int) -> list[str]:
    # If the LLM returned a single string instead of a list, split on sentences
    if len(values) == 1 and isinstance(values[0], str):
        raw = values[0]
        if len(raw) > max_chars or "|" in raw:
            values = [s.strip() for s in re.split(r"[|\n]", raw) if s.strip()]
        else:
            values = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    # Guard against single-character items (LLM sometimes splits strings into chars)
    if values and all(isinstance(v, str) and len(v) <= 2 and v.strip().isalpha() for v in values if v is not None):
        # Rejoin and re-split as sentences
        joined = " ".join(v for v in values if v)
        values = [s.strip() for s in re.split(r"(?<=[.!?])\s+", joined) if s.strip()]
        if not values or len(values) < 2:
            # Could not split into sentences; use the whole joined string
            values = [joined.strip()] if joined.strip() else []
    return [_clean_text(v, max_chars) for v in values if _clean_text(v, max_chars)][:limit]


def _voiceover_from_scenes(plan: dict[str, Any]) -> str:
    bits = [plan.get("hook", ""), plan.get("main_idea", "")]
    bits.extend(scene.get("caption", "") for scene in plan.get("scenes", []))
    bits.append(plan.get("cta", ""))
    return _clean_text(" ".join(bits), 900)


def _normalise_short_type(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in ALLOWED_SHORT_TYPES else "article_summary_with_practical_takeaway"


def _normalise_kind(value: Any) -> str:
    allowed = {
        "code_card", "terminal_window", "architecture_diagram", "before_after",
        "mistake_fix", "title_card", "cta_card",
    }
    text = str(value or "").strip()
    # Map scene types with code fields to appropriate template kinds
    if text in allowed:
        return text
    # Fallback heuristics for common LLM mis-mappings
    if text == "cta":
        return "cta_card"
    if text == "code":
        return "code_card"
    if text == "terminal":
        return "terminal_window"
    if text == "diagram":
        return "architecture_diagram"
    return "title_card"


def _kind_for_type(short_type: str) -> str:
    return {
        "before_after_code": "before_after",
        "terminal_workflow": "terminal_window",
        "architecture_diagram": "architecture_diagram",
        "mistake_fix": "mistake_fix",
        "tool_test_result": "terminal_window",
    }.get(short_type, "title_card")


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_walk_strings(item))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_walk_strings(item))
        return out
    return []


def _highlight_code(lines: Any) -> str:
    if isinstance(lines, str):
        lines = lines.splitlines()
    keywords = {
        "function", "return", "class", "def", "import", "from", "if", "else",
        "for", "while", "await", "async", "public", "private", "const", "let",
        "var", "use", "namespace", "new", "try", "catch",
    }
    rendered = []
    for line in _short_code(lines, 12):
        safe = html.escape(line)
        for kw in keywords:
            safe = re.sub(rf"\b{re.escape(kw)}\b", f'<span class="kw">{kw}</span>', safe)
        rendered.append(f"<div><span class=\"ln\">{len(rendered)+1:02d}</span>{safe}</div>")
    return "\n".join(rendered) or "<div><span class=\"ln\">01</span>// practical idea</div>"


def _terminal_lines(lines: Any) -> str:
    rendered = []
    for line in _short_code(lines, 10):
        prefix = "$ " if not str(line).lstrip().startswith(("$", ">")) else ""
        rendered.append(f"<div><span class=\"prompt\">{html.escape(prefix)}</span>{html.escape(str(line))}</div>")
    return "\n".join(rendered) or '<div><span class="prompt">$ </span>run the smallest check first</div>'


def _diagram_html(scene: dict[str, Any]) -> str:
    raw = scene.get("diagram") or scene.get("nodes") or ["Input", "Process", "Result"]
    nodes = raw if isinstance(raw, list) else str(raw).split("->")
    parts = []
    for i, node in enumerate(nodes[:5]):
        parts.append(f'<div class="node">{html.escape(str(node).strip()[:42])}</div>')
        if i < min(len(nodes), 5) - 1:
            parts.append('<div class="arrow">↓</div>')
    return "\n".join(parts)


def _watermark_html() -> str:
    candidates = [
        ROOT / "content" / "assets" / "brand" / "bwa-youtube-watermark.png",
        ROOT / "content" / "assets" / "brand" / "logo.png",
    ]
    for path in candidates:
        if path.exists():
            return f'<img class="wm-img" src="{path.resolve().as_uri()}" alt="Build With Abdallah" />'
    return '<div class="wm-text">BWA</div>'
