import React from "react";
import {
  AbsoluteFill, Audio, Series, staticFile,
  interpolate, spring, useCurrentFrame, useVideoConfig,
} from "remotion";
import { BRAND, SAFE } from "./brand/tokens";
import { BrandFrame } from "./brand/BrandFrame";

export type DataDiveProps = {
  title: string;
  titleLines?: string[];
  hook: string;
  beats: string[];
  statCards: { label: string; value: string }[];
  finalCall: string;
  cta: string;
  durations: number[];
  hasAudio: boolean;
  audioFile: string;
};

const useIn = (delay = 0, damping = 13) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - delay, fps, config: { damping, mass: 0.7 } });
};

const TitleText: React.FC<{ children: React.ReactNode; size?: number }> = ({ children, size = 66 }) => (
  <div style={{ fontFamily: BRAND.font, fontWeight: 900, fontSize: size, lineHeight: 1.05, letterSpacing: 0, color: BRAND.navy }}>
    {children}
  </div>
);

const Badge: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ display: "inline-block", background: BRAND.blue, color: "#fff", borderRadius: 12, padding: "14px 22px", fontFamily: BRAND.font, fontWeight: 900, fontSize: 26, letterSpacing: 1 }}>
    {children}
  </div>
);

const titleLines = (p: DataDiveProps): string[] => {
  const lines = (p.titleLines || []).map((x) => String(x).trim()).filter(Boolean);
  if (lines.length > 0) return lines.slice(0, 3);
  const words = p.title.split(/\s+/).filter(Boolean);
  const out: string[] = [];
  let line = "";
  for (const word of words) {
    const trial = `${line} ${word}`.trim();
    if (trial.length <= 26) {
      line = trial;
    } else {
      if (line) out.push(line);
      line = word;
    }
  }
  if (line) out.push(line);
  return out.slice(0, 3);
};

