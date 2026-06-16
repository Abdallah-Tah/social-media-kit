import React from "react";
import {
  AbsoluteFill,
  Img,
  Audio,
  Series,
  staticFile,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { THEME, FONT } from "./theme";

// ============================================================================
// Full-screen World Cup prediction Short — the ENTIRE 1080x1920 canvas IS the
// prediction card (clean sports-analytics product look). No poster wrapper.
// ============================================================================

export type PredictionProps = {
  home: string;
  away: string;
  competition: string;
  hook: string;
  lean: string;           // e.g. "Iran 1 – 0 New Zealand"
  confidence: string;     // e.g. "Slight Iran edge"
  reasons: string[];      // reason chips
  probs: { homeP: number; drawP: number; awayP: number }; // 0..100
  factors: string[];
  finalCall: string;      // e.g. "Iran 1 – 0"
  durations: number[];
  hasAudio: boolean;
  audioFile: string;
  homeFlag: string;       // file in public/
  awayFlag: string;
};

const safeTop = 96;

// ---- shared full-screen chrome ---------------------------------------------

const CornerAccents: React.FC = () => (
  <>
    <div style={{ position: "absolute", top: 0, right: 0, width: 0, height: 0, borderTop: "240px solid #0b2a6b", borderLeft: "240px solid transparent", opacity: 0.9 }} />
    <div style={{ position: "absolute", top: 0, right: 0, width: 0, height: 0, borderTop: "150px solid " + THEME.blue, borderLeft: "150px solid transparent" }} />
    <div style={{ position: "absolute", bottom: 0, left: 0, width: 0, height: 0, borderBottom: "190px solid rgba(8,102,255,.10)", borderRight: "190px solid transparent" }} />
    {/* faint giant watermark */}
    <div style={{ position: "absolute", right: -40, top: 560, fontFamily: FONT, fontWeight: 900, fontSize: 760, color: THEME.navy, opacity: 0.04, lineHeight: 1 }}>A</div>
    {/* dotted pattern bottom-left */}
    <div style={{ position: "absolute", left: 70, bottom: 150, display: "grid", gridTemplateColumns: "repeat(6,16px)", gap: 12, opacity: 0.4 }}>
      {Array.from({ length: 30 }).map((_, i) => (
        <div key={i} style={{ width: 8, height: 8, borderRadius: "50%", background: THEME.blue }} />
      ))}
    </div>
  </>
);

const Branding: React.FC = () => (
  <div style={{ position: "absolute", top: safeTop, left: 80, right: 80, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: THEME.ink }}>
        Build With <span style={{ color: THEME.blue }}>Abdallah</span>
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 19, letterSpacing: 3, color: THEME.muted, marginTop: 6 }}>
        THE PITCH AGENT • INDEPENDENT FOOTBALL ANALYTICS
      </div>
    </div>
    <div style={{ width: 88, height: 88, borderRadius: 20, background: "#fff", border: `4px solid ${THEME.blue}`, display: "grid", placeItems: "center", fontFamily: FONT, fontWeight: 900, fontSize: 46, color: THEME.navy, boxShadow: "0 10px 24px rgba(8,42,96,.14)" }}>A</div>
  </div>
);

const Footer: React.FC = () => (
  <div style={{ position: "absolute", bottom: 70, left: 0, right: 0, textAlign: "center", fontFamily: FONT, fontSize: 22, color: THEME.muted, opacity: 0.85 }}>
    The Pitch Agent by BuildWithAbdallah&nbsp;&nbsp;|&nbsp;&nbsp;Independent analytics&nbsp;&nbsp;|&nbsp;&nbsp;Not affiliated with FIFA
  </div>
);

const Frame: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ background: THEME.bgGrad, fontFamily: FONT }}>
    <CornerAccents />
    <Branding />
    {children}
    <Footer />
  </AbsoluteFill>
);

const SectionLabel: React.FC<{ text: string; delay?: number }> = ({ text, delay = 0 }) => {
  const f = useCurrentFrame();
  const o = interpolate(f - delay, [0, 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 30, letterSpacing: 6, color: THEME.blue, opacity: o }}>{text}</div>
  );
};

const useSpringIn = (delay = 0, damping = 13) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - delay, fps, config: { damping, mass: 0.7 } });
};

// ---- Scene 1 — Match setup --------------------------------------------------

