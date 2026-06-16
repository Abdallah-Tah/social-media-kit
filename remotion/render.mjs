// Render a Build With Abdallah animated Short from a plan JSON (+ optional
// ElevenLabs voiceover). Usage:
//   node render.mjs --plan <plan.json> --out <out.mp4> [--audio <voiceover.mp3>]
import { bundle } from "@remotion/bundler";
import { selectComposition, renderMedia } from "@remotion/renderer";
import { execFileSync } from "node:child_process";
import { existsSync, copyFileSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const get = (k) => {
  const i = args.indexOf(k);
  return i >= 0 ? args[i + 1] : undefined;
};
const planPath = get("--plan");
const propsPath = get("--props");
const compId = get("--id") || "Short";
const outPath = get("--out") || path.join(__dirname, "out.mp4");
let audioPath = get("--audio");

// Two modes: --props <json> renders any composition by --id with those props;
// --plan <json> builds the article "Short" composition props.
let inputProps;
let durations;
let baseDir;
if (propsPath) {
  inputProps = JSON.parse(readFileSync(propsPath, "utf8"));
  durations = inputProps.durations || [];
  baseDir = path.dirname(propsPath);
} else if (planPath) {
  const plan = JSON.parse(readFileSync(planPath, "utf8"));
  const scenes = plan.scenes || [];
  durations = scenes.map((s) => Number(s.duration_seconds) || 4);
  inputProps = {
    scenes,
    durations,
    captions: plan.captions || [],
    url: (plan.source && plan.source.url) || "buildwithabdallah.com",
  };
  baseDir = path.dirname(planPath);
} else {
  console.error("missing --plan or --props");
  process.exit(2);
}

if (!audioPath) {
  const guess = path.join(baseDir, "voiceover.mp3");
  if (existsSync(guess)) audioPath = guess;
}

const FPS = 30;
const ffprobe = "/usr/bin/ffprobe";
const probeDur = (p) => {
  try {
    const out = execFileSync(ffprobe, ["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p], { encoding: "utf8" });
    return parseFloat(out.trim());
  } catch {
    return 0;
  }
};

let hasAudio = false;
const publicDir = path.join(__dirname, "public");
mkdirSync(publicDir, { recursive: true });
const audioFile = "voiceover.mp3";
if (audioPath && existsSync(audioPath)) {
  copyFileSync(audioPath, path.join(publicDir, audioFile));
  hasAudio = true;
  const aDur = probeDur(audioPath);
  const sceneSum = durations.reduce((a, b) => a + b, 0);
  // Stretch scene timing to cover the full narration (+0.6s tail), keeping
  // relative pacing, so the detailed script is never cut off.
  if (aDur > 0 && sceneSum > 0) {
    const target = aDur + 0.6;
    if (target > sceneSum) {
      const k = target / sceneSum;
      durations = durations.map((d) => Math.round(d * k * 100) / 100);
    }
  }
  console.log(`[remotion] audio ${aDur.toFixed(1)}s -> scenes ${durations.reduce((a, b) => a + b, 0).toFixed(1)}s`);
}

inputProps = { ...inputProps, durations, hasAudio, audioFile };

console.log("[remotion] bundling…");
const serveUrl = await bundle({
  entryPoint: path.join(__dirname, "src", "index.ts"),
  publicDir,
});

const composition = await selectComposition({ serveUrl, id: compId, inputProps });

console.log(`[remotion] rendering ${composition.durationInFrames} frames -> ${outPath}`);
await renderMedia({
  serveUrl,
  composition,
  codec: "h264",
  outputLocation: outPath,
  inputProps,
  imageFormat: "jpeg",
  jpegQuality: 90,
  concurrency: 2,
  browserExecutable: existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined,
  chromiumOptions: { gl: "swiftshader" },
  timeoutInMilliseconds: 120000,
});
console.log("✅ Remotion render complete:", outPath);
