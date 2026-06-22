import React from "react";
import {
  AbsoluteFill, Audio, Series, staticFile,
  interpolate, spring, useCurrentFrame, useVideoConfig,
} from "remotion";
import { BRAND, SAFE } from "./brand/tokens";
import { BrandFrame } from "./brand/BrandFrame";

export type SurvivalLabProps = {
  title: string;
  titleLines: string[];
  hook: string;
  subtitle: string;
  groups: string[];
  dangerExamples: string[];
  cta: string;
  durations: number[];
  hasAudio: boolean;
  audioFile: string;
};

const useIn = (delay = 0, damping = 13) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - delay, fps, config: { damping, mass: 0.7 } });
};

const Badge: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{
    display: "inline-block", background: BRAND.blue, color: "#fff",
    borderRadius: 13, padding: "14px 22px", fontFamily: BRAND.font,
    fontWeight: 900, fontSize: 27, letterSpacing: 1,
  }}>
    {children}
  </div>
);

const TitleLines: React.FC<{ lines: string[]; size?: number }> = ({ lines, size = 68 }) => (
  <div style={{
    fontFamily: BRAND.font, fontWeight: 930, fontSize: size,
    lineHeight: 1.08, letterSpacing: 0, color: BRAND.navy,
  }}>
    {lines.slice(0, 3).map((line, i) => <div key={i}>{line}</div>)}
  </div>
);

const GroupCards: React.FC<{ groups: string[]; top?: number }> = ({ groups, top = 520 }) => {
  const visible = groups.slice(0, 12);
  return (
    <div style={{
      position: "absolute", top, left: SAFE.side, right: SAFE.side,
      display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18,
    }}>
      {visible.map((g, i) => {
        const s = useIn(8 + i * 3, 13);
        return (
          <div key={g} style={{
            height: 118, borderRadius: 18, background: "#fff",
            border: `3px solid ${BRAND.line}`, boxShadow: "0 8px 20px rgba(8,42,96,.08)",
            display: "flex", alignItems: "center", justifyContent: "center",
            opacity: s, transform: `translateY(${interpolate(s, [0, 1], [22, 0])}px)`,
          }}>
            <div style={{ fontFamily: BRAND.font, fontWeight: 900, color: BRAND.navy, fontSize: 30 }}>GROUP {g}</div>
          </div>
        );
      })}
    </div>
  );
};

const AdvancingTable: React.FC = () => {
  const rows = [
    ["1st", "automatic"],
    ["2nd", "automatic"],
    ["3rd", "survival table"],
    ["4th", "out"],
  ];
  return (
    <div style={{ position: "absolute", top: 620, left: 94, right: 94 }}>
      {rows.map((row, i) => {
        const s = useIn(12 + i * 8, 13);
        const active = i < 2;
        return (
          <div key={row[0]} style={{
            height: 128, marginBottom: 22, borderRadius: 20,
            background: active ? BRAND.navy : "#fff",
            border: `3px solid ${active ? BRAND.blue : BRAND.line}`,
            boxShadow: "0 12px 26px rgba(8,42,96,.10)",
            display: "grid", gridTemplateColumns: "180px 1fr", alignItems: "center",
            padding: "0 34px", opacity: s,
            transform: `translateX(${interpolate(s, [0, 1], [-38, 0])}px)`,
          }}>
            <div style={{ fontFamily: BRAND.font, fontWeight: 950, fontSize: 54, color: active ? "#fff" : BRAND.blue }}>{row[0]}</div>
            <div style={{ fontFamily: BRAND.font, fontWeight: 850, fontSize: 42, color: active ? "#fff" : BRAND.text }}>{row[1]}</div>
          </div>
        );
      })}
    </div>
  );
};

const ThirdPlaceTable: React.FC = () => {
  const rows = [
    ["3A", "4 pts", "+1"],
    ["3B", "4 pts", "0"],
    ["3C", "3 pts", "+2"],
    ["3D", "3 pts", "-1"],
    ["3E", "2 pts", "0"],
    ["3F", "1 pt", "-2"],
  ];
  return (
    <div style={{ position: "absolute", top: 520, left: 78, right: 78 }}>
      <div style={{
        background: BRAND.navy, color: "#fff", borderRadius: "18px 18px 0 0",
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
        padding: "22px 28px", fontFamily: BRAND.font, fontWeight: 900, fontSize: 32,
      }}>
        <div>TEAM</div><div>POINTS</div><div>GD</div>
      </div>
      {rows.map((row, i) => {
        const s = useIn(10 + i * 5, 13);
        return (
          <div key={row[0]} style={{
            display: "grid", gridTemplateColumns: "1fr 1fr 1fr", alignItems: "center",
            padding: "20px 28px", background: i < 4 ? "#fff" : "rgba(255,255,255,.78)",
            borderLeft: `3px solid ${BRAND.line}`, borderRight: `3px solid ${BRAND.line}`,
            borderBottom: `3px solid ${BRAND.line}`,
            fontFamily: BRAND.font, fontWeight: 850, fontSize: 36,
            color: i < 4 ? BRAND.navy : BRAND.muted, opacity: s,
          }}>
            <div>{row[0]}</div><div>{row[1]}</div><div>{row[2]}</div>
          </div>
        );
      })}
      <div style={{
        marginTop: 30, background: BRAND.blue, color: "#fff", borderRadius: 18,
        padding: "26px 30px", textAlign: "center", fontFamily: BRAND.font,
        fontWeight: 950, fontSize: 48,
      }}>
        8 third-place teams survive
      </div>
    </div>
  );
};

