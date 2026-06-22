#!/usr/bin/env python3
"""Per-match FULL-SCREEN prediction Shorts (the Mexico-vs-SA format) — auto.

For each upcoming World Cup match: pull the model's read (win probabilities,
predicted scoreline, key factor), render the full-screen Remotion "Prediction"
composition (Jarnathan voice), upload to YouTube + cross-post FB/LinkedIn.
Deduped via content/prediction_shorts_posted.json.

This REPLACES the old poster-wrapper per-match shorts (football_match_shorts.py).

  /usr/bin/python3 scripts/football_prediction_shorts.py --dry-run
  /usr/bin/python3 scripts/football_prediction_shorts.py --privacy public --max 4
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
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
OUT_DIR = KIT / "content" / "assets" / "shorts" / "predictions_auto"
POSTED = KIT / "content" / "prediction_shorts_posted.json"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"
RENDER_TIMEOUT_SECS = int(os.environ.get("PRED_SHORT_RENDER_TIMEOUT_SECS", "1200"))
UPLOAD_TIMEOUT_SECS = int(os.environ.get("PRED_SHORT_UPLOAD_TIMEOUT_SECS", "600"))
MIN_VIDEO_BYTES = int(os.environ.get("PRED_SHORT_MIN_VIDEO_BYTES", "1000000"))

# team name -> ISO-3166 alpha-2 (flagcdn); England/Scotland use GB subdivisions
FLAG = {
    "Algeria": "dz", "Argentina": "ar", "Australia": "au", "Austria": "at",
    "Belgium": "be", "Bosnia-H.": "ba", "Brazil": "br", "Canada": "ca",
    "Cape Verde": "cv", "Colombia": "co", "Congo DR": "cd", "Croatia": "hr",
    "Curaçao": "cw", "Czechia": "cz", "Ecuador": "ec", "Egypt": "eg",
    "England": "gb-eng", "France": "fr", "Germany": "de", "Ghana": "gh",
    "Haiti": "ht", "Iran": "ir", "Iraq": "iq", "Ivory Coast": "ci",
    "Japan": "jp", "Jordan": "jo", "Korea Republic": "kr", "Mexico": "mx",
    "Morocco": "ma", "Netherlands": "nl", "New Zealand": "nz", "Norway": "no",
    "Panama": "pa", "Paraguay": "py", "Portugal": "pt", "Qatar": "qa",
    "Saudi Arabia": "sa", "Scotland": "gb-sct", "Senegal": "sn",
    "South Africa": "za", "Spain": "es", "Sweden": "se", "Switzerland": "ch",
    "Tunisia": "tn", "Turkey": "tr", "USA": "us", "Uruguay": "uy",
    "Uzbekistan": "uz",
}


def _posted() -> set:
    try:
        return set(json.loads(POSTED.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _mark(mid: str) -> None:
    seen = _posted()
    seen.add(str(mid))
    POSTED.write_text(json.dumps(sorted(seen)[-400:]))


def todays_upcoming() -> list[dict]:
    from pitch_agent.fixtures import get_upcoming_fixtures
    from pitch_agent.content import _upcoming_fixtures
    return _upcoming_fixtures(get_upcoming_fixtures(limit=20), limit=12, today_only=True)


def predict(fixture: dict) -> dict | None:
    """Structured model read for a fixture (probs, scoreline, factors)."""
    from pitch_agent.poisson import (
        top_scorelines, match_outcome_probs, prediction_key_factor,
        predict_xg, resolve_predicted_outcome, TEAM_CODES,
    )
    from pitch_agent.content import DRAW_RHO, DRAW_PREF_EPS, MODEL_VERSION
    from pitch_agent.db import get_connection, get_team_prior, count_team_matches
    from pitch_agent.config import PitchAgentConfig

    home = fixture.get("home_team_name", "")
    away = fixture.get("away_team_name", "")
    if not home or not away:
        return None
    try:
        cfg = PitchAgentConfig.load()
        conn = get_connection(cfg.db_path)
    except Exception:
        return None
    try:
        rows = conn.execute(
            """SELECT p.team_name, AVG(s.score) avg_score
               FROM form_index_scores s
               JOIN player_match_stats p ON s.match_id=p.match_id AND s.player_id=p.player_id
               WHERE s.model_version=? AND (p.team_name=? OR p.team_name=?)
               GROUP BY p.team_name""",
            (MODEL_VERSION, home, away),
        ).fetchall()
        fi = {r["team_name"]: float(r["avg_score"]) for r in rows}
        hp = get_team_prior(conn, fixture.get("home_team_id") or home) or get_team_prior(conn, home)
        ap = get_team_prior(conn, fixture.get("away_team_id") or away) or get_team_prior(conn, away)
        he = hp["elo"] if hp else None
        ae = ap["elo"] if ap else None
        if (he is None and fi.get(home) is None) or (ae is None and fi.get(away) is None):
            return None
        hxg, axg, bh, ba = predict_xg(
            home_team=home, away_team=away,
            home_avg_fi=fi.get(home), away_avg_fi=fi.get(away),
            home_elo=he, away_elo=ae,
            home_matches=count_team_matches(conn, home),
            away_matches=count_team_matches(conn, away),
            host_nations=cfg.host_nations, host_team_ids=cfg.host_team_ids,
        )
        out = match_outcome_probs(hxg, axg, rho=DRAW_RHO)
        top = top_scorelines(hxg, axg, n=1, rho=DRAW_RHO)[0]
        outcome = resolve_predicted_outcome(out, top, draw_pref_eps=DRAW_PREF_EPS)
        kf = prediction_key_factor(
            [{"score": fi.get(home) or 50, "goals": 0}],
            [{"score": fi.get(away) or 50, "goals": 0}],
            home_elo=he, away_elo=ae, basis_home=bh, basis_away=ba,
            home_code=TEAM_CODES.get(home, ""), away_code=TEAM_CODES.get(away, ""),
            is_host_advantage=False,
        )
        hp_, dp_, ap_ = out["home_win"] * 100, out["draw"] * 100, out["away_win"] * 100
        label = top["label"]  # e.g. "2–1"
        return {
            "home": home, "away": away,
            "homeFlag_code": FLAG.get(home), "awayFlag_code": FLAG.get(away),
            "probs": {"homeP": round(hp_), "drawP": round(dp_), "awayP": round(ap_)},
            "scoreline": label, "outcome": outcome, "key_factor": kf,
            "lead_prob": max(hp_, dp_, ap_),
        }
    finally:
        conn.close()


def fetch_flag(code: str, dest: Path) -> bool:
    if not code:
        return False
    try:
        req = urllib.request.Request(f"https://flagcdn.com/w640/{code}.png",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            dest.write_bytes(r.read())
        return dest.stat().st_size > 0
    except Exception:
        return False


def compute_ledger() -> dict | None:
    """Continuity stats from the IMMUTABLE accuracy CLI (never backfill/fake).

    Source of truth: `pitch_agent.cli accuracy` → "Outcome: 16/26 correct (61.5%)".
    Returns {"banner": "Ledger 16-10 · 61.5%", "correct": 16, "total": 26,
    "pct": "61.5"} or None if no graded predictions yet. Streak/last-five are
    intentionally omitted: graded_at is batch-identical, so no honest
    chronological order exists.
    """
    try:
        r = _run_with_timeout(
            ["/usr/bin/python3", "-m", "pitch_agent.cli", "accuracy"],
            cwd=KIT, timeout=60, capture_output=True, text=True)
        if r.returncode != 0:
            return None
        m = re.search(r"Outcome:\s+(\d+)/(\d+)\s+correct\s+\(([\d.]+)%\)", r.stdout or "")
        if not m:
            return None
        correct, total, pct = int(m.group(1)), int(m.group(2)), m.group(3)
        if total <= 0:
            return None
        return {"banner": f"Ledger {correct}-{total - correct} · {pct}%",
                "correct": correct, "total": total, "pct": pct}
    except Exception:  # noqa: BLE001
        return None


def build_props(p: dict, ledger: dict | None = None, next_match: str | None = None) -> dict:
    home, away = p["home"], p["away"]
    outcome = p["outcome"]
    winner = home if outcome == "home" else away if outcome == "away" else None
    lead = p["lead_prob"]
    # Outcome-only output — call the winner, never a scoreline.
    if outcome == "draw":
        confidence = "Too even to split"
        lean = "Model leans a draw"
        hook = "This matchup is closer than it looks."
    else:
        strong = lead >= 55
        confidence = f"{'Strong' if strong else 'Slight'} {winner} edge"
        lean = f"{winner} to win"
        hook = "Our model sees one clear edge." if strong else "The model does not see this as a walkover."
    leader = home if p["probs"]["homeP"] >= p["probs"]["awayP"] else away
    other = away if leader == home else home
    reasons = [p["key_factor"][:26] if p.get("key_factor") else "Form & Elo read",
               "First goal matters", confidence]
    factors = [
        "Group stage pressure",
        "First goal changes the game",
        f"{leader} rate higher in our model",
        f"{other} can threaten in transition",
    ]
    final = f"{winner} to win" if outcome != "draw" else "Too close — draw"
    # Ledger-led "bridge" hook (Meta growth advice, brand-safe — analytics only,
    # no betting/bookie framing). Falls back to the per-match hook pre-ledger.
    if ledger:
        hook = f"{ledger['correct']} of {ledger['total']} calls right — here's the next one."
    return {
        "home": home, "away": away, "competition": "World Cup 2026",
        "hook": hook, "lean": lean, "confidence": confidence,
        "reasons": reasons, "probs": p["probs"], "factors": factors,
        "finalCall": final, "durations": [4, 6, 6, 6, 5],
        "homeFlag": "flag_home.png", "awayFlag": "flag_away.png",
        **({"ledger": ledger["banner"]} if ledger else {}),
        **({"nextMatch": next_match} if next_match else {}),
    }


def voiceover(props: dict, out: Path) -> Path | None:
    import reel_generator  # type: ignore
    h, a = props["home"], props["away"]
    text = (
        f"{props['hook']} {h} versus {a} at the World Cup. "
        f"The model's read: {props['confidence'].lower()}. "
        f"On the numbers, here is the win probability for {h}, the draw, and {a}. "
        "The key factors: group stage pressure, the first goal changing the game, and where the edge sits. "
        f"Final model call — {props['finalCall']}. An independent model prediction. "
        "Comment who you've got winning, and follow to see if the model gets it right."
    )
    r = reel_generator.tts(text, str(out))
    return Path(r) if r and Path(r).exists() else None


def _run_with_timeout(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int,
    capture_output: bool = False,
    text: bool = False,
) -> subprocess.CompletedProcess:
    stdout = subprocess.PIPE if capture_output else None
    stderr = subprocess.PIPE if capture_output else None
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=stdout,
        stderr=stderr,
        text=text,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    except KeyboardInterrupt:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
        raise
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        return subprocess.CompletedProcess(cmd, 124, out, err)


def publish_match(fx: dict, privacy: str, dry_run: bool, next_fx: dict | None = None) -> bool:
    data = predict(fx)
    if not data:
        print(f"[pred-short] no model data for {fx.get('home_team_name')} vs {fx.get('away_team_name')} — skip")
        return False
    home, away = data["home"], data["away"]
    PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not (fetch_flag(data["homeFlag_code"], PUBLIC / "flag_home.png")
            and fetch_flag(data["awayFlag_code"], PUBLIC / "flag_away.png")):
        print(f"[pred-short] missing flag for {home}/{away} — skip")
        return False

    next_match = None
    if next_fx:
        nh = next_fx.get("home_team_name", "")
        na = next_fx.get("away_team_name", "")
        if nh and na:
            next_match = f"{nh} vs {na}"
    props = build_props(data, ledger=compute_ledger(), next_match=next_match)
    props_path = OUT_DIR / "props.json"
    props_path.write_text(json.dumps(props, indent=2))
    vo = voiceover(props, OUT_DIR / "voiceover.mp3")

    out = OUT_DIR / f"{fx['match_id']}.mp4"
    tmp_out = out.with_suffix(".tmp.mp4")
    if tmp_out.exists():
        tmp_out.unlink()
    cmd = [NODE, str(REMOTION / "render.mjs"), "--id", "Prediction",
           "--props", str(props_path), "--out", str(tmp_out)]
    if vo:
        cmd += ["--audio", str(vo)]
    print(f"[pred-short] {home} vs {away} — rendering full-screen prediction")
    if dry_run:
        print("[pred-short] DRY RUN — not rendering/uploading.")
        return False
    render = _run_with_timeout(cmd, cwd=REMOTION, timeout=RENDER_TIMEOUT_SECS)
    if render.returncode == 124:
        print(f"[pred-short] render timed out after {RENDER_TIMEOUT_SECS}s")
        tmp_out.unlink(missing_ok=True)
        return False
    if render.returncode != 0:
        print("[pred-short] render failed")
        tmp_out.unlink(missing_ok=True)
        return False
    if not tmp_out.exists() or tmp_out.stat().st_size < MIN_VIDEO_BYTES:
        size = tmp_out.stat().st_size if tmp_out.exists() else 0
        print(f"[pred-short] render output invalid ({size} bytes)")
        tmp_out.unlink(missing_ok=True)
        return False
    tmp_out.replace(out)
    try:
        from worldcup_thumbnail import generate_thumbnail
        thumb = generate_thumbnail(
            OUT_DIR / f"{fx['match_id']}_thumb.jpg",
            title=f"{home} vs {away}",
            kind="AI PREDICTION",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[pred-short] thumbnail failed (non-fatal): {exc}")
        thumb = None

    title = f"{home} vs {away} — AI Prediction \U0001F3C6 World Cup 2026"[:100]
    desc = (f"{home} vs {away} — our independent model's World Cup 2026 read: model lean, "
            f"win probability, and key factors. Analytics only, not affiliated with FIFA.\n\n"
            "Comment who you've got winning. Follow to see if the model gets it right.\n\n"
            "#WorldCup2026 #WorldCup #Football #Soccer #FIFAWorldCup #AIPredictions #footballpredictions #Shorts")
    up = _run_with_timeout(
        ["/usr/bin/python3", str(KIT / "scripts" / "youtube_shorts_publisher.py"), "upload",
         "--video", str(out), "--title", title, "--description", desc,
         "--privacy", privacy, "--profile", "main", "--category-id", "17",
         "--tags", "WorldCup2026,WorldCup,football,soccer,FIFAWorldCup,AIpredictions,footballpredictions,shorts"]
        + (["--thumbnail", str(thumb)] if thumb else []),
        timeout=UPLOAD_TIMEOUT_SECS, capture_output=True, text=True)
    print((up.stdout or "")[-300:])
    if up.returncode == 124:
        print(f"[pred-short] upload timed out after {UPLOAD_TIMEOUT_SECS}s")
        return False
    if up.returncode != 0:
        print(f"[pred-short] upload failed: {(up.stderr or '')[-300:]}")
        return False
    import re
    m = re.search(r"https://www\.youtube\.com/shorts/[\w-]+", up.stdout)
    yt = m.group(0) if m else ""
    if privacy == "public":
        try:
            import subprocess as sp
            frame = OUT_DIR / "fb_frame.png"
            sp.run(["/usr/bin/ffmpeg", "-y", "-ss", "3", "-i", str(out), "-frames:v", "1", str(frame)], capture_output=True)
            from football_crosspost import crosspost
            crosspost(f"🤖 {home} vs {away} — World Cup 2026 model prediction. Win probability + key factors inside.",
                      youtube_url=yt, image_path=str(frame) if frame.exists() else None,
                      title=title)
        except Exception as exc:  # noqa: BLE001
            print(f"[pred-short] crosspost failed (non-fatal): {exc}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    ap.add_argument("--max", type=int, default=6)
    args = ap.parse_args()
    load_env()

    posted = _posted()
    matches = [m for m in todays_upcoming() if str(m.get("match_id")) not in posted]
    if not matches:
        print("[pred-short] no new upcoming matches today")
        return 0
    n = 0
    batch = matches[: args.max]
    for i, fx in enumerate(batch):
        next_fx = batch[i + 1] if i + 1 < len(batch) else None
        try:
            if publish_match(fx, args.privacy, args.dry_run, next_fx=next_fx) and not args.dry_run:
                _mark(fx["match_id"])
                n += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[pred-short] {fx.get('match_id')} failed (non-fatal): {exc}")
    print(f"[pred-short] done — {n} posted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
