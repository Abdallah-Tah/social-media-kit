from __future__ import annotations

import json
from pathlib import Path

from agent.cli import main as smkit_main
from pitch_agent.bracket_video import BracketVideoError, load_payload, render_bracket_video, validate_payload


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_bracket.json"


def test_payload_validation_accepts_sample():
    payload = load_payload(SAMPLE)
    assert validate_payload(payload) == []


def test_forbidden_wording_rejected():
    payload = load_payload(SAMPLE)
    payload["title"] = "Guaranteed lock World Cup bracket"
    issues = validate_payload(payload)
    assert any("guaranteed" in issue for issue in issues)
    assert any("lock" in issue for issue in issues)


def test_missing_disclaimer_rejected():
    payload = load_payload(SAMPLE)
    payload["disclaimer"] = "Educational prediction model"
    issues = validate_payload(payload)
    assert any("not betting advice" in issue for issue in issues)


def test_template_render_smoke(tmp_path):
    payload = load_payload(SAMPLE)
    result = render_bracket_video(payload, tmp_path / "bracket.mp4", dry_run=True, workdir=tmp_path / "render")
    html = result.html.read_text(encoding="utf-8")
    assert "World Cup 2026 Bracket Simulation" in html
    assert "Educational prediction model" in html
    assert "Brazil" in html
    assert "bracket_animation_v2" not in html
    assert result.video is None


def test_cli_dry_run(tmp_path):
    payload_path = tmp_path / "sample.json"
    payload_path.write_text(json.dumps(load_payload(SAMPLE)), encoding="utf-8")
    rc = smkit_main([
        "pitch-bracket-video",
        "--input",
        str(payload_path),
        "--out",
        str(tmp_path / "bracket.mp4"),
        "--dry-run",
        "--style",
        "viral-bracket-v2",
    ])
    assert rc == 0


def test_classic_v1_style_still_available(tmp_path):
    payload = load_payload(SAMPLE)
    result = render_bracket_video(
        payload,
        tmp_path / "classic.mp4",
        dry_run=True,
        workdir=tmp_path / "classic",
        style="classic-v1",
    )
    html = result.html.read_text(encoding="utf-8")
    assert "World Cup 2026 Bracket Simulation" in html
    assert result.validation["style"] == "classic-v1"


def test_render_raises_on_bad_payload(tmp_path):
    payload = load_payload(SAMPLE)
    payload.pop("champion")
    try:
        render_bracket_video(payload, tmp_path / "bad.mp4", dry_run=True)
    except BracketVideoError as exc:
        assert "champion" in str(exc)
    else:
        raise AssertionError("Expected BracketVideoError")
