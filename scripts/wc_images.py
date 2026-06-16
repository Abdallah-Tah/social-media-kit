#!/usr/bin/env python3
"""Copyright-safe image sourcing for World Cup videos.

One place that returns LOCAL image/video paths (copied into remotion/public/)
plus attribution credits. Sources, in safety order:
  - flag(team)        flagcdn.com (free)
  - atmosphere(query) Pexels b-roll via gen_atmosphere (licensed; no players/logos)
  - commons_photo(q)  Wikimedia Commons, FREE licenses only (CC0/PD/CC BY/CC BY-SA),
                      with attribution. Never NC/ND/non-free.
  - ai_graphic(p)     FAL/Gemini original graphic (fallback)
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))

PUBLIC = KIT / "remotion" / "public"
CACHE = KIT / "content" / "assets" / "wc_image_cache"
UA = {"User-Agent": "BuildWithAbdallah-WorldCup/1.0 (contact: skulldark2011@gmail.com)"}

# team name -> ISO-3166 alpha-2 for flagcdn (England/Scotland use GB subdivisions)
from football_prediction_shorts import FLAG  # noqa: E402


def _ensure_dirs() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)


def flag(team: str, dest_name: str) -> Path | None:
    """Download a team flag into remotion/public/<dest_name>. Returns path/None."""
    _ensure_dirs()
    code = FLAG.get(team)
    if not code:
        return None
    dest = PUBLIC / dest_name
    try:
        req = urllib.request.Request(f"https://flagcdn.com/w640/{code}.png", headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            dest.write_bytes(r.read())
        return dest if dest.stat().st_size > 0 else None
    except Exception as exc:  # noqa: BLE001
        print(f"[wc-images] flag {team} failed: {exc}", file=sys.stderr)
        return None


def atmosphere(query: str | None = None, duration: float = 8.0,
               dest_name: str = "atmosphere.mp4") -> Path | None:
    """Pexels football-atmosphere b-roll (stadium/crowd, no players/logos)."""
    _ensure_dirs()
    try:
        import gen_atmosphere
        out = PUBLIC / dest_name
        gen_atmosphere.fetch_atmosphere(query=query, out_path=str(out), duration=duration)
        return out if out.exists() and out.stat().st_size > 0 else None
    except Exception as exc:  # noqa: BLE001
        print(f"[wc-images] atmosphere failed: {exc}", file=sys.stderr)
        return None


# --- Wikimedia Commons (free licenses only) ---------------------------------

_ALLOWED_RE = re.compile(r"^(cc0|public domain|cc[\s-]?by)", re.I)


def _license_ok(short: str) -> bool:
    if not short:
        return False
    s = short.strip().lower()
    if "nc" in s.replace("inc", "") or "nd" in s.replace("and", "") or "fair use" in s or "non-free" in s:
        # reject NonCommercial / NoDerivatives / fair-use / non-free
        if re.search(r"\bnc\b|\bnd\b|non[- ]?commercial|no[- ]?deriv|fair use|non-?free", s):
            return False
    return bool(_ALLOWED_RE.match(s))


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", _html.unescape(s or ""))).strip()


def commons_photo(query: str, dest_name: str, width: int = 1080) -> tuple[Path | None, str | None]:
    """Fetch a FREE-licensed Wikimedia Commons image for *query*.

    Returns (local_path, credit) or (None, None). credit = "Author / License (Wikimedia)".
    Only CC0 / public-domain / CC BY / CC BY-SA images are accepted (no NC/ND/non-free).
    """
    _ensure_dirs()
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": "12",
        "prop": "imageinfo", "iiprop": "url|extmetadata|mime",
        "iiurlwidth": str(width),
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        print(f"[wc-images] commons query failed: {exc}", file=sys.stderr)
        return None, None

    pages = (data.get("query", {}) or {}).get("pages", {}) or {}
    # search order is unstable across dict; sort by index
    for page in sorted(pages.values(), key=lambda p: p.get("index", 999)):
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if mime not in ("image/jpeg", "image/png"):
            continue
        meta = info.get("extmetadata", {}) or {}
        lic = (meta.get("LicenseShortName", {}) or {}).get("value", "")
        if not _license_ok(lic):
            continue
        thumb = info.get("thumburl") or info.get("url")
        if not thumb:
            continue
        author = _strip_html((meta.get("Artist", {}) or {}).get("value", "")) or "Wikimedia Commons"
        author = author[:60]
        dest = PUBLIC / dest_name
        try:
            req = urllib.request.Request(thumb, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                dest.write_bytes(r.read())
            if dest.stat().st_size <= 0:
                continue
        except Exception:
            continue
        credit = f"{author} / {lic} (Wikimedia Commons)"
        print(f"[wc-images] commons: {query} -> {credit}")
        return dest, credit
    print(f"[wc-images] commons: no free image for '{query}'")
    return None, None


def ai_graphic(prompt: str, dest_name: str) -> Path | None:
    """Original AI graphic (FAL flux) as a fallback. Returns path/None."""
    _ensure_dirs()
    try:
        import image_generator
        out = PUBLIC / dest_name
        res = image_generator.generate_cover(prompt[:70], prompt=prompt,
                                             out_path=str(out), provider="fal")
        p = (res or {}).get("path") if isinstance(res, dict) else res
        return Path(p) if p and Path(p).exists() else None
    except Exception as exc:  # noqa: BLE001
        print(f"[wc-images] ai_graphic failed: {exc}", file=sys.stderr)
        return None


if __name__ == "__main__":
    # smoke test
    from agent.config import load_env
    load_env()
    print("flag:", flag("Iran", "test_flag.png"))
    print("atmosphere:", atmosphere("football stadium night", 6))
    print("commons:", commons_photo("Lionel Messi", "test_commons.jpg"))
