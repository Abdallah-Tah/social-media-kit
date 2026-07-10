import React from "react";
import { interpolate, Series } from "remotion";
import { BrandFrame } from "../../brand/BrandFrame";
import { Chip, Content, FactorCard, useSpringIn } from "../components";
import { MatchupBanner, VerdictCard, CtaCard } from "../components";
import { FONT, THEME } from "../../theme";

export type KeyFactorMysteryProps = {
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

const HookScene: React.FC<{ p: KeyFactorMysteryProps }> = ({ p }) => {
  const pop = useSpringIn(1, 11);
  const sub = interpolate(useSpringIn(9), [0, 1], [0, 1]);
  return (
    <BrandFrame>
      <Content>
        <div style={{ transform: `scale(${interpolate(pop, [0, 1], [0.92, 1])})`, transformOrigin: "left top" }}>
          <Chip delay={0}>AI MODEL • WORLD CUP PREDICTION</Chip>
          <div style={{
            fontFamily: FONT, fontWeight: 900, fontSize: 92, lineHeight: 1.05, letterSpacing: -3,
            color: THEME.navy, marginTop: 56, opacity: pop,
            transform: `translateY(${interpolate(pop, [0, 1], [40, 0])}px)`,
          }}>{p.hook}</div>
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 40, color: THEME.muted, marginTop: 38, lineHeight: 1.3, opacity: sub }}>{p.subheadline}</div>
        </div>
        <div style={{ marginTop: "auto" }}><Chip tone="white" delay={16}>{p.credibilityChip}</Chip></div>
      </Content>
    </BrandFrame>
  );
};

const FactorsScene: React.FC<{ p: KeyFactorMysteryProps }> = ({ p }) => {
  const lab = interpolate(useSpringIn(2), [0, 1], [0, 1]);
  const factors = p.factors.slice(0, 3);
  return (
    <BrandFrame>
      <Content>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 32, letterSpacing: 5, color: THEME.blue, textTransform: "uppercase", opacity: lab }}>{p.factorLabel}</div>
        <div style={{ marginTop: 44, display: "flex", flexDirection: "column", gap: 26 }}>
          {factors.map((f, i) => (
            <FactorCard key={i} text={f} index={i} hot={i === factors.length - 1} />
          ))}
        </div>
      </Content>
    </BrandFrame>
  );
};

export const KeyFactorMystery: React.FC<KeyFactorMysteryProps> = (p) => {
  const [f1, f2, f3, f4, f5] = p.frames;
  return (
    <Series>
      <Series.Sequence durationInFrames={f1}>
        <HookScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f2}>
        <MatchupBanner p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f3}>
        <FactorsScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f4}>
        <VerdictCard p={{ leader: p.leader, verdict: p.verdict, confidence: p.confidence }} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f5}>
        <CtaCard home={p.home} away={p.away} verdict={p.verdict} cta={p.cta} />
      </Series.Sequence>
    </Series>
  );
};
