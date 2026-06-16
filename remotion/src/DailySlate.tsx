import React from "react";
import {
  AbsoluteFill, Img, Audio, Series, OffthreadVideo, staticFile,
  interpolate, spring, useCurrentFrame, useVideoConfig,
} from "remotion";
import { THEME, FONT } from "./theme";

// ============================================================================
// "Today at the World Cup" — full-screen, image-rich daily slate Short.
// ============================================================================

export type Match = { home: string; away: string; homeFlag: string; awayFlag: string; time: string; lean: string };
export type Result = { label: string; prediction: string; correct: boolean | null };
export type DailyProps = {
  date: string;
  teamsToday: { name: string; flag: string }[];
  results: Result[];
  matches: Match[];
  headline: { home: string; away: string; homeFlag: string; awayFlag: string; scoreline: string; text: string; image?: string } | null;
  modelRecord: string;
  credits: string[];
  durations: number[];
  hasAudio: boolean;
  audioFile: string;
  atmosphere: string | null;
};

const safeTop = 96;
const useIn = (delay = 0, damping = 13) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - delay, fps, config: { damping, mass: 0.7 } });
};

const Corner: React.FC = () => (
  <>
    <div style={{ position: "absolute", top: 0, right: 0, width: 0, height: 0, borderTop: "230px solid #0b2a6b", borderLeft: "230px solid transparent", opacity: 0.9 }} />
    <div style={{ position: "absolute", top: 0, right: 0, width: 0, height: 0, borderTop: "145px solid " + THEME.blue, borderLeft: "145px solid transparent" }} />
    <div style={{ position: "absolute", bottom: 0, left: 0, width: 0, height: 0, borderBottom: "180px solid rgba(8,102,255,.10)", borderRight: "180px solid transparent" }} />
    <div style={{ position: "absolute", left: 70, bottom: 150, display: "grid", gridTemplateColumns: "repeat(6,16px)", gap: 12, opacity: 0.35 }}>
      {Array.from({ length: 24 }).map((_, i) => <div key={i} style={{ width: 8, height: 8, borderRadius: "50%", background: THEME.blue }} />)}
    </div>
  </>
);

const Branding: React.FC = () => (
  <div style={{ position: "absolute", top: safeTop, left: 80, right: 80, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: THEME.ink }}>Build With <span style={{ color: THEME.blue }}>Abdallah</span></div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 19, letterSpacing: 3, color: THEME.muted, marginTop: 6 }}>THE PITCH AGENT • INDEPENDENT FOOTBALL ANALYTICS</div>
    </div>
    <div style={{ width: 88, height: 88, borderRadius: 20, background: "#fff", border: `4px solid ${THEME.blue}`, display: "grid", placeItems: "center", fontFamily: FONT, fontWeight: 900, fontSize: 46, color: THEME.navy }}>A</div>
  </div>
);

const Footer: React.FC<{ credit?: string }> = ({ credit }) => (
  <div style={{ position: "absolute", bottom: 64, left: 0, right: 0, textAlign: "center", fontFamily: FONT, fontSize: credit ? 19 : 22, color: THEME.muted, opacity: 0.85, padding: "0 60px" }}>
    {credit ? credit : "The Pitch Agent by BuildWithAbdallah  |  Independent analytics  |  Not affiliated with FIFA"}
  </div>
);

const Label: React.FC<{ text: string; delay?: number }> = ({ text, delay = 0 }) => {
  const o = interpolate(useIn(delay), [0, 1], [0, 1]);
  return <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 30, letterSpacing: 6, color: THEME.blue, opacity: o }}>{text}</div>;
};

const Frame: React.FC<{ children: React.ReactNode; bg?: string | null; credit?: string }> = ({ children, bg, credit }) => (
  <AbsoluteFill style={{ background: THEME.bgGrad, fontFamily: FONT }}>
    {bg ? (
      <AbsoluteFill>
        <OffthreadVideo src={staticFile(bg)} muted loop style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        <AbsoluteFill style={{ background: "rgba(244,248,255,0.84)" }} />
      </AbsoluteFill>
    ) : null}
    <Corner />
    <Branding />
    {children}
    <Footer credit={credit} />
  </AbsoluteFill>
);

const FlagImg: React.FC<{ src: string; w?: number; h?: number }> = ({ src, w = 150, h = 100 }) => (
  <Img src={staticFile(src)} style={{ width: w, height: h, objectFit: "cover", borderRadius: 12, border: "3px solid #fff", boxShadow: "0 10px 24px rgba(8,42,96,.18)" }} />
);

