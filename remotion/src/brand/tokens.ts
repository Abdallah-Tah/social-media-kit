// ============================================================================
// PITCH AGENT BRAND TOKENS — single source of truth for all Remotion video
// pillars. Values pulled VERBATIM from the canonical brand source
// templates/shorts/match_recap_wide.html :root (the social/prediction card).
// Do not invent values here; if the brand changes, change it in ONE place.
// ============================================================================

export const BRAND = {
  // palette (match_recap_wide.html :root)
  navy: "#071a44",
  navy2: "#002b73",
  blue: "#0866ff",
  text: "#081b44",
  muted: "#40527a",
  line: "rgba(10, 42, 90, .13)",
  soft: "rgba(8, 42, 96, .08)",
  bg: "#f8fbff",
  green: "#16a34a",
  red: "#dc2626",
  dot: "#6b8fca",
  watermark: "rgba(6, 35, 84, .045)",

  // background gradient (from .social-card)
  bgGradient:
    "radial-gradient(circle at 45% 38%, rgba(255,255,255,.95) 0 26%, transparent 60%), " +
    "linear-gradient(135deg, #ffffff 0%, #f8fbff 58%, #ffffff 100%)",

  // typography
  font: 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Arial, sans-serif',

  // lockup + tagline + footer (FOOTBALL — never the software/automation one)
  brandName: ["Build With ", "Abdallah"] as const,
  tagline: "The Pitch Agent · Independent Football Analytics",
  footer: "The Pitch Agent by BuildWithAbdallah · Independent analytics · Not affiliated with FIFA",

  // real Build With Abdallah logo (committed master remotion/assets/brand_logo.jpg,
  // copied into remotion/public/ at render time by render.mjs if missing).
  logoFile: "brand_logo.jpg",
} as const;

// 9:16 canvas
export const CANVAS = { W: 1080, H: 1920 } as const;

// Shorts safe area: keep captions + key text clear of the bottom 15% (YouTube
// UI) and the top header band.
export const SAFE = {
  top: 250,        // below the header lockup
  bottomReserve: 288, // 15% of 1920 — Shorts UI / progress bar
  side: 70,
} as const;

// chrome specs (scaled from the 1200x628 card to 1080x1920)
export const CHROME = {
  cornerSize: 200,
  cornerRadius: 28,
  cornerBorder: 4,
  watermarkSize: 660,
  dotCols: 6,
  dotSize: 7,
  dotGap: 13,
  dotOpacity: 0.45,
} as const;
