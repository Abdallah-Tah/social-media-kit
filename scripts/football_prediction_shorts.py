#!/usr/bin/env python3
"""Per-match FULL-SCREEN prediction Shorts (modular variant system) — auto.

For each upcoming World Cup match: pull the model's read (win probabilities,
predicted scoreline, key factor), render the full-screen Remotion
"PredictionShort" composition (Jarnathan voice), upload to YouTube + cross-post
FB/LinkedIn. Deduped via content/prediction_shorts_posted.json.

Variants (CLI --variant):
  key-factor-mystery  hook = "One stat changed the X vs Y prediction" (default)
  match-tension       hook = "This matchup is closer than it looks"
  result-curiosity    hook = "Will X pull the upset?"

The legacy "Prediction" composition is left untouched.

  /usr/bin/python3 scripts/football_prediction_shorts.py --dry-run
  /usr/bin/python3 scripts/football_prediction_shorts.py --privacy public --max 4
  /usr/bin/python3 scripts/football_prediction_shorts.py --variant-samples
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
SAMPLES_DIR = OUT_DIR / "samples"
POSTED = KIT / "content" / "prediction_shorts_posted.json"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"
RENDER_TIMEOUT_SECS = int(os.environ.get("PRED_SHORT_RENDER_TIMEOUT_SECS", "1200"))
UPLOAD_TIMEOUT_SECS = int(os.environ.get("PRED_SHORT_UPLOAD_TIMEOUT_SECS", "600"))
MIN_VIDEO_BYTES = int(os.environ.get("PRED_SHORT_MIN_VIDEO_BYTES", "1000000"))

VARIANT_ORDER = ["key-factor-mystery", "match-tension", "result-curiosity"]

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
        label = top["label"]
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
    """Continuity stats from the IMMUTABLE accuracy CLI (never backfill/fake)."""
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


def _variant_copy(home: str, away: str, leader: str, other: str, outcome: str, confidence: int,
                    key_factor: str, probs: dict, ledger: dict | None, variant: str) -> dict:
    """Generate hook/subheadline/factors/verdict copy for a given variant."""
    strong = confidence >= 55
    win_p = probs["homeP"] if leader == home else probs["awayP"]
    draw_p = probs["drawP"]
    loss_p = probs["awayP"] if leader == home else probs["homeP"]
    credibility = ledger["banner"] if ledger else "Independent AI model"

    if variant == "match-tension":
        hook = f"This {home} vs {away} matchup is closer than it looks."
        subheadline = "The model sees a tight contest — here is where the edge sits."
        factor_label = "WHY THE MODEL IS NERVOUS"
        tension_label = "TIGHT MATCHUP"
        tension_factors = [
            f"{leader} only holds a slight edge on the numbers",
            f"{other} can flip it with one good half",
            "First goal pressure is the model's swing factor",
        ]
        factors = [
            key_factor or f"{leader} rate higher in our model",
            f"{other} threaten in transition",
            "First goal changes the game",
        ]
    elif variant == "result-curiosity":
        hook = f"Will {other} pull the upset against {leader}?"
        subheadline = "The model's answer is locked in."
        factor_label = "HOW THE MODEL DECIDED"
        tension_label = "UPSET WATCH"
        tension_factors = [
            f"{other}'s path to a shock result",
            f"{leader}'s advantage in the model",
            "One moment can override the probability",
        ]
        factors = [
            key_factor or f"{leader} rate higher in our model",
            f"{other} can threaten in transition",
            "First goal changes the game",
        ]
    else:  # key-factor-mystery (default)
        if strong:
            hook = f"One stat changed the {home} vs {away} prediction."
            subheadline = f"The model still favors {leader} — but the gap matters."
        else:
            hook = f"One stat flipped the {home} vs {away} read."
            subheadline = "This is closer than the names suggest."
        factor_label = "THE STAT THAT CHANGED IT"
        tension_label = "KEY FACTORS"
        tension_factors = [
            key_factor or f"{leader} rate higher in our model",
            f"{other} can threaten in transition",
            "First goal changes the game",
        ]
        factors = [
            key_factor or f"{leader} rate higher in our model",
            f"{other} can threaten in transition",
            "First goal changes the game",
        ]

    if outcome == "draw":
        verdict = "Too close — draw likely"
        cta = f"Can {home} or {away} break the deadlock? Follow for the recap."
    else:
        verdict = f"{leader} to win"
        cta = f"Follow BuildWithAbdallah to see if {leader} gets it done."

    return {
        "hook": hook, "subheadline": subheadline,
        "factorLabel": factor_label, "tensionLabel": tension_label,
        "factors": factors, "tensionFactors": tension_factors,
        "verdict": verdict, "cta": cta,
        "winProb": win_p, "drawProb": draw_p, "lossProb": loss_p,
        "credibilityChip": credibility,
    }


def build_props(p: dict, ledger: dict | None = None, variant: str = "key-factor-mystery") -> dict:
    home, away = p["home"], p["away"]
    outcome = p["outcome"]
    leader = home if p["probs"]["homeP"] >= p["probs"]["awayP"] else away
    other = away if leader == home else home
    confidence = p["lead_prob"]
    copy = _variant_copy(home, away, leader, other, outcome, confidence,
                         p.get("key_factor", ""), p["probs"], ledger, variant)

    durations = {
        "key-factor-mystery": [2, 4, 7, 4, 3],
        "match-tension": [2, 4, 6, 5, 3],
        "result-curiosity": [2, 4, 6, 5, 3],
    }.get(variant, [2, 4, 7, 4, 3])

    return {
        "variant": variant,
        "home": home, "away": away, "competition": "World Cup 2026",
        "homeFlag": "flag_home.png", "awayFlag": "flag_away.png",
        "leader": leader,
        "confidence": round(confidence),
        "winProb": copy["winProb"],
        "drawProb": copy["drawProb"],
        "lossProb": copy["lossProb"],
        "verdict": copy["verdict"],
        "credibilityChip": copy["credibilityChip"],
        "hook": copy["hook"],
        "subheadline": copy["subheadline"],
        "factorLabel": copy["factorLabel"],
        "factors": copy["factors"],
        "tensionLabel": copy["tensionLabel"],
        "tensionFactors": copy["tensionFactors"],
        "cta": copy["cta"],
        "durations": durations,
        "hasAudio": False,
        "audioFile": "voiceover.mp3",
    }


def voiceover(props: dict, out: Path) -> Path | None:
    import reel_generator  # type: ignore
    h, a = props["home"], props["away"]
    variant = props.get("variant", "key-factor-mystery")
    if variant == "match-tension":
        text = (
            f"{props['hook']} {h} versus {a} at the World Cup. "
            f"The model shows a tight win probability: {props['winProb']}% for {props['leader']}, "
            f"{props['drawProb']}% draw, {props['lossProb']}% for the underdog. "
            "Why it is so close: a slight edge on the numbers, one good half can flip it, and the first goal is the swing factor. "
            f"The model breaks the tie: {props['verdict']}. Follow to see if it holds up."
        )
    elif variant == "result-curiosity":
        text = (
            f"{props['hook']} {h} versus {a}. The model's answer is locked in: "
            f"{props['leader']} with a {props['confidence']}% win probability. "
            "How it decided: the ratings, the transition threat, and the pressure of the first goal. "
            f"Final model call — {props['verdict']}. Follow BuildWithAbdallah for the recap."
        )
    else:
        text = (
            f"{props['hook']} {h} versus {a} at the World Cup. "
            f"The model's read: {props['leader']} edge, {props['confidence']}% win probability. "
            "The key factors: the model's ratings, the transition threat, and why the first goal swings it. "
            f"Final model call — {props['verdict']}. Follow to see if the model gets it right."
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


def render_prediction(data: dict, ledger: dict | None, variant: str, out_dir: Path,
                      base_name: str, *, with_voice: bool = True,
                      dry_run: bool = False) -> Path | None:
    """Render one PredictionShort MP4 for the given variant."""
    PUBLIC.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    home, away = data["home"], data["away"]
    if not (fetch_flag(data["homeFlag_code"], PUBLIC / "flag_home.png")
            and fetch_flag(data["awayFlag_code"], PUBLIC / "flag_away.png")):
        print(f"[pred-short] missing flag for {home}/{away} — skip")
        return None

    props = build_props(data, ledger=ledger, variant=variant)
    props_path = out_dir / f"{base_name}_{variant}.props.json"
    props_path.write_text(json.dumps(props, indent=2))
    vo: Path | None = None
    if with_voice:
        vo = voiceover(props, out_dir / f"{base_name}_{variant}.mp3")

    out = out_dir / f"{base_name}_{variant}.mp4"
    tmp_out = out.with_suffix(".tmp.mp4")
    if tmp_out.exists():
        tmp_out.unlink()
    cmd = [NODE, str(REMOTION / "render.mjs"), "--id", "PredictionShort",
           "--props", str(props_path), "--out", str(tmp_out)]
    if vo:
        cmd += ["--audio", str(vo)]
    print(f"[pred-short] {home} vs {away} [{variant}] — rendering")
    if dry_run:
        print("[pred-short] DRY RUN — not rendering/uploading.")
        return None
    render = _run_with_timeout(cmd, cwd=REMOTION, timeout=RENDER_TIMEOUT_SECS)
    if render.returncode == 124:
        print(f"[pred-short] render timed out after {RENDER_TIMEOUT_SECS}s")
        tmp_out.unlink(missing_ok=True)
        return None
    if render.returncode != 0:
        print("[pred-short] render failed")
        print((render.stderr or "")[-600:])
        tmp_out.unlink(missing_ok=True)
        return None
    if not tmp_out.exists() or tmp_out.stat().st_size < MIN_VIDEO_BYTES:
        size = tmp_out.stat().st_size if tmp_out.exists() else 0
        print(f"[pred-short] render output invalid ({size} bytes)")
        tmp_out.unlink(missing_ok=True)
        return None
    tmp_out.replace(out)
    return out


def publish_match(fx: dict, privacy: str, dry_run: bool, variant: str,
                  next_fx: dict | None = None) -> bool:
    data = predict(fx)
    if not data:
        print(f"[pred-short] no model data for {fx.get('home_team_name')} vs {fx.get('away_team_name')} — skip")
        return False
    home, away = data["home"], data["away"]
    out = render_prediction(data, compute_ledger(), variant, OUT_DIR,
                            str(fx["match_id"]), with_voice=True, dry_run=dry_run)
    if not out:
        return False

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

    title = f"{home} vs {away} — AI Prediction 🏆 World Cup 2026"[:100]
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


def render_variant_samples(dry_run: bool = False) -> list[Path]:
    """Render all three variants for the next upcoming TIMED match (no upload, no voice)."""
    from pitch_agent.fixtures import get_upcoming_fixtures
    matches = [m for m in get_upcoming_fixtures(limit=50)
               if str(m.get("match_id")) not in _posted()
               and m.get("status") == "TIMED"
               and m.get("home_team_name") and m.get("away_team_name")]
    if not matches:
        print("[pred-short] no upcoming TIMED matches for variant samples")
        return []
    fx = matches[0]
    data = predict(fx)
    if not data:
        print(f"[pred-short] could not predict {fx.get('home_team_name')} vs {fx.get('away_team_name')}")
        return []
    ledger = compute_ledger()
    outputs: list[Path] = []
    meta = {"match_id": fx.get("match_id"), "home": data["home"], "away": data["away"],
            "date": fx.get("date"), "probs": data["probs"], "variants": {}}
    for variant in VARIANT_ORDER:
        out = render_prediction(data, ledger, variant, SAMPLES_DIR,
                                f"sample_{fx['match_id']}", with_voice=False, dry_run=dry_run)
        if out:
            outputs.append(out)
            props = build_props(data, ledger=ledger, variant=variant)
            meta["variants"][variant] = {
                "file": str(out), "props": props,
                "size_bytes": out.stat().st_size,
            }
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = SAMPLES_DIR / f"sample_{fx['match_id']}.metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"[pred-short] samples metadata: {meta_path}")
    return outputs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    ap.add_argument("--max", type=int, default=6)
    ap.add_argument("--variant", choices=VARIANT_ORDER, default="key-factor-mystery",
                    help="Default prediction Short variant")
    ap.add_argument("--variant-samples", action="store_true",
                    help="Render all 3 variants for the first upcoming match (no upload)")
    args = ap.parse_args()
    load_env()

    if args.variant_samples:
        outs = render_variant_samples(dry_run=args.dry_run)
        print(f"[pred-short] rendered {len(outs)} variant samples")
        for o in outs:
            print(f"  {o}")
        return 0 if outs else 1

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
            if publish_match(fx, args.privacy, args.dry_run, args.variant, next_fx=next_fx) and not args.dry_run:
                _mark(fx["match_id"])
                n += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[pred-short] {fx.get('match_id')} failed (non-fatal): {exc}")
    print(f"[pred-short] done — {n} posted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
