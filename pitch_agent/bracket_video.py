"""Animated World Cup-style bracket prediction video renderer.

This module uses the repo's deterministic HTML -> Playwright frames -> ffmpeg
pipeline. It intentionally uses local assets only and falls back to country
codes when a flag image is unavailable.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pitch_agent.config import ROOT, load_env

WIDTH = 1080
HEIGHT = 1920
DEFAULT_DURATION = 20.0
DEFAULT_FPS = 24
DISCLAIMER_REQUIRED = "not betting advice"
TEMPLATE = ROOT / "templates" / "pitch_agent" / "bracket_animation.html"
TEMPLATES = {
    "classic-v1": TEMPLATE,
    "viral-bracket-v2": ROOT / "templates" / "pitch_agent" / "bracket_animation_v2.html",
}
DEFAULT_STYLE = "viral-bracket-v2"
DEFAULT_OUT = ROOT / "content" / "assets" / "shorts" / "bracket_prediction" / "bracket_prediction.mp4"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"
FFMPEG = "/usr/bin/ffmpeg" if Path("/usr/bin/ffmpeg").exists() else "ffmpeg"

FORBIDDEN_TERMS = [
    "bet",
    "bets",
    "betting",
    "gamble",
    "gambling",
    "wager",
    "wagering",
    "odds",
    "parlay",
    "sportsbook",
    "bookmaker",
    "guaranteed",
    "guarantee",
    "lock",
    "sure win",
    "risk-free",
    "bet on",
]

ROUND_NAMES = ["Round of 32", "Round of 16", "Quarterfinals", "Semifinals", "Final"]


class BracketVideoError(RuntimeError):
    """Raised when the bracket payload or render pipeline is invalid."""


@dataclass(frozen=True)
class BracketRenderResult:
    video: Path | None
    preview: Path | None
    html: Path
    frames_dir: Path | None
    validation: dict[str, Any]


def load_payload(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_payload(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not str(payload.get("title", "")).strip():
        issues.append("payload.title is required")
    rounds = payload.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        issues.append("payload.rounds must be a non-empty list")
    champion = payload.get("champion")
    if not isinstance(champion, dict) or not str(champion.get("name", "")).strip():
        issues.append("payload.champion.name is required")
    disclaimer = str(payload.get("disclaimer", "")).strip()
    if not disclaimer:
        issues.append("payload.disclaimer is required")
    elif DISCLAIMER_REQUIRED not in disclaimer.lower():
        issues.append('payload.disclaimer must include "not betting advice"')

    text_blob = json.dumps(payload, ensure_ascii=False).lower()
    # The required compliance disclaimer contains the word "betting"; allow
    # that exact phrase while still blocking betting/gambling copy elsewhere.
    text_blob = text_blob.replace(DISCLAIMER_REQUIRED, "educational-disclaimer")
    for term in FORBIDDEN_TERMS:
        if _contains_forbidden(text_blob, term):
            issues.append(f"forbidden wording: {term}")

    if isinstance(rounds, list) and rounds:
        first_matches = rounds[0].get("matches", []) if isinstance(rounds[0], dict) else []
        if len(first_matches) != 16:
            issues.append("Round of 32 must include exactly 16 matches / 32 teams")
        for i, match in enumerate(first_matches):
            if not isinstance(match, dict):
                issues.append(f"Round of 32 match {i + 1} must be an object")
                continue
            for side in ("teamA", "teamB"):
                team = match.get(side)
                if not isinstance(team, dict) or not str(team.get("name", "")).strip():
                    issues.append(f"Round of 32 match {i + 1} missing {side}.name")
            winner = str(match.get("winner", "")).strip()
            names = {
                str((match.get("teamA") or {}).get("name", "")).strip(),
                str((match.get("teamB") or {}).get("name", "")).strip(),
            }
            if winner and winner not in names:
                issues.append(f"Round of 32 match {i + 1} winner must match teamA or teamB")

    return issues


def render_bracket_video(
    payload: dict[str, Any],
    out: str | Path | None = None,
    *,
    dry_run: bool = False,
    fps: int = DEFAULT_FPS,
    duration: float = DEFAULT_DURATION,
    workdir: str | Path | None = None,
    style: str = DEFAULT_STYLE,
    audio: str | Path | None = None,
) -> BracketRenderResult:
    issues = validate_payload(payload)
    if issues:
        raise BracketVideoError("Bracket payload validation failed:\n - " + "\n - ".join(issues))
    template = _template_for_style(style)
    if not template.exists():
        raise BracketVideoError(f"Template not found: {template}")
    audio_path = _resolve_optional_audio(audio)

    out_path = Path(out) if out else DEFAULT_OUT
    out_path = out_path if out_path.is_absolute() else ROOT / out_path
    render_dir = Path(workdir) if workdir else out_path.with_suffix("")
    render_dir.mkdir(parents=True, exist_ok=True)

    normalized = normalize_payload(payload, duration=duration, style=style)
    html_path = render_dir / "bracket_animation.html"
    html_path.write_text(_render_template(normalized, template), encoding="utf-8")

    validation = {
        "ok": True,
        "issues": [],
        "duration": duration,
        "fps": fps,
        "width": WIDTH,
        "height": HEIGHT,
        "teams": len(normalized["teams"]),
        "champion": normalized["champion"]["name"],
        "disclaimer": normalized["disclaimer"],
        "style": style,
        "audio": str(audio_path) if audio_path else "",
    }

    if dry_run:
        return BracketRenderResult(
            video=None,
            preview=None,
            html=html_path,
            frames_dir=None,
            validation=validation,
        )

    frames_dir = render_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    record_cmd = [
        NODE,
        str(ROOT / "scripts" / "record_frames.mjs"),
        str(html_path),
        str(frames_dir),
        f"{duration:.3f}",
        str(fps),
        str(WIDTH),
        str(HEIGHT),
    ]
    _run(record_cmd, "Playwright frame render failed", cwd=ROOT, timeout=900)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_cmd = [
        FFMPEG,
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "f_%05d.png"),
    ]
    if audio_path:
        ffmpeg_cmd += ["-i", str(audio_path)]
    ffmpeg_cmd += [
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if audio_path:
        ffmpeg_cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    ffmpeg_cmd.append(str(out_path))
    _run(ffmpeg_cmd, "ffmpeg video assembly failed", timeout=900)
    if not out_path.exists() or out_path.stat().st_size < 100_000:
        raise BracketVideoError(f"Video output is missing or too small: {out_path}")

    preview = out_path.with_name(out_path.stem + "_preview.png")
    preview_frame = frames_dir / f"f_{min(max(0, int((duration - 1.2) * fps)), int(duration * fps) - 1):05d}.png"
    if preview_frame.exists():
        shutil.copyfile(preview_frame, preview)

    return BracketRenderResult(
        video=out_path,
        preview=preview if preview.exists() else None,
        html=html_path,
        frames_dir=frames_dir,
        validation=validation,
    )


def normalize_payload(
    payload: dict[str, Any],
    *,
    duration: float = DEFAULT_DURATION,
    style: str = DEFAULT_STYLE,
) -> dict[str, Any]:
    first_matches = payload["rounds"][0]["matches"]
    bracket_rounds = _complete_rounds(payload)
    teams = _team_tracks(first_matches, bracket_rounds)
    champion_name = payload["champion"]["name"]
    champion_track = next((t for t in teams if t["name"] == champion_name), None)
    if not champion_track:
        raise BracketVideoError("champion must be one of the 32 starting teams")

    return {
        "title": payload.get("title", "World Cup 2026 Prediction Bracket"),
        "brand": payload.get("brand", "Build With Abdallah"),
        "subtitle": payload.get("subtitle", "The Pitch Agent"),
        "site": payload.get("site", "buildwithabdallah.com"),
        "disclaimer": payload["disclaimer"],
        "duration": duration,
        "style": style,
        "roundLabels": ["ROUND OF 32", "ROUND OF 16", "QUARTERFINALS", "SEMIFINALS", "FINAL", "CHAMPION"],
        "teams": teams,
        "paths": _bracket_paths(bracket_rounds),
        "champion": {
            **_clean_team(payload["champion"]),
            "flagSrc": _resolve_local_asset(payload["champion"].get("flag")),
            "flagEmoji": _flag_emoji(_clean_team(payload["champion"]).get("code", "")),
            "flagClass": _flag_class(_clean_team(payload["champion"])),
            "confidence": payload["champion"].get("confidence", ""),
        },
    }


def send_telegram_review(result: BracketRenderResult, payload: dict[str, Any], command: str) -> None:
    load_env()
    _telegram_env()
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import telegram_poster as TG  # type: ignore

    title = str(payload.get("title", "World Cup 2026 Prediction Bracket"))
    status = "PASS" if result.validation.get("ok") else "FAIL"
    packet = (
        "Animated bracket prediction review\n\n"
        f"Title: {title}\n"
        f"Video: {result.video or '(dry run - no video)'}\n"
        f"Preview: {result.preview or '(none)'}\n"
        f"HTML: {result.html}\n"
        f"Validation: {status}\n"
        f"Size: {WIDTH}x{HEIGHT}\n"
        f"Duration: {result.validation.get('duration')}s\n\n"
        "Publish/use after approval:\n"
        f"{command}"
    )
    if result.video:
        TG.post_video(str(result.video), caption=f"Bracket video review\n{title}\nValidation: {status}")
    if result.preview:
        TG.post_photo(str(result.preview), caption="Bracket video preview frame")
    TG.post_message(packet)


def _contains_forbidden(text_blob: str, term: str) -> bool:
    escaped = re.escape(term.lower())
    if " " in term or "-" in term:
        return escaped in text_blob
    return bool(re.search(rf"\b{escaped}\b", text_blob))


def _complete_rounds(payload: dict[str, Any]) -> list[list[dict[str, Any]]]:
    provided = payload.get("rounds", [])
    rounds: list[list[dict[str, Any]]] = []
    first = [_normalize_match(m) for m in provided[0]["matches"]]
    rounds.append(first)
    champion = str(payload["champion"]["name"]).strip()

    prev_winners = [_winner_team(m) for m in first]
    for round_index in range(1, 5):
        provided_matches = []
        if round_index < len(provided) and isinstance(provided[round_index], dict):
            provided_matches = provided[round_index].get("matches") or []
        if provided_matches:
            current = [_normalize_match(m) for m in provided_matches]
        else:
            current = []
            for i in range(0, len(prev_winners), 2):
                team_a = prev_winners[i]
                team_b = prev_winners[i + 1]
                winner = champion if champion in {team_a["name"], team_b["name"]} else team_a["name"]
                current.append({
                    "teamA": team_a,
                    "teamB": team_b,
                    "winner": winner,
                    "confidence": 50,
                })
        expected = max(1, 16 // (2 ** round_index))
        if len(current) != expected:
            raise BracketVideoError(f"{ROUND_NAMES[round_index]} must contain {expected} matches when provided")
        rounds.append(current)
        prev_winners = [_winner_team(m) for m in current]
    if prev_winners[0]["name"] != champion:
        rounds[-1][-1]["winner"] = champion
    return rounds


def _normalize_match(match: dict[str, Any]) -> dict[str, Any]:
    team_a = _clean_team(match.get("teamA") or {})
    team_b = _clean_team(match.get("teamB") or {})
    winner = str(match.get("winner") or team_a["name"]).strip()
    if winner not in {team_a["name"], team_b["name"]}:
        winner = team_a["name"]
    return {
        "teamA": team_a,
        "teamB": team_b,
        "winner": winner,
        "confidence": match.get("confidence", ""),
    }


def _clean_team(team: dict[str, Any]) -> dict[str, Any]:
    name = str(team.get("name", "")).strip()
    code = str(team.get("code", "" if not name else name[:3])).strip().upper()
    return {
        "name": name,
        "code": code[:4] if code else name[:3].upper(),
        "flag": str(team.get("flag", "")).strip(),
    }


def _winner_team(match: dict[str, Any]) -> dict[str, Any]:
    return match["teamA"] if match["winner"] == match["teamA"]["name"] else match["teamB"]


def _team_tracks(first_matches: list[dict[str, Any]], rounds: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    tracks: dict[str, dict[str, Any]] = {}
    slot = 0
    for match in first_matches:
        for side in ("teamA", "teamB"):
            team = _clean_team(match[side])
            tracks[team["name"]] = {
                **team,
                "slot": slot,
                "flagSrc": _resolve_local_asset(team.get("flag")),
                "flagEmoji": _flag_emoji(team.get("code", "")),
                "flagClass": _flag_class(team),
                "reached": 0,
                "positions": [_position(0, slot)],
            }
            slot += 1

    for round_index, matches in enumerate(rounds, start=1):
        for match_index, match in enumerate(matches):
            winner = match["winner"]
            if winner in tracks:
                tracks[winner]["reached"] = round_index
                tracks[winner]["positions"].append(_position(round_index, match_index))

    for track in tracks.values():
        reached = int(track["reached"])
        last = track["positions"][-1]
        while len(track["positions"]) < 6:
            track["positions"].append(last)
        track["opacityStops"] = _opacity_stops(reached)
        track["scaleStops"] = _scale_stops(reached)
        track["side"] = "left" if int(track["slot"]) < 16 else "right"
    return list(tracks.values())


def _position(stage: int, index: int) -> dict[str, int]:
    if stage == 0:
        local = index if index < 16 else index - 16
        x = 34 if index < 16 else 836
        return {"x": x, "y": 258 + local * 78, "anchorX": x + (34 if index < 16 else 176)}
    if stage == 1:
        local = index if index < 8 else index - 8
        x = 194 if index < 8 else 748
        return {"x": x, "y": 298 + local * 156, "anchorX": x + (34 if index < 8 else 176)}
    if stage == 2:
        local = index if index < 4 else index - 4
        x = 328 if index < 4 else 614
        return {"x": x, "y": 376 + local * 312, "anchorX": x + (34 if index < 4 else 176)}
    if stage == 3:
        local = index if index < 2 else index - 2
        x = 424 if index < 2 else 548
        return {"x": x, "y": 532 + local * 624, "anchorX": x + (34 if index < 2 else 176)}
    if stage == 4:
        x = 368 if index == 0 else 632
        return {"x": x, "y": 890, "anchorX": x + (48 if index == 0 else 162)}
    return {"x": 488, "y": 1260, "anchorX": 540}


def _opacity_stops(reached: int) -> list[float]:
    # stage 0..5. Losers fade before disappearing so advancement is readable.
    values = []
    for i in range(6):
        if i <= reached:
            values.append(1.0)
        elif i == reached + 1:
            values.append(0.25)
        else:
            values.append(0.0)
    return values


def _scale_stops(reached: int) -> list[float]:
    return [min(1.0 + i * 0.10, 1.46) if i <= reached else 0.42 for i in range(6)]


def _bracket_paths(rounds: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    for stage in range(1, 5):
        matches = rounds[stage - 1]
        for i, match in enumerate(matches):
            for source_offset, source_team in enumerate((match["teamA"], match["teamB"])):
                source_index = i * 2 + source_offset if stage == 1 else i * 2 + source_offset
                start = _position(stage - 1, source_index)
                end = _position(stage, i)
                active = source_team["name"] == match["winner"]
                paths.append(_path(
                    start,
                    end,
                    side="left" if end["x"] < 540 else "right",
                    stage=stage,
                    active=active,
                    champion=active and stage >= 4,
                ))
    final = rounds[4][0]
    for i, source_team in enumerate((final["teamA"], final["teamB"])):
        active = source_team["name"] == final["winner"]
        paths.append(_path(
            _position(4, i),
            _position(5, 0),
            side="left" if i == 0 else "right",
            stage=5,
            active=active,
            champion=active,
        ))
    return paths


def _path(
    start: dict[str, int],
    end: dict[str, int],
    *,
    side: str,
    stage: int,
    active: bool,
    champion: bool,
) -> dict[str, Any]:
    sx, sy = int(start.get("anchorX", start["x"] + 34)), start["y"] + 34
    ex, ey = int(end.get("anchorX", end["x"] + 34)), end["y"] + 34
    mid = (sx + ex) // 2
    return {
        "d": f"M {sx} {sy} H {mid} V {ey} H {ex}",
        "side": side,
        "stage": stage,
        "active": active,
        "champion": champion,
    }


def _resolve_local_asset(value: str | None) -> str:
    if not value:
        return ""
    path = Path(str(value))
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([
            ROOT / path,
            ROOT / "content" / "assets" / path,
            ROOT / "content" / "assets" / "flags" / path,
        ])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve().as_uri()
    return ""


def _template_for_style(style: str) -> Path:
    try:
        return TEMPLATES[style]
    except KeyError as exc:
        allowed = ", ".join(sorted(TEMPLATES))
        raise BracketVideoError(f"Unknown bracket video style '{style}'. Use one of: {allowed}") from exc


def _resolve_optional_audio(value: str | Path | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists() or not path.is_file():
        raise BracketVideoError(f"Audio file not found: {path}")
    return path


def _render_template(normalized: dict[str, Any], template: Path) -> str:
    data = json.dumps(normalized, ensure_ascii=False).replace("</", "<\\/")
    return template.read_text(encoding="utf-8").replace("__BRACKET_DATA__", data)


def _flag_class(team: dict[str, Any]) -> str:
    code = str(team.get("code", "")).lower()
    safe = re.sub(r"[^a-z0-9]+", "", code)
    return f"flag-{safe}" if safe else "flag-generic"


def _flag_emoji(code: str) -> str:
    normalized = {
        "ENG": "GB",
        "SCO": "GB",
        "WA": "GB",
        "UK": "GB",
    }.get(str(code).upper(), str(code).upper())
    if len(normalized) != 2 or not normalized.isalpha():
        return ""
    base = 0x1F1E6
    return "".join(chr(base + ord(ch) - ord("A")) for ch in normalized)


def _run(cmd: list[str], label: str, *, cwd: Path | None = None, timeout: int = 300) -> None:
    res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "")[-1400:]
        raise BracketVideoError(f"{label}:\n{tail}")


def _telegram_env() -> None:
    tok = Path(os.path.expanduser("~/.telegram-bot-token"))
    if tok.exists():
        token = tok.read_text(encoding="utf-8").strip()
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["TELEGRAM_TOKEN"] = token
    os.environ.setdefault("TELEGRAM_CHAT_ID", "-1003948211258")
    os.environ.setdefault("TELEGRAM_MESSAGE_THREAD_ID", "14119")
