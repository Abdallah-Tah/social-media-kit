// Render an animated HTML template to a deterministic PNG frame sequence.
// Seeks all CSS animations/transitions to exact timestamps and screenshots
// each frame — smooth output even on a slow Pi (no realtime capture).
// Usage: node record_frames.mjs <input.html> <outdir> <seconds> <fps> [w] [h]

import path from "node:path";
import { existsSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";

function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_DIR, path.resolve("node_modules")].filter(Boolean);
  for (const dir of candidates) {
    try {
      const require = createRequire(dir.endsWith("/") ? dir : dir + "/");
      return require("playwright");
    } catch { /* try next */ }
  }
  throw new Error("Could not resolve 'playwright'. Install it: npm install playwright");
}

const [, , inHtml, outDir, secArg, fpsArg, wArg, hArg] = process.argv;
if (!inHtml || !outDir || !secArg) {
  console.error("Usage: node record_frames.mjs <input.html> <outdir> <seconds> <fps> [w] [h]");
  process.exit(1);
}
if (!existsSync(inHtml)) {
  console.error(`Input HTML not found: ${inHtml}`);
  process.exit(1);
}
mkdirSync(outDir, { recursive: true });

const seconds = parseFloat(secArg);
const fps = parseInt(fpsArg || "20", 10);
const width = parseInt(wArg || "1080", 10);
const height = parseInt(hArg || "1920", 10);
const frames = Math.max(1, Math.round(seconds * fps));

const { chromium } = loadPlaywright();
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});
try {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.goto("file://" + path.resolve(inHtml), { waitUntil: "networkidle" });
  await page.waitForTimeout(1200); // web fonts

  // Pause every animation so we can scrub them deterministically.
  await page.evaluate(() => {
    for (const a of document.getAnimations()) a.pause();
  });

  for (let i = 0; i < frames; i++) {
    const t = (i / fps) * 1000; // ms
    await page.evaluate((ms) => {
      for (const a of document.getAnimations()) a.currentTime = ms;
    }, t);
    const name = path.join(outDir, `f_${String(i).padStart(5, "0")}.png`);
    await page.screenshot({ path: name });
  }
  console.log(`Rendered ${frames} frames @ ${fps}fps -> ${outDir}`);
} finally {
  await browser.close();
}