const HeadlineBlock: React.FC<{ p: DataDiveProps }> = ({ p }) => {
  const lines = titleLines(p);
  const fontSize = lines.length >= 3 ? 62 : 70;
  return (
    <div style={{ fontFamily: BRAND.font, fontWeight: 900, fontSize, lineHeight: 1.08, letterSpacing: 0, color: BRAND.navy }}>
      {lines.map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </div>
  );
};

const BracketViz: React.FC<{ top?: number }> = ({ top = 930 }) => {
  const s = useIn(14, 12);
  const rows = [0, 1, 2, 3];
  return (
    <div style={{ position: "absolute", left: 90, right: 90, top, height: 630, opacity: s }}>
      {rows.map((r) => {
        const y = 34 + r * 128;
        return (
          <div key={r}>
            <div style={{ position: "absolute", left: 10, top: y, width: 230, height: 58, background: "#fff", border: `3px solid ${BRAND.line}`, borderRadius: 10 }} />
            <div style={{ position: "absolute", left: 10, top: y + 64, width: 230, height: 58, background: "#fff", border: `3px solid ${BRAND.line}`, borderRadius: 10 }} />
            <div style={{ position: "absolute", left: 240, top: y + 29, width: 70, height: 64, borderRight: `5px solid ${BRAND.blue}`, borderTop: `5px solid ${BRAND.blue}`, borderBottom: `5px solid ${BRAND.blue}` }} />
            <div style={{ position: "absolute", left: 310, top: y + 61, width: 130, height: 5, background: BRAND.blue }} />
            <div style={{ position: "absolute", left: 440, top: y + 31, width: 210, height: 62, background: "#fff", border: `3px solid ${BRAND.line}`, borderRadius: 10 }} />
          </div>
        );
      })}
      <div style={{ position: "absolute", right: 10, top: 226, width: 250, height: 110, borderRadius: 18, background: BRAND.navy, color: "#fff", display: "grid", placeItems: "center", fontFamily: BRAND.font, fontWeight: 900, fontSize: 34, boxShadow: "0 16px 32px rgba(8,42,96,.2)" }}>CHAMPION?</div>
    </div>
  );
};

const ProbabilityGrid: React.FC<{ cards: { label: string; value: string }[] }> = ({ cards }) => (
  <div style={{ position: "absolute", top: 700, left: 90, right: 90, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 26 }}>
    {cards.slice(0, 4).map((card, i) => {
      const s = useIn(10 + i * 8, 13);
      return (
        <div key={i} style={{ background: "#fff", border: `3px solid ${BRAND.line}`, borderRadius: 18, padding: "32px 26px", boxShadow: "0 12px 28px rgba(8,42,96,.10)", opacity: s, transform: `translateY(${interpolate(s, [0, 1], [30, 0])}px)` }}>
          <div style={{ fontFamily: BRAND.font, fontSize: 27, fontWeight: 800, color: BRAND.muted, textTransform: "uppercase" }}>{card.label}</div>
          <div style={{ marginTop: 16, fontFamily: BRAND.font, fontSize: 54, fontWeight: 900, color: BRAND.blue }}>{card.value}</div>
        </div>
      );
    })}
  </div>
);

const Intro: React.FC<{ p: DataDiveProps }> = ({ p }) => {
  const s = useIn(8, 11);
  return (
    <BrandFrame pageBadge="DATA">
      <div style={{ position: "absolute", top: 284, left: SAFE.side, right: SAFE.side, textAlign: "center", opacity: s, transform: `translateY(${interpolate(s, [0, 1], [26, 0])}px)` }}>
        <Badge>WORLD CUP DATA LAB</Badge>
      </div>
      <div style={{ position: "absolute", top: 382, left: SAFE.side, right: SAFE.side, textAlign: "center", opacity: s, transform: `translateY(${interpolate(s, [0, 1], [28, 0])}px)` }}>
        <HeadlineBlock p={p} />
      </div>
      <div style={{ position: "absolute", top: 648, left: SAFE.side + 18, right: SAFE.side + 18, textAlign: "center", opacity: interpolate(useIn(18), [0, 1], [0, 1]) }}>
        <div style={{ fontFamily: BRAND.font, fontSize: 36, fontWeight: 750, color: BRAND.muted, lineHeight: 1.26 }}>
          {p.hook}
        </div>
      </div>
      <BracketViz top={930} />
    </BrandFrame>
  );
};

const Method: React.FC<{ p: DataDiveProps }> = ({ p }) => (
  <BrandFrame pageBadge="MODEL">
    <div style={{ position: "absolute", top: 320, left: SAFE.side, right: SAFE.side }}>
      <Badge>10,000 SIMULATIONS</Badge>
      <div style={{ marginTop: 40 }}><TitleText>What the model is testing</TitleText></div>
      <div style={{ marginTop: 46, display: "flex", flexDirection: "column", gap: 24 }}>
        {p.beats.slice(0, 3).map((b, i) => {
          const s = useIn(10 + i * 10, 12);
          return (
            <div key={i} style={{ background: "#fff", border: `3px solid ${BRAND.line}`, borderRadius: 18, padding: "26px 30px", fontFamily: BRAND.font, fontSize: 37, fontWeight: 800, lineHeight: 1.24, color: BRAND.text, opacity: s, transform: `translateX(${interpolate(s, [0, 1], [-36, 0])}px)` }}>
              {b}
            </div>
          );
        })}
      </div>
    </div>
  </BrandFrame>
);

const Numbers: React.FC<{ p: DataDiveProps }> = ({ p }) => (
  <BrandFrame pageBadge="CHAOS">
    <div style={{ position: "absolute", top: 320, left: SAFE.side, right: SAFE.side, textAlign: "center" }}>
      <Badge>WHERE THE BRACKET BREAKS</Badge>
      <div style={{ marginTop: 42 }}><TitleText>Upsets create the path</TitleText></div>
    </div>
    <ProbabilityGrid cards={p.statCards} />
  </BrandFrame>
);

const Final: React.FC<{ p: DataDiveProps }> = ({ p }) => {
  const s = useIn(10, 11);
  return (
    <BrandFrame pageBadge="CALL">
      <div style={{ position: "absolute", top: 430, left: SAFE.side, right: SAFE.side, textAlign: "center" }}>
        <Badge>FINAL MODEL TAKE</Badge>
        <div style={{ marginTop: 54, opacity: s, transform: `scale(${interpolate(s, [0, 1], [0.88, 1])})` }}><TitleText size={68}>{p.finalCall}</TitleText></div>
        <div style={{ marginTop: 58, background: BRAND.blue, color: "#fff", borderRadius: 18, padding: "26px 34px", fontFamily: BRAND.font, fontWeight: 900, fontSize: 40 }}>{p.cta}</div>
        <div style={{ marginTop: 24, fontFamily: BRAND.font, fontSize: 26, fontWeight: 700, color: BRAND.muted }}>Independent simulation. Not affiliated with FIFA.</div>
      </div>
    </BrandFrame>
  );
};

export const DataDive: React.FC<DataDiveProps> = (p) => {
  const FPS = 30;
  const scenes = [<Intro p={p} />, <Method p={p} />, <Numbers p={p} />, <Final p={p} />];
  const d = (p.durations && p.durations.length === scenes.length) ? p.durations : [6, 8, 7, 6];
  const frames = d.map((x) => Math.max(1, Math.round(x * FPS)));
  return (
    <AbsoluteFill style={{ backgroundColor: BRAND.bg }}>
      <Series>
        {scenes.map((scene, i) => <Series.Sequence key={i} durationInFrames={frames[i]}>{scene}</Series.Sequence>)}
      </Series>
      {p.hasAudio ? <Audio src={staticFile(p.audioFile)} /> : null}
    </AbsoluteFill>
  );
};
