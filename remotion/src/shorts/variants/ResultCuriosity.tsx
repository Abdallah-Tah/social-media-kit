import React from "react";
import { interpolate, Series } from "remotion";
import { BrandFrame } from "../../brand/BrandFrame";
import { Chip, Content, FactorCard, NumberReveal, useSpringIn } from "../components";
import { Flag, VerdictCard, CtaCard } from "../components";
import { FONT, THEME } from "../../theme";

export type ResultCuriosityProps = {
  home: string;
  away: string;
  competition: string;
  homeFlag: string;
  awayFlag: string;
  leader: string;
  confidence: number;
  winProb: number;
  drawProb: number;
  lossProb: number;
  verdict: string;
  credibilityChip: string;
  hook: string;
  subheadline: string;
  factorLabel: string;
  factors: string[];
  cta: string;
  frames: number[];
};

const HookScene: React.FC<{ p: ResultCuriosityProps }> = ({ p }) => {
  const pop = useSpringIn(1, 11);
  const sub = interpolate(useSpringIn(9), [0, 1], [0, 1]);
  return (
    <BrandFrame>
      <Content>
        <div style={{ transform: `scale(${interpolate(pop, [0, 1], [0.92, 1])})`, transformOrigin: "left top" }}>
          <Chip delay={0}>AI PREDICTION LOCKED IN</Chip>
          <div style={{
            fontFamily: FONT, fontWeight: 900, fontSize: 88, lineHeight: 1.05, letterSpacing: -3,
            color: THEME.navy, marginTop: 54, opacity: pop,
            transform: `translateY(${interpolate(pop, [0, 1], [40, 0])}px)`,
          }}>{p.hook}</div>
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 40, color: THEME.muted, marginTop: 36, lineHeight: 1.3, opacity: sub }}>{p.subheadline}</div>
        </div>
        <div style={{ marginTop: "auto" }}><Chip tone="white" delay={16}>{p.credibilityChip}</Chip></div>
      </Content>
    </BrandFrame>
  );
};

const TeaseScene: React.FC<{ p: ResultCuriosityProps }> = ({ p }) => {
  const s = useSpringIn(4, 12);
  return (
    <BrandFrame>
      <Content center>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 38, letterSpacing: 4, color: THEME.blue, textTransform: "uppercase", opacity: interpolate(useSpringIn(2), [0, 1], [0, 1]) }}>{p.competition}</div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 80 }}>
          <Flag src={p.homeFlag} name={p.home} dir={-1} delay={6} />
          <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 48, color: THEME.navy }}>VS</div>
          <Flag src={p.awayFlag} name={p.away} dir={1} delay={10} />
        </div>
        <div style={{ marginTop: 80, fontFamily: FONT, fontWeight: 900, fontSize: 56, color: THEME.navy, opacity: s }}>
          Will it be <span style={{ color: THEME.blue }}>{p.home}</span> or <span style={{ color: THEME.blue }}>{p.away}</span>?
        </div>
      </Content>
    </BrandFrame>
  );
};

const RevealScene: React.FC<{ p: ResultCuriosityProps }> = ({ p }) => {
  const s = useSpringIn(4, 10);
  return (
    <BrandFrame>
      <Content center>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 34, letterSpacing: 6, color: THEME.blue, textTransform: "uppercase", opacity: interpolate(useSpringIn(2), [0, 1], [0, 1]) }}>The model says...</div>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 110, lineHeight: 1.02, letterSpacing: -2, color: THEME.navy, marginTop: 40, opacity: s, transform: `scale(${interpolate(s, [0, 1], [0.8, 1])})` }}>
          {p.leader}
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 130, lineHeight: 1, color: THEME.blue, marginTop: 30 }}>
          <NumberReveal value={p.confidence} delay={12} />
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 38, color: THEME.muted, letterSpacing: 2, textTransform: "uppercase", marginTop: 6 }}>win probability</div>
      </Content>
    </BrandFrame>
  );
};

const FactorsScene: React.FC<{ p: ResultCuriosityProps }> = ({ p }) => {
  const lab = interpolate(useSpringIn(2), [0, 1], [0, 1]);
  const factors = p.factors.slice(0, 3);
  return (
    <BrandFrame>
      <Content>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 32, letterSpacing: 5, color: THEME.blue, textTransform: "uppercase", opacity: lab }}>{p.factorLabel}</div>
        <div style={{ marginTop: 44, display: "flex", flexDirection: "column", gap: 26 }}>
          {factors.map((f, i) => (
            <FactorCard key={i} text={f} index={i} />
          ))}
        </div>
      </Content>
    </BrandFrame>
  );
};

export const ResultCuriosity: React.FC<ResultCuriosityProps> = (p) => {
  const [f1, f2, f3, f4, f5] = p.frames;
  return (
    <Series>
      <Series.Sequence durationInFrames={f1}>
        <HookScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f2}>
        <TeaseScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f3}>
        <RevealScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f4}>
        <FactorsScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f5}>
        <CtaCard home={p.home} away={p.away} verdict={p.verdict} cta={p.cta} />
      </Series.Sequence>
    </Series>
  );
};