const Flag: React.FC<{ src: string; name: string; dir: number; delay: number }> = ({ src, name, dir, delay }) => {
  const s = useSpringIn(delay, 12);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22, opacity: s, transform: `translateX(${interpolate(s, [0, 1], [dir * 90, 0])}px)` }}>
      <Img src={staticFile(src)} style={{ width: 300, height: 200, objectFit: "cover", borderRadius: 20, boxShadow: "0 18px 40px rgba(8,42,96,.20)", border: "4px solid #fff" }} />
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 46, color: THEME.navy }}>{name}</div>
    </div>
  );
};

const MatchSetup: React.FC<{ p: PredictionProps }> = ({ p }) => {
  const title = useSpringIn(4);
  const vs = useSpringIn(20, 9);
  const hook = useSpringIn(38);
  return (
    <Frame>
      <div style={{ position: "absolute", top: 330, left: 80, right: 80, textAlign: "center" }}>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 96, letterSpacing: -1, color: THEME.navy, opacity: title, transform: `translateY(${interpolate(title, [0, 1], [40, 0])}px)` }}>MATCH PREDICTION</div>
        <div style={{ fontFamily: FONT, fontSize: 44, color: THEME.muted, marginTop: 18, opacity: interpolate(useSpringIn(12), [0, 1], [0, 1]) }}>{p.home} vs {p.away} · {p.competition}</div>
      </div>
      <div style={{ position: "absolute", top: 720, left: 80, right: 80, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Flag src={p.homeFlag} name={p.home} dir={-1} delay={12} />
        <div style={{ width: 130, height: 130, borderRadius: "50%", background: THEME.navy, display: "grid", placeItems: "center", color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 56, transform: `scale(${interpolate(vs, [0, 1], [0.4, 1])})`, boxShadow: "0 12px 30px rgba(7,26,68,.30)" }}>VS</div>
        <Flag src={p.awayFlag} name={p.away} dir={1} delay={18} />
      </div>
      <div style={{ position: "absolute", bottom: 300, left: 110, right: 110, textAlign: "center", opacity: hook }}>
        <div style={{ display: "inline-block", background: THEME.blueSoft, border: `2px solid #cfe0ff`, borderRadius: 16, padding: "22px 38px", fontFamily: FONT, fontSize: 42, fontWeight: 700, color: THEME.ink }}>{p.hook}</div>
      </div>
    </Frame>
  );
};

// ---- Scene 2 — Model read ---------------------------------------------------

const ModelRead: React.FC<{ p: PredictionProps }> = ({ p }) => {
  const score = useSpringIn(10, 10);
  return (
    <Frame>
      <div style={{ position: "absolute", top: 360, left: 90, right: 90 }}>
        <SectionLabel text="MODEL LEANS" />
        <div style={{ marginTop: 40, fontFamily: FONT, fontWeight: 900, fontSize: 110, letterSpacing: -2, color: THEME.navy, lineHeight: 1.04, opacity: score, transform: `scale(${interpolate(score, [0, 1], [0.85, 1])})`, transformOrigin: "left" }}>{p.lean}</div>
        <div style={{ marginTop: 40, display: "inline-block", background: THEME.navy, color: "#fff", borderRadius: 14, padding: "18px 34px", fontFamily: FONT, fontWeight: 800, fontSize: 40, opacity: interpolate(useSpringIn(26), [0, 1], [0, 1]) }}>{p.confidence}</div>
        <div style={{ marginTop: 70, display: "flex", flexWrap: "wrap", gap: 22 }}>
          {p.reasons.map((r, i) => {
            const s = useSpringIn(40 + i * 12, 12);
            return (
              <div key={i} style={{ background: "#fff", border: `3px solid ${THEME.line}`, borderRadius: 999, padding: "20px 34px", fontFamily: FONT, fontWeight: 700, fontSize: 38, color: THEME.ink, boxShadow: "0 8px 20px rgba(8,42,96,.08)", opacity: s, transform: `translateY(${interpolate(s, [0, 1], [24, 0])}px)` }}>{r}</div>
            );
          })}
        </div>
      </div>
    </Frame>
  );
};

// ---- Scene 3 — Probability bars --------------------------------------------

