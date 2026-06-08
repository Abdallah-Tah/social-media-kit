// Render HTML templates to retina-quality PNG screenshots using Playwright.
// Usage: node render_card.mjs <input.html> <output.png> [width] [height]

import path from "node:path";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";

function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_DIR,
    path.resolve("node_modules"),
  ].filter(Boolean);
  for (const dir of candidates) {
    try {
      const require = createRequire(dir.endsWith("/") ? dir : dir + "/");
      return require("playwright");
    } catch { /* try next */ }
  }
  throw new Error(
    "Could not resolve 'playwright'. Install it: npm install playwright"
  );
}

const [, , inHtml, outPng, wArg, hArg] = process.argv;
if (!inHtml || !outPng) {
  console.error("Usage: node render_card.mjs <input.html> <output.png> [width] [height]");
  process.exit(1);
}
if (!existsSync(inHtml)) {
  console.error(`Input HTML not found: ${inHtml}`);
  process.exit(1);
}

const width = parseInt(wArg || "1600", 10);
const height = parseInt(hArg || "1000", 10);

const { chromium } = loadPlaywright();
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});
try {
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 2, // 1600x1000@2x normal mode for sharp PNG text
  });
  await page.goto("file://" + path.resolve(inHtml), { waitUntil: "networkidle" });
  await page.waitForTimeout(400); // Let web fonts settle
  await page.screenshot({ path: path.resolve(outPng) });
  console.log(`Rendered ${width}x${height}@2x -> ${outPng}`);
} finally {
  await browser.close();
}
