# World Cup Survival Lab

World Cup Survival Lab is a Build With Abdallah / The Pitch Agent short-form pillar for explaining qualification math in simple English.

## Editorial Rules

- Educational football analytics only.
- No betting, gambling, odds, sportsbook, or fake-certainty language.
- No FIFA footage, match footage, copyrighted clips, or tournament logos.
- Use original tables, cards, brackets, animations, and voiceover.
- Keep the tone simple: qualification paths, table math, goal difference, goals scored, discipline tiebreakers, and bracket consequences.

## First Format

Title: `The 2026 World Cup Has a Hidden Table`

Hook: `Your team can finish 3rd and still survive.`

Structure:

- 0-3 sec: hook
- 3-8 sec: 12 group cards
- 8-15 sec: top two advance automatically
- 15-23 sec: hidden third-place table
- 23-29 sec: danger examples
- 29-32 sec: CTA

## Files

- `content/survival_lab/topics.json`
- `scripts/worldcup_survival_lab.py`
- `scripts/worldcup_survival_thumbnail.py`
- `remotion/src/SurvivalLab.tsx`

## Commands

Render and send review:

```bash
/usr/bin/python3 scripts/worldcup_survival_lab.py --topic hidden-third-place-table --review
```

Render only:

```bash
/usr/bin/python3 scripts/worldcup_survival_lab.py --topic hidden-third-place-table
```

Publish after approval:

```bash
/usr/bin/python3 scripts/worldcup_survival_lab.py --topic hidden-third-place-table --publish --privacy public
```

## Next Templates

- Can They Still Qualify?
- Third-Place Danger Table
- Goal Difference Swing
- Yellow Card Danger Index
- Bracket Path Finder
- Group Chaos Meter