const Bar: React.FC<{ label: string; pct: number; color: string; delay: number }> = ({ label, pct, color, delay }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const grow = spring({ frame: f - delay, fps, config: { damping: 16, mass: 0.9 } });
  const w = interpolate(grow, [0, 1], [0, pct]);
  return (
    <div style={{ marginBottom: 46 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: FONT, fontWeight: 800, fontSize: 42, color: THEME.ink, marginBottom: 16 }}>
        <span>{label}</span>
        <span style={{ color }}>{Math.round(w)}%</span>
      </div>
      <div style={{ height: 56, background: "#e9eff8", borderRadius: 14, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${w}%`, background: color, borderRadius: 14 }} />
      </div>
    </div>
  );
};

const Probability: React.FC<{ p: PredictionProps }> = ({ p }) => (
  <Frame>
    <div style={{ position: "absolute", top: 360, left: 90, right: 90 }}>
      <SectionLabel text="WIN PROBABILITY" />
      <div style={{ marginTop: 70 }}>
        <Bar label={p.home} pct={p.probs.homeP} color={THEME.blue} delay={16} />
        <Bar label="Draw" pct={p.probs.drawP} color={THEME.muted} delay={28} />
        <Bar label={p.away} pct={p.probs.awayP} color={THEME.navy} delay={40} />
      </div>
      <div style={{ marginTop: 30, fontFamily: FONT, fontSize: 34, color: THEME.muted, opacity: interpolate(useSpringIn(56), [0, 1], [0, 1]) }}>Independent model estimate · close matchup</div>
    </div>
  </Frame>
);

// ---- Scene 4 — Key factors --------------------------------------------------

const KeyFactors: React.FC<{ p: PredictionProps }> = ({ p }) => (
  <Frame>
    <div style={{ position: "absolute", top: 360, left: 90, right: 90 }}>
      <SectionLabel text="KEY FACTORS" />
      <div style={{ marginTop: 60, display: "flex", flexDirection: "column", gap: 30 }}>
        {p.factors.map((fct, i) => {
          const s = useSpringIn(14 + i * 14, 13);
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 26, background: "#fff", border: `3px solid ${THEME.line}`, borderRadius: 18, padding: "30px 32px", boxShadow: "0 8px 20px rgba(8,42,96,.07)", opacity: s, transform: `translateX(${interpolate(s, [0, 1], [-40, 0])}px)` }}>
              <div style={{ width: 22, height: 22, borderRadius: "50%", background: THEME.blue, flex: "0 0 22px" }} />
              <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 42, color: THEME.ink, lineHeight: 1.2 }}>{fct}</div>
            </div>
          );
        })}
      </div>
    </div>
  </Frame>
);

// ---- Scene 5 — Final call + CTA --------------------------------------------

const FinalCall: React.FC<{ p: PredictionProps }> = ({ p }) => {
  const call = useSpringIn(10, 9);
  const f = useCurrentFrame();
  const pulse = 1 + Math.sin(f / 7) * 0.02;
  return (
    <Frame>
      <div style={{ position: "absolute", top: 470, left: 90, right: 90, textAlign: "center" }}>
        <SectionLabel text="FINAL MODEL CALL" />
        <div style={{ marginTop: 50, fontFamily: FONT, fontWeight: 900, fontSize: 150, letterSpacing: -3, color: THEME.navy, opacity: call, transform: `scale(${interpolate(call, [0, 1], [0.7, 1]) * pulse})` }}>{p.finalCall}</div>
        <div style={{ marginTop: 26, fontFamily: FONT, fontSize: 38, color: THEME.muted }}>Independent model prediction</div>
      </div>
      <div style={{ position: "absolute", bottom: 250, left: 110, right: 110, textAlign: "center", opacity: interpolate(useSpringIn(40), [0, 1], [0, 1]) }}>
        <div style={{ background: THEME.blue, color: "#fff", borderRadius: 16, padding: "24px 30px", fontFamily: FONT, fontWeight: 800, fontSize: 38 }}>Comment your score prediction</div>
        <div style={{ marginTop: 20, fontFamily: FONT, fontSize: 34, fontWeight: 700, color: THEME.blue }}>Follow for daily World Cup model calls</div>
      </div>
    </Frame>
  );
};

export const Prediction: React.FC<PredictionProps> = (p) => {
  const FPS = 30;
  const d = p.durations || [4, 6, 6, 6, 5];
  const frames = d.map((x) => Math.max(1, Math.round(x * FPS)));
  const scenes = [MatchSetup, ModelRead, Probability, KeyFactors, FinalCall];
  return (
    <AbsoluteFill style={{ backgroundColor: THEME.bg }}>
      <Series>
        {scenes.map((S, i) => (
          <Series.Sequence key={i} durationInFrames={frames[i]}>
            <S p={p} />
          </Series.Sequence>
        ))}
      </Series>
      {p.hasAudio ? <Audio src={staticFile(p.audioFile)} /> : null}
    </AbsoluteFill>
  );
};
