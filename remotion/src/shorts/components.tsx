import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig, Img, staticFile } from "remotion";
import { THEME, FONT } from "../theme";
import { BrandFrame } from "../brand/BrandFrame";

export const useSpringIn = (delay = 0, damping = 13) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - delay, fps, config: { damping, mass: 0.7 } });
};

export const Chip: React.FC<{ children: React.ReactNode; tone?: "blue" | "white" | "navy"; delay?: number }> = ({
  children, tone = "blue", delay = 0,
}) => {
  const o = interpolate(useSpringIn(delay), [0, 1], [0, 1]);
  const bg = tone === "blue" ? THEME.blue : tone === "navy" ? THEME.navy : "#fff";
  const color = tone === "blue" ? "#fff" : THEME.navy;
  const border = tone === "white" ? `2px solid ${THEME.line}` : "none";
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 14, alignSelf: "flex-start",
      background: bg, color, border,
      borderRadius: 999, padding: tone === "blue" ? "16px 30px" : "16px 32px",
      fontFamily: FONT, fontWeight: 800, fontSize: tone === "blue" ? 30 : 34,
      letterSpacing: tone === "blue" ? 3 : 0, textTransform: tone === "blue" ? "uppercase" : "none",
      boxShadow: tone === "white" ? "0 8px 22px rgba(8,42,96,.08)" : "none", opacity: o,
    }}>
      <span style={{ width: 14, height: 14, borderRadius: "50%", background: tone === "blue" ? "#fff" : THEME.blue }} />
      {children}
    </div>
  );
};

export const ProgressBar: React.FC = () => {
  const f = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const w = interpolate(f, [0, durationInFrames], [0, 100], { extrapolateRight: "clamp" });
  return <div style={{ position: "absolute", left: 0, bottom: 0, height: 12, width: `${w}%`, background: THEME.blue, zIndex: 5 }} />;
};

export const NumberReveal: React.FC<{ value: number; delay?: number; style?: React.CSSProperties }> = ({
  value, delay = 0, style,
}) => {
  const s = useSpringIn(delay, 18);
  const n = Math.round(interpolate(s, [0, 1], [0, value]));
  return <span style={style}>{n}%</span>;
};

export const FactorCard: React.FC<{ text: string; index: number; hot?: boolean; delay?: number }> = ({ text, index, hot, delay }) => {
  const s = useSpringIn((delay ?? 6) + index * 8, 13);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 24,
      background: hot ? "linear-gradient(90deg,rgba(8,102,255,.06),#fff)" : "#fff",
      border: `3px solid ${hot ? THEME.blue : THEME.line}`, borderRadius: 20, padding: "30px 32px",
      boxShadow: "0 8px 20px rgba(8,42,96,.07)", opacity: s,
      transform: `translateX(${interpolate(s, [0, 1], [-40, 0])}px)`,
    }}>
      <div style={{ width: 20, height: 20, borderRadius: "50%", background: THEME.blue, flex: "0 0 20px" }} />
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 40, color: THEME.ink, lineHeight: 1.2 }}>{text}</div>
    </div>
  );
};

export const Content: React.FC<{ children: React.ReactNode; center?: boolean }> = ({ children, center }) => (
  <div style={{
    position: "absolute", top: 300, left: 80, right: 80, bottom: 280,
    display: "flex", flexDirection: "column", ...(center ? { justifyContent: "center", textAlign: "center" } : {}),
  }}>{children}</div>
);

export const Flag: React.FC<{ src: string; name: string; dir: number; delay: number }> = ({ src, name, dir, delay }) => {
  const s = useSpringIn(delay, 12);
  return (
    <div style={{ textAlign: "center", opacity: s, transform: `translateX(${interpolate(s, [0, 1], [dir * 90, 0])}px)` }}>
      <Img src={staticFile(src)} style={{ width: 270, height: 180, objectFit: "cover", borderRadius: 18, boxShadow: "0 16px 38px rgba(8,42,96,.2)", border: "4px solid #fff" }} />
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 44, color: THEME.navy, marginTop: 22 }}>{name}</div>
    </div>
  );
};

export const MatchupBanner: React.FC<{ p: { home: string; away: string; competition: string; homeFlag: string; awayFlag: string; leader: string; confidence: number }; delay?: number }> = ({ p, delay = 0 }) => {
  const vs = useSpringIn((delay || 0) + 14, 9);
  return (
    <BrandFrame>
      <Content center>
        <Chip delay={delay}>{p.competition}</Chip>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 90 }}>
          <Flag src={p.homeFlag} name={p.home} dir={-1} delay={(delay || 0) + 6} />
          <div style={{ width: 120, height: 120, borderRadius: "50%", background: THEME.navy, display: "grid", placeItems: "center", color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 50, transform: `scale(${interpolate(vs, [0, 1], [0.4, 1])})` }}>VS</div>
          <Flag src={p.awayFlag} name={p.away} dir={1} delay={(delay || 0) + 10} />
        </div>
        <div style={{ marginTop: 90, fontFamily: FONT, fontWeight: 700, fontSize: 38, color: THEME.muted, opacity: interpolate(useSpringIn((delay || 0) + 26), [0, 1], [0, 1]) }}>
          Model leans <b style={{ color: THEME.navy }}>{p.leader}</b> · <b style={{ color: THEME.blue }}><NumberReveal value={p.confidence} delay={(delay || 0) + 30} /></b> win probability
        </div>
      </Content>
    </BrandFrame>
  );
};

export const VerdictCard: React.FC<{ p: { leader: string; verdict: string; confidence: number }; label?: string }> = ({ p, label = "Model Verdict" }) => {
  const v = useSpringIn(6, 9);
  const f = useCurrentFrame();
  const pulse = 1 + Math.sin(f / 8) * 0.015;
  return (
    <BrandFrame>
      <Content center>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 34, letterSpacing: 6, color: THEME.blue, textTransform: "uppercase", opacity: interpolate(v, [0, 1], [0, 1]) }}>{label}</div>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 104, lineHeight: 1.02, letterSpacing: -2, color: THEME.navy, marginTop: 30, opacity: v, transform: `scale(${interpolate(v, [0, 1], [0.8, 1])})` }}>{p.verdict}</div>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 150, lineHeight: 1, color: THEME.blue, marginTop: 36, transform: `scale(${pulse})` }}>
          <NumberReveal value={p.confidence} delay={12} />
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 38, color: THEME.muted, letterSpacing: 2, textTransform: "uppercase", marginTop: 6 }}>model win probability</div>
      </Content>
    </BrandFrame>
  );
};

export const CtaCard: React.FC<{ home: string; away: string; verdict: string; cta: string }> = ({ home, away, verdict, cta }) => {
  const c = useSpringIn(4, 11);
  return (
    <BrandFrame>
      <Content center>
        <div style={{ margin: "auto 0", opacity: c, transform: `scale(${interpolate(c, [0, 1], [0.9, 1])})` }}>
          <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: THEME.muted }}>{home} vs {away} · {verdict}</div>
          <div style={{ marginTop: 40, background: THEME.blue, color: "#fff", borderRadius: 22, padding: "38px 40px", fontFamily: FONT, fontWeight: 900, fontSize: 46, lineHeight: 1.25, boxShadow: "0 16px 40px rgba(8,102,255,.28)" }}>{cta}</div>
        </div>
      </Content>
    </BrandFrame>
  );
};