// ---- Scene 1: intro --------------------------------------------------------
const Intro: React.FC<{ p: DailyProps }> = ({ p }) => {
  const t = useIn(6);
  return (
    <Frame bg={p.atmosphere}>
      <div style={{ position: "absolute", top: 430, left: 80, right: 80, textAlign: "center" }}>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 86, letterSpacing: -1, color: THEME.navy, lineHeight: 1.05, opacity: t, transform: `translateY(${interpolate(t, [0, 1], [40, 0])}px)` }}>TODAY AT THE<br />WORLD CUP</div>
        <div style={{ marginTop: 22, fontFamily: FONT, fontSize: 46, fontWeight: 700, color: THEME.blue, opacity: interpolate(useIn(16), [0, 1], [0, 1]) }}>{p.date}</div>
      </div>
      <div style={{ position: "absolute", bottom: 360, left: 80, right: 80, display: "flex", flexWrap: "wrap", gap: 18, justifyContent: "center" }}>
        {p.teamsToday.slice(0, 8).map((tm, i) => {
          const s = useIn(26 + i * 6, 12);
          return <div key={i} style={{ opacity: s, transform: `scale(${interpolate(s, [0, 1], [0.6, 1])})` }}><FlagImg src={tm.flag} w={132} h={88} /></div>;
        })}
      </div>
    </Frame>
  );
};

// ---- Scene 2: yesterday results -------------------------------------------
const Results: React.FC<{ p: DailyProps }> = ({ p }) => (
  <Frame>
    <div style={{ position: "absolute", top: 320, left: 80, right: 80 }}>
      <Label text="YESTERDAY · MODEL REPORT CARD" />
      <div style={{ marginTop: 44, display: "flex", flexDirection: "column", gap: 22 }}>
        {p.results.slice(0, 4).map((r, i) => {
          const s = useIn(12 + i * 12, 13);
          const col = r.correct === true ? "#1a9e5f" : r.correct === false ? THEME.red : THEME.muted;
          const mark = r.correct === true ? "✓" : r.correct === false ? "✗" : "—";
          return (
            <div key={i} style={{ background: "#fff", border: `3px solid ${THEME.line}`, borderRadius: 16, padding: "26px 30px", boxShadow: "0 8px 20px rgba(8,42,96,.07)", opacity: s, transform: `translateX(${interpolate(s, [0, 1], [-40, 0])}px)` }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 38, color: THEME.ink }}>{r.label}</div>
                <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 44, color: col }}>{mark}</div>
              </div>
              {r.prediction ? <div style={{ marginTop: 8, fontFamily: FONT, fontSize: 28, color: THEME.muted }}>{r.prediction}</div> : null}
            </div>
          );
        })}
      </div>
      {p.modelRecord ? (
        <div style={{ marginTop: 34, background: THEME.soft, borderLeft: `5px solid ${THEME.blue}`, borderRadius: "0 10px 10px 0", padding: "18px 24px", fontFamily: FONT, fontWeight: 700, fontSize: 30, color: THEME.navy, opacity: interpolate(useIn(60), [0, 1], [0, 1]) }}>{p.modelRecord}</div>
      ) : null}
    </div>
  </Frame>
);

// ---- Scene 3: today's matches ---------------------------------------------
const Today: React.FC<{ p: DailyProps }> = ({ p }) => (
  <Frame>
    <div style={{ position: "absolute", top: 300, left: 70, right: 70 }}>
      <Label text="TODAY'S MATCHES" />
      <div style={{ marginTop: 40, display: "flex", flexDirection: "column", gap: 24 }}>
        {p.matches.slice(0, 4).map((m, i) => {
          const s = useIn(12 + i * 13, 13);
          return (
            <div key={i} style={{ background: "#fff", border: `3px solid ${THEME.line}`, borderRadius: 18, padding: "22px 26px", boxShadow: "0 8px 20px rgba(8,42,96,.07)", opacity: s, transform: `translateY(${interpolate(s, [0, 1], [28, 0])}px)` }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <FlagImg src={m.homeFlag} w={84} h={56} />
                  <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 30, color: THEME.navy }}>vs</span>
                  <FlagImg src={m.awayFlag} w={84} h={56} />
                </div>
                <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 28, color: THEME.blue }}>{m.time}</div>
              </div>
              <div style={{ marginTop: 14, fontFamily: FONT, fontWeight: 800, fontSize: 34, color: THEME.ink }}>{m.home} vs {m.away}</div>
              {m.lean ? <div style={{ marginTop: 4, fontFamily: FONT, fontSize: 27, color: THEME.muted }}>{m.lean}</div> : null}
            </div>
          );
        })}
      </div>
    </div>
  </Frame>
);

