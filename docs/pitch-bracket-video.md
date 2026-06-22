# Animated Bracket Prediction Video

The `pitch-bracket-video` command creates an original Build With Abdallah / The Pitch Agent animated knockout bracket video. It uses local HTML, CSS animations, Playwright frame capture, and ffmpeg. It does not use FIFA footage, official logos, copyrighted trophy images, music, or remote assets.

## Usage

Dry run validation and HTML generation:

```bash
smkit pitch-bracket-video --input data/sample_bracket.json --out storage/videos/bracket_prediction.mp4 --dry-run
```

Render the full 1080x1920 MP4 and PNG preview:

```bash
smkit pitch-bracket-video --input data/sample_bracket.json --out storage/videos/bracket_prediction.mp4
```

The default style is `viral-bracket-v2`. V1 remains available for comparison:

```bash
smkit pitch-bracket-video --input data/sample_bracket.json --out storage/videos/bracket_prediction.mp4 --style classic-v1
```

Optional local audio can be muxed into the MP4:

```bash
smkit pitch-bracket-video --input data/sample_bracket.json --out storage/videos/bracket_prediction.mp4 --audio content/audio/bracket-bed.mp3
```

Send a Telegram review packet:

```bash
smkit pitch-bracket-video --input data/sample_bracket.json --telegram-review
```

## Payload Format

The payload is JSON-compatible and must include:

- `title`
- `brand`
- `subtitle`
- `site`
- `disclaimer`, which must include `not betting advice`
- `rounds[0].matches`, exactly 16 Round of 32 matches
- `champion.name`

Later rounds may be empty. When they are empty, the renderer creates a deterministic bracket path from prior winners and forces the declared champion through its side of the bracket.

## Asset Requirements

Flags are optional local files only. A `flag` value can point to:

- an absolute local path
- a path relative to the repo root
- `content/assets/<flag>`
- `content/assets/flags/<flag>`

If the file is missing, V2 first tries a flag emoji, then a stylized local CSS flag circle, then a branded gradient code circle. The trophy is an inline original SVG, so no trophy asset is required. The champion reveal uses a generic card, not a player image.

## Safety Validation

The renderer rejects betting, gambling, and fake-certainty language, including:

`bet`, `betting`, `gamble`, `wager`, `odds`, `parlay`, `sportsbook`, `bookmaker`, `guaranteed`, `lock`, `sure win`, `risk-free`, and `bet on`.

Every output includes:

`Educational prediction model — not betting advice`

## Headless / Raspberry Pi Notes

This pipeline records deterministic PNG frames instead of realtime screen capture. It is slower, but stable on headless machines.

Requirements:

- Node with Playwright installed in the repo or available through `PLAYWRIGHT_DIR`
- Chromium dependencies available for Playwright
- `/usr/bin/ffmpeg` or `ffmpeg` on `PATH`
- No network access required for rendering

If Playwright cannot launch in a sandboxed environment, rerun the render outside the sandbox or on the target host service account.
