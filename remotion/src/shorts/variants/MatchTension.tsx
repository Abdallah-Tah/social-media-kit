import React from "react";
import { interpolate, Series, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { BrandFrame } from "../../brand/BrandFrame";
import { Chip, Content, FactorCard, NumberReveal, useSpringIn } from "../components";
import { Flag, VerdictCard, CtaCard } from "../components";
import { FONT, THEME } from "../../theme";

export type MatchTensionProps = {
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
  tensionLabel: string;
  tensionFactors: string[];
  cta: string;
  frames: number[];
};

const usePulse = () => {
  const f = useCurrentFrame();
  return 1 + Math.sin(f / 6) * 0.02;
};

const TensionBar: React.FC<{ label: string; value: number; color: string; delay: number }> = ({ label, value, color, delay }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const grow = spring({ frame: f - delay, fps, config: { damping: 16, mass: 0.9 } });
  const w = interpolate(grow, [0, 1], [0, value]);
  return (
    <div style={{ marginBottom: 42 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: FONT, fontWeight: 800, fontSize: 40, color: THEME.ink, marginBottom: 16 }}>
        <span>{label}</span>
        <span style={{ color }}>{Math.round(w)}%</span>
      </div>
      <div style={{ height: 52, background: "#e9eff8", borderRadius: 14, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${w}%`, background: color, borderRadius: 14 }} />
      </div>
    </div>
  );
};

const HookScene: React.FC<{ p: MatchTensionProps }> = ({ p }) => {
  const pop = useSpringIn(1, 11);
  const sub = interpolate(useSpringIn(9), [0, 1], [0, 1]);
  return (
    <BrandFrame>
      <Content>
        <div style={{ transform: `scale(${interpolate(pop, [0, 1], [0.92, 1])})`, transformOrigin: "left top" }}>
          <Chip delay={0}>TIGHT MATCHUP</Chip>
          <div style={{
            fontFamily: FONT, fontWeight: 900, fontSize: 90, lineHeight: 1.05, letterSpacing: -3,
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

const FaceoffScene: React.FC<{ p: MatchTensionProps }> = ({ p }) => {
  const pulse = usePulse();
  const s = useSpringIn(4, 12);
  return (
    <BrandFrame>
      <Content center>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 38, letterSpacing: 4, color: THEME.blue, textTransform: "uppercase", opacity: interpolate(useSpringIn(2), [0, 1], [0, 1]) }}>{p.competition}</div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 70, transform: `scale(${pulse})` }}>
          <Flag src={p.homeFlag} name={p.home} dir={-1} delay={6} />
          <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 56, color: THEME.navy }}>—</div>
          <Flag src={p.awayFlag} name={p.away} dir={1} delay={10} />
        </div>
        <div style={{ marginTop: 70, fontFamily: FONT, fontWeight: 800, fontSize: 42, color: THEME.navy, opacity: s }}>
          Winner takes <span style={{ color: THEME.blue }}><NumberReveal value={p.winProb} delay={14} />%</span> in the model
        </div>
      </Content>
    </BrandFrame>
  );
};

const TensionFactorsScene: React.FC<{ p: MatchTensionProps }> = ({ p }) => {
  const lab = interpolate(useSpringIn(2), [0, 1], [0, 1]);
  const factors = p.tensionFactors.slice(0, 3);
  return (
    <BrandFrame>
      <Content>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 32, letterSpacing: 5, color: THEME.blue, textTransform: "uppercase", opacity: lab }}>{p.tensionLabel}</div>
        <div style={{ marginTop: 44, display: "flex", flexDirection: "column", gap: 26 }}>
          {factors.map((f, i) => (
            <FactorCard key={i} text={f} index={i} />
          ))}
        </div>
      </Content>
    </BrandFrame>
  );
};

const ProbabilitySplitScene: React.FC<{ p: MatchTensionProps }> = ({ p }) => {
  const lab = interpolate(useSpringIn(2), [0, 1], [0, 1]);
  return (
    <BrandFrame>
      <Content>
        <div style={{ fontFamily: FONT, fontWeight: 900, fontSize: 32, letterSpacing: 5, color: THEME.blue, textTransform: "uppercase", opacity: lab }}>WHY IT IS SO TIGHT</div>
        <div style={{ marginTop: 50 }}>
          <TensionBar label={p.home} value={p.winProb} color={THEME.blue} delay={10} />
          <TensionBar label="Draw" value={p.drawProb} color={THEME.muted} delay={22} />
          <TensionBar label={p.away} value={p.lossProb} color={THEME.navy} delay={34} />
        </div>
      </Content>
    </BrandFrame>
  );
};

export const MatchTension: React.FC<MatchTensionProps> = (p) => {
  const [f1, f2, f3, f4, f5] = p.frames;
  return (
    <Series>
      <Series.Sequence durationInFrames={f1}>
        <HookScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f2}>
        <FaceoffScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f3}>
        <TensionFactorsScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f4}>
        <ProbabilitySplitScene p={p} />
      </Series.Sequence>
      <Series.Sequence durationInFrames={f5}>
        <VerdictCard p={{ leader: p.leader, verdict: p.verdict, confidence: p.confidence }} label="THE MODEL BREAKS THE TIE" />
      </Series.Sequence>
      <Series.Sequence durationInFrames={Math.max(1, Math.round(3 * 30))}>
        <CtaCard home={p.home} away={p.away} verdict={p.verdict} cta={p.cta} />
      </Series.Sequence>
    </Series>
  );
};
