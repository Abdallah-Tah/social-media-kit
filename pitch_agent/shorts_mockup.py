"""Reusable static-frame renderer for the World Cup Shorts variants.

Data-driven (no hardcoded match): given a match `data` dict + a variant id, it
renders the 3 key frames (hook / key-factors / verdict+CTA) as PNGs using the
Pi-safe headless path (CDP captureScreenshot, fromSurface:false). Shared by the
mockup board and the `smkit pitch-video` sample command.
"""
from __future__ import annotations

import base64
import subprocess
import urllib.request
from pathlib import Path

from . import shorts_meta as sm

_ROOT = Path(__file__).resolve().parents[1]

# team name -> flagcdn code (kept here so the renderer is self-contained)
try:  # reuse the canonical map if present
    import importlib.util
    _spec = importlib.util.spec_from_file_location("_fps", _ROOT / "scripts" / "football_prediction_shorts.py")
    FLAG = {}  # populated lazily below to avoid importing the whole script
except Exception:  # pragma: no cover
    FLAG = {}

_FLAG_FALLBACK = {
    "England": "gb-eng", "Croatia": "hr", "Scotland": "gb-sct", "Spain": "es",
    "Saudi Arabia": "sa", "Argentina": "ar", "Austria": "at", "France": "fr",
    "Iraq": "iq", "Norway": "no", "Senegal": "sn", "Jordan": "jo", "Algeria": "dz",
    "Japan": "jp", "Tunisia": "tn", "Mexico": "mx", "Brazil": "br", "Germany": "de",
    "Netherlands": "nl", "Portugal": "pt", "USA": "us", "Morocco": "ma",
}


def _flag_code(name: str) -> str:
    return _FLAG_FALLBACK.get(name, "")