const DangerList: React.FC<{ items: string[] }> = ({ items }) => (
  <div style={{ position: "absolute", top: 540, left: 82, right: 82, display: "flex", flexDirection: "column", gap: 28 }}>
    {items.map((item, i) => {
      const s = useIn(10 + i * 11, 13);
      return (
        <div key={item} style={{
          background: "#fff", borderRadius: 20, border: `3px solid ${BRAND.line}`,
          padding: "34px 36px", display: "grid", gridTemplateColumns: "72px 1fr",
          alignItems: "center", boxShadow: "0 12px 26px rgba(8,42,96,.10)",
          opacity: s, transform: `translateY(${interpolate(s, [0, 1], [28, 0])}px)`,
        }}>
          <div style={{
            width: 54, height: 54, borderRadius: "50%", background: i === 0 ? BRAND.green : BRAND.blue,
            color: "#fff", display: "grid", placeItems: "center", fontFamily: BRAND.font,
            fontWeight: 950, fontSize: 28,
          }}>{i + 1}</div>
          <div style={{ fontFamily: BRAND.font, fontWeight: 870, fontSize: 42, color: BRAND.text, lineHeight: 1.18 }}>{item}</div>
        </div>
      );
    })}
  </div>
);

const SceneTitle: React.FC<{ badge: string; title: string; sub?: string }> = ({ badge, title, sub }) => (
  <div style={{ position: "absolute", top: 300, left: SAFE.side, right: SAFE.side, textAlign: "center" }}>
    <Badge>{badge}</Badge>
    <div style={{ marginTop: 34, fontFamily: BRAND.font, fontWeight: 930, fontSize: 62, lineHeight: 1.08, color: BRAND.navy }}>{title}</div>
    {sub ? <div style={{ marginTop: 22, fontFamily: BRAND.font, fontWeight: 760, fontSize: 34, lineHeight: 1.25, color: BRAND.muted }}>{sub}</div> : null}
  </div>
);

const HookScene: React.FC<{ p: SurvivalLabProps }> = ({ p }) => {
  const s = useIn(6, 11);
  return (
    <BrandFrame pageBadge="LAB">
      <div style={{ position: "absolute", top: 330, left: SAFE.side, right: SAFE.side, textAlign: "center", opacity: s, transform: `translateY(${interpolate(s, [0, 1], [30, 0])}px)` }}>
        <Badge>WORLD CUP SURVIVAL LAB</Badge>
        <div style={{ marginTop: 54 }}><TitleLines lines={[p.hook]} size={78} /></div>
        <div style={{ marginTop: 42, fontFamily: BRAND.font, fontWeight: 780, fontSize: 38, lineHeight: 1.26, color: BRAND.muted }}>{p.subtitle}</div>
      </div>
    </BrandFrame>
  );
};

const GroupsScene: React.FC<{ p: SurvivalLabProps }> = ({ p }) => (
  <BrandFrame pageBadge="12">
    <SceneTitle badge="THE FORMAT" title="Twelve groups feed the survival math" />
    <GroupCards groups={p.groups} top={620} />
  </BrandFrame>
);

const TopTwoScene: React.FC = () => (
  <BrandFrame pageBadge="TOP 2">
    <SceneTitle badge="AUTOMATIC PATH" title="First and second are safe" sub="Every group sends its top two forward." />
    <AdvancingTable />
  </BrandFrame>
);

const HiddenTableScene: React.FC = () => (
  <BrandFrame pageBadge="3RD">
    <SceneTitle badge="THE HIDDEN TABLE" title="Third place is not always out" />
    <ThirdPlaceTable />
  </BrandFrame>
);

const DangerScene: React.FC<{ p: SurvivalLabProps }> = ({ p }) => (
  <BrandFrame pageBadge="MATH">
    <SceneTitle badge="DANGER ZONE" title="Small margins can move the table" />
    <DangerList items={p.dangerExamples} />
  </BrandFrame>
);

const CTAScene: React.FC<{ p: SurvivalLabProps }> = ({ p }) => (
  <BrandFrame pageBadge="NEXT">
    <div style={{ position: "absolute", top: 430, left: SAFE.side, right: SAFE.side, textAlign: "center" }}>
      <Badge>DAILY SURVIVAL MATH</Badge>
      <div style={{ marginTop: 52 }}><TitleLines lines={p.titleLines} size={64} /></div>
      <div style={{
        marginTop: 70, background: BRAND.blue, color: "#fff", borderRadius: 18,
        padding: "28px 34px", fontFamily: BRAND.font, fontWeight: 930,
        fontSize: 38, lineHeight: 1.2,
      }}>
        {p.cta}
      </div>
    </div>
  </BrandFrame>
);

export const SurvivalLab: React.FC<SurvivalLabProps> = (p) => {
  const FPS = 30;
  const scenes = [
    <HookScene p={p} />,
    <GroupsScene p={p} />,
    <TopTwoScene />,
    <HiddenTableScene />,
    <DangerScene p={p} />,
    <CTAScene p={p} />,
  ];
  const d = (p.durations && p.durations.length === scenes.length) ? p.durations : [3, 5, 7, 8, 6, 3];
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