// ---- Scene 4: headline call -----------------------------------------------
const Headline: React.FC<{ p: DailyProps }> = ({ p }) => {
  const h = p.headline;
  const a = useIn(8, 10);
  const f = useCurrentFrame();
  const pulse = 1 + Math.sin(f / 8) * 0.02;
  if (!h) return <Frame><div /></Frame>;
  return (
    <Frame>
      {h.image ? (
        <AbsoluteFill><Img src={staticFile(h.image)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /><AbsoluteFill style={{ background: "rgba(244,248,255,0.86)" }} /></AbsoluteFill>
      ) : null}
      <div style={{ position: "absolute", top: 380, left: 80, right: 80, textAlign: "center" }}>
        <Label text="MODEL'S CALL OF THE DAY" />
        <div style={{ marginTop: 50, display: "flex", alignItems: "center", justifyContent: "center", gap: 40 }}>
          <FlagImg src={h.homeFlag} w={190} h={126} />
          <span style={{ fontFamily: FONT, fontWeight: 900, fontSize: 46, color: THEME.navy }}>VS</span>
          <FlagImg src={h.awayFlag} w={190} h={126} />
        </div>
        <div style={{ marginTop: 44, fontFamily: FONT, fontWeight: 900, fontSize: 96, letterSpacing: -2, color: THEME.navy, opacity: a, transform: `scale(${interpolate(a, [0, 1], [0.8, 1]) * pulse})` }}>{h.scoreline}</div>
        <div style={{ marginTop: 24, fontFamily: FONT, fontSize: 40, color: THEME.muted, opacity: interpolate(useIn(24), [0, 1], [0, 1]) }}>{h.text}</div>
      </div>
    </Frame>
  );
};

// ---- Scene 5: outro / CTA --------------------------------------------------
const Outro: React.FC<{ p: DailyProps }> = ({ p }) => {
  const credit = p.credits && p.credits.length ? "Photos: " + p.credits.slice(0, 2).join(" · ") : undefined;
  return (
    <Frame credit={credit}>
      <div style={{ position: "absolute", top: 560, left: 90, right: 90, textAlign: "center" }}>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 76, color: THEME.navy, opacity: useIn(6) }}>Who wins today?</div>
        <div style={{ fontFamily: FONT, fontSize: 40, color: THEME.muted, marginTop: 20, opacity: interpolate(useIn(16), [0, 1], [0, 1]) }}>Independent model · daily World Cup calls</div>
      </div>
      <div style={{ position: "absolute", bottom: 300, left: 110, right: 110, textAlign: "center", opacity: interpolate(useIn(30), [0, 1], [0, 1]) }}>
        <div style={{ background: THEME.blue, color: "#fff", borderRadius: 16, padding: "24px 30px", fontFamily: FONT, fontWeight: 800, fontSize: 38 }}>Comment your score predictions</div>
        <div style={{ marginTop: 18, fontFamily: FONT, fontSize: 33, fontWeight: 700, color: THEME.blue }}>Follow for daily World Cup model calls</div>
      </div>
    </Frame>
  );
};

export const DailySlate: React.FC<DailyProps> = (p) => {
  const FPS = 30;
  const order: React.FC<{ p: DailyProps }>[] = [Intro];
  if (p.results && p.results.length) order.push(Results);
  if (p.matches && p.matches.length) order.push(Today);
  if (p.headline) order.push(Headline);
  order.push(Outro);
  const d = (p.durations && p.durations.length === order.length) ? p.durations : order.map(() => 6);
  const frames = d.map((x) => Math.max(1, Math.round(x * FPS)));
  return (
    <AbsoluteFill style={{ backgroundColor: THEME.bg }}>
      <Series>
        {order.map((S, i) => (
          <Series.Sequence key={i} durationInFrames={frames[i]}>
            <S p={p} />
          </Series.Sequence>
        ))}
      </Series>
      {p.hasAudio ? <Audio src={staticFile(p.audioFile)} /> : null}
    </AbsoluteFill>
  );
};
