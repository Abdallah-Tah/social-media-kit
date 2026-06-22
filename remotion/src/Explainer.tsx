import React from "react";
import {
  AbsoluteFill, Audio, Series, staticFile,
  interpolate, spring, useCurrentFrame, useVideoConfig,
} from "remotion";
import { BRAND, SAFE } from "./brand/tokens";
import { BrandFrame } from "./brand/BrandFrame";
import { OffsideLine } from "./primitives/OffsideLine";
import { CardSystem } from "./primitives/CardSystem";
import { PenaltySpot } from "./primitives/PenaltySpot";
import { MatchClock } from "./primitives/MatchClock";
import { HandballZone } from "./primitives/HandballZone";
import { RefereeApproach } from "./primitives/stubs";

// Full-screen rules-explainer rendered INSIDE the shared <BrandFrame>. One
// animated primitive per beat + an optional caption (LLM-framed, gate-passed).
// Captions stay clear of the Shorts safe zone (bottom ~15%).

const PRIMITIVES: Record<string, React.FC<{ params: any }>> = {
  OffsideLine: OffsideLine as any, CardSystem, PenaltySpot, MatchClock, HandballZone, RefereeApproach,
};

export type Beat = { caption?: string; visual: { type: string; params: any }; stress_words?: string[] };
export type ExplainerProps = {
  title: string;
  beats: Beat[];
  cta: string;
  brand?: string;
  durations: number[];
  hasAudio: boolean;
  audioFile: string;
};

const useIn = (delay = 0, damping = 13) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - delay, fps, config: { damping, mass: 0.7 } });
};

const Kicker: React.FC<{ title: string }> = ({ title }) => {
  const o = interpolate(useIn(4), [0, 1], [0, 1]);
  return (
    <div style={{ position: "absolute", top: SAFE.top + 18, left: 0, right: 0, textAlign: "center", opacity: o }}>
      <span style={{ fontFamily: BRAND.font, fontWeight: 900, fontSize: 46, letterSpacing: -1, color: BRAND.navy }}>{title}</span>
    </div>
  );
};

const Caption: React.FC<{ text?: string; stress?: string[] }> = ({ text, stress = [] }) => {
  const s = useIn(6);
  if (!text) return null;
  const words = text.split(" ");
  return (
    <div style={{ position: "absolute", left: SAFE.side, right: SAFE.side, bottom: SAFE.bottomReserve + 70, textAlign: "center", opacity: s, transform: `translateY(${interpolate(s, [0, 1], [30, 0])}px)` }}>
      <div style={{ display: "inline-block", background: "rgba(255,255,255,0.94)", borderRadius: 18, padding: "22px 34px", boxShadow: "0 12px 30px rgba(8,42,96,.16)" }}>
        <span style={{ fontFamily: BRAND.font, fontWeight: 700, fontSize: 44, lineHeight: 1.25, color: BRAND.text }}>
          {words.map((w, i) => {
            const bare = w.replace(/[.,!?]/g, "").toLowerCase();
            const hot = stress.some((s2) => s2.toLowerCase() === bare || s2.toLowerCase().includes(bare));
            return <span key={i} style={{ color: hot ? BRAND.blue : BRAND.text }}>{w}{i < words.length - 1 ? " " : ""}</span>;
          })}
        </span>
      </div>
    </div>
  );
};

const BeatView: React.FC<{ beat: Beat; title: string; badge: string }> = ({ beat, title, badge }) => {
  const P = PRIMITIVES[beat.visual?.type] || (() => null);
  return (
    <BrandFrame pageBadge={badge}>
      <P params={beat.visual?.params || {}} />
      <Kicker title={title} />
      <Caption text={beat.caption} stress={beat.stress_words} />
    </BrandFrame>
  );
};

const CTACard: React.FC<{ cta: string; title: string; badge: string }> = ({ cta, title, badge }) => {
  const s = useIn(8, 11);
  return (
    <BrandFrame pageBadge={badge}>
      <Kicker title={title} />
      <div style={{ position: "absolute", top: 760, left: 90, right: 90, textAlign: "center" }}>
        <div style={{ fontFamily: BRAND.font, fontWeight: 900, fontSize: 76, color: BRAND.navy, opacity: useIn(4) }}>Now you know.</div>
        <div style={{ marginTop: 44, opacity: s, transform: `scale(${interpolate(s, [0, 1], [0.85, 1])})` }}>
          <span style={{ background: BRAND.blue, color: "#fff", fontFamily: BRAND.font, fontWeight: 800, fontSize: 40, padding: "24px 40px", borderRadius: 16 }}>{cta}</span>
        </div>
      </div>
    </BrandFrame>
  );
};

export const Explainer: React.FC<ExplainerProps> = (p) => {
  const FPS = 30;
  const n = p.beats.length + 1;
  const views: React.ReactNode[] = p.beats.map((b, i) => <BeatView key={i} beat={b} title={p.title} badge={`${i + 1}/${n}`} />);
  views.push(<CTACard key="cta" cta={p.cta} title={p.title} badge={`${n}/${n}`} />);
  const d = (p.durations && p.durations.length === views.length) ? p.durations : views.map(() => 5);
  const frames = d.map((x) => Math.max(1, Math.round(x * FPS)));
  return (
    <AbsoluteFill style={{ backgroundColor: BRAND.bg }}>
      <Series>
        {views.map((v, i) => (
          <Series.Sequence key={i} durationInFrames={frames[i]}>{v}</Series.Sequence>
        ))}
      </Series>
      {p.hasAudio ? <Audio src={staticFile(p.audioFile)} /> : null}
    </AbsoluteFill>
  );
};