def _flag_uri(name: str) -> str:
    code = _flag_code(name)
    if not code:
        return ""
    try:
        req = urllib.request.Request(f"https://flagcdn.com/w160/{code}.png",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return "data:image/png;base64," + base64.b64encode(r.read()).decode()
    except Exception:
        return ""


_CSS = (Path(__file__).parent / "_shorts_card.css")
# Inline CSS (kept in-module so there is no extra asset to ship).
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Sora:wght@700;800;900&display=swap');
:root{--navy:#071a44;--navy2:#002b73;--blue:#0866ff;--muted:#40527a;--line:rgba(10,42,90,.13)}
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1920px;font-family:Inter,system-ui,sans-serif;color:var(--navy)}
.card{position:relative;width:1080px;height:1920px;overflow:hidden;background:radial-gradient(circle at 46% 38%,rgba(255,255,255,.95) 0 26%,transparent 60%),linear-gradient(135deg,#fff 0%,#f8fbff 58%,#fff 100%)}
.wm{position:absolute;right:40px;top:430px;font-family:Sora;font-weight:900;font-size:760px;line-height:1;letter-spacing:-60px;color:rgba(6,35,84,.045)}
.corner{position:absolute;width:240px;height:240px;background:linear-gradient(135deg,var(--navy),var(--navy2));border:5px solid var(--blue);border-radius:32px}
.corner.tr{top:-120px;right:-120px;transform:rotate(30deg)}.corner.bl{bottom:-128px;left:-128px;transform:rotate(63deg)}
.dots{position:absolute;display:grid;grid-template-columns:repeat(6,9px);gap:18px;opacity:.4}.dots.t{top:42px;left:42px}.dots.b{right:46px;bottom:300px}
.dots span{width:9px;height:9px;border-radius:50%;background:#6b8fca;display:block}
.hd{position:absolute;top:88px;left:80px;right:80px;display:flex;align-items:center;gap:20px}
.hd .mark{width:74px;height:74px;border-radius:16px;background:linear-gradient(135deg,var(--navy),var(--navy2));display:grid;place-items:center;color:#fff;font-family:Sora;font-weight:900;font-size:44px}
.hd .bw{font-family:Sora;font-weight:900;font-size:36px;letter-spacing:-1px;line-height:1}.hd .bw b{color:var(--blue)}
.hd .sub{font-size:15px;font-weight:800;letter-spacing:3px;margin-top:8px;text-transform:uppercase}
.body{position:absolute;left:80px;right:80px;top:300px;bottom:280px;display:flex;flex-direction:column}
.ft{position:absolute;left:60px;right:60px;bottom:46px;text-align:center;font-size:24px;font-style:italic;opacity:.85}
.bar{position:absolute;left:0;bottom:0;height:12px;background:var(--blue)}
.tag{display:inline-flex;align-items:center;gap:12px;align-self:flex-start;background:var(--blue);color:#fff;font-weight:900;font-size:26px;letter-spacing:3px;padding:14px 26px;border-radius:999px;text-transform:uppercase}
.dot{width:14px;height:14px;border-radius:50%;background:#fff;display:inline-block}
.hook{font-family:Sora;font-weight:900;font-size:96px;line-height:1.04;letter-spacing:-3px;margin-top:60px}
.hooksub{font-size:40px;font-weight:700;color:var(--muted);margin-top:40px;line-height:1.3}
.ledger{margin-top:auto;align-self:flex-start;display:inline-flex;align-items:center;gap:14px;background:#fff;border:2px solid var(--line);border-radius:999px;padding:16px 32px;font-weight:800;font-size:34px;box-shadow:0 8px 22px rgba(8,42,96,.08)}
.ledger i{width:15px;height:15px;border-radius:50%;background:var(--blue);font-style:normal}
.mh{display:flex;align-items:center;justify-content:center;gap:34px;margin-top:20px}
.mh img{width:150px;height:100px;object-fit:cover;border-radius:14px;box-shadow:0 12px 30px rgba(8,42,96,.2)}
.mh .vs{font-family:Sora;font-weight:900;font-size:48px;color:var(--blue)}
.mhname{text-align:center;font-size:34px;font-weight:800;margin-top:18px}
.lab{font-weight:900;font-size:32px;letter-spacing:5px;color:var(--blue);text-transform:uppercase;margin-top:60px}
.fac{margin-top:36px;display:flex;flex-direction:column;gap:26px}
.frow{display:flex;align-items:center;gap:24px;background:#fff;border:3px solid var(--line);border-radius:20px;padding:30px 32px;box-shadow:0 8px 20px rgba(8,42,96,.07)}
.frow.hot{border-color:var(--blue);background:linear-gradient(90deg,rgba(8,102,255,.06),#fff)}
.frow .b{width:20px;height:20px;border-radius:50%;background:var(--blue);flex:0 0 20px}
.frow .t{font-size:40px;font-weight:700;line-height:1.2}
.vw{margin-top:30px;text-align:center}.vlab{font-weight:900;font-size:34px;letter-spacing:6px;color:var(--blue);text-transform:uppercase}
.vmain{font-family:Sora;font-weight:900;font-size:104px;line-height:1.02;letter-spacing:-2px;margin-top:30px}
.vconf{margin-top:40px;font-family:Sora;font-weight:900;font-size:150px;line-height:1;color:var(--blue)}
.vsub{font-size:38px;font-weight:800;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-top:6px}
.cta{margin-top:auto;background:var(--blue);color:#fff;border-radius:22px;padding:34px 36px;text-align:center;font-weight:900;font-size:44px;line-height:1.25}
"""

CHROME = (
    '<div class="wm">A</div><div class="corner tr"></div><div class="corner bl"></div>'
    '<div class="dots t">' + "<span></span>" * 12 + '</div>'
    '<div class="dots b">' + "<span></span>" * 12 + '</div>'
    '<div class="hd"><div class="mark">A</div><div><div class="bw">Build With <b>Abdallah</b></div>'
    '<div class="sub">The Pitch Agent · AI Football Analytics</div></div></div>'
    '<div class="ft">The Pitch Agent by BuildWithAbdallah · Independent analytics · Not affiliated with FIFA</div>'
)

_SHOT_JS = """
import { createRequire } from "module";
const require = createRequire("%s/node_modules/");
const { chromium } = require("playwright");
import { writeFileSync } from "fs";
const [,, inHtml, outPng] = process.argv;
const b = await chromium.launch({ headless: true, args:["--no-sandbox","--disable-gpu","--disable-dev-shm-usage"] });
const p = await b.newPage({ viewport: { width:1080, height:1920 } });
await p.goto("file://"+inHtml, { waitUntil:"networkidle" });
await p.waitForTimeout(1200);
const cdp = await p.context().newCDPSession(p);
const s = await cdp.send("Page.captureScreenshot", { format:"png", fromSurface:false, captureBeyondViewport:false });
writeFileSync(outPng, Buffer.from(s.data,"base64"));
await b.close();
""" % _ROOT


def _page(body: str, bar_pct: int) -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head>"
            f"<body><div class='card'>{CHROME}<div class='body'>{body}</div>"
            f"<div class='bar' style='width:{bar_pct}%'></div></div></body></html>")


def build_frames_html(data: dict, variant: str | None = None) -> dict[str, str]:
    """Return {frame_name: html} for the 3 key frames — pure, testable."""
    vid, cfg = sm.select_template(variant)
    meta = sm.generate_metadata(data, vid)
    h, a = data["home"], data["away"]
    leader = data.get("leader") or h
    verdict = data.get("verdict", f"{leader} to win")
    conf = data.get("confidence", "")
    hf, af = _flag_uri(h), _flag_uri(a)

    hook = _page(
        f'<span class="tag"><span class="dot"></span>{sm.TOP_CHIP}</span>'
        f'<div class="hook">{meta["hook"]}</div>'
        f'<div class="hooksub">{meta["subheadline"]}</div>'
        f'<div class="ledger"><i></i>{meta["credibility_chip"]}</div>', 10)

    factor_label = cfg["factor_label"].format(leader=leader, underdog=sm._underdog(data))
    rows = ""
    for i, f in enumerate(data.get("factors", [])[:3]):
        hot = " hot" if (cfg.get("highlight_factor") and i == len(data.get("factors", [])[:3]) - 1) else ""
        rows += f'<div class="frow{hot}"><div class="b"></div><div class="t">{f}</div></div>'
    matchup = (f'<div class="mh"><div><img src="{hf}"><div class="mhname">{h}</div></div>'
               f'<div class="vs">VS</div><div><img src="{af}"><div class="mhname">{a}</div></div></div>')
    factors = _page(matchup + f'<div class="lab">{factor_label}</div><div class="fac">{rows}</div>', 55)

    verdict_html = _page(
        '<div class="vw"><div class="vlab">Model Verdict</div>'
        f'<div class="vmain">{verdict}</div>'
        f'<div class="vconf">{conf}%</div><div class="vsub">model win probability</div></div>'
        f'<div class="cta">{meta["cta_text"]}</div>', 96)

    return {"hook": hook, "factors": factors, "verdict": verdict_html}


def render_frames(data: dict, variant: str | None, outdir: Path) -> list[Path]:
    """Render the 3 frames to PNG. Returns the written paths (skips on failure)."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    shot = outdir / "_shot.mjs"
    shot.write_text(_SHOT_JS)
    node = "/home/linuxbrew/.linuxbrew/bin/node"
    node = node if Path(node).exists() else "node"
    written = []
    for name, html in build_frames_html(data, variant).items():
        hp = outdir / f"{name}.html"
        pp = outdir / f"{name}.png"
        hp.write_text(html)
        subprocess.run([node, str(shot), str(hp), str(pp)], capture_output=True, text=True)
        if pp.exists():
            written.append(pp)
    return written
