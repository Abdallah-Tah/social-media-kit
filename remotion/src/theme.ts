// Compatibility shim — THEME now DERIVES from the single source of truth
// (brand/tokens.ts BRAND). Do not edit palette values here; change them in
// remotion/src/brand/tokens.ts. Kept so existing comps importing THEME/FONT
// keep working while they migrate onto BrandFrame.
import { BRAND, CANVAS } from "./brand/tokens";

export const THEME = {
  bg: BRAND.bg,
  bgGrad: BRAND.bgGradient,
  ink: BRAND.text,
  navy: BRAND.navy,
  navy2: BRAND.navy2,
  blue: BRAND.blue,
  muted: BRAND.muted,
  line: BRAND.line,
  soft: BRAND.soft,
  red: BRAND.red,
  green: BRAND.green,
  // Remotion-only tints (no card equivalent) — kept for the existing panels
  redSoft: "#fff5f5",
  blueSoft: "#eef4ff",
};

export const FONT = BRAND.font;

export const W = CANVAS.W;
export const H = CANVAS.H;
export const FPS = 30;
