import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { THEME, FONT } from "../theme";

// MatchClock — two modes:
//  gk8 (Law 12, NEW 2025/26): keeper may hold 8s; longer -> CORNER. Ref counts
//      down the last 5s by hand.
//  stoppage (Law 7): added time accumulates on the 4th-official board.
const CX = 540;

const Ring: React.FC<{ p: number; color: string; n: string; sub: string }> = ({ p, color, n, sub }) => {
  const R = 210, C = 2 * Math.PI * R;
  return (
    <svg width={1080} height={620} style={{ position: "absolute", top: 470, left: 0 }}>
      <circle cx={CX} cy={310} r={R} fill="#fff" stroke="#e3ebf6" strokeWidth={26} />
      <circle cx={CX} cy={310} r={R} fill="none" stroke={color} strokeWidth={26} strokeLinecap="round"
        strokeDasharray={C} strokeDashoffset={C * (1 - p)} transform={`rotate(-90 ${CX} 310)`} />
      <text x={CX} y={300} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={180} fill={THEME.navy}>{n}</text>
      <text x={CX} y={380} textAnchor="middle" fontFamily={FONT} fontWeight={800} fontSize={40} fill={THEME.muted}>{sub}</text>
    </svg>
  );
};

const Stamp: React.FC<{ text: string; color: string; show: boolean }> = ({ text, color, show }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  const s = spring({ frame: f - 86, fps, config: { damping: 13 } });
  if (!show) return null;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 380, textAlign: "center", opacity: s, transform: `scale(${interpolate(s, [0, 1], [0.7, 1])})` }}>
      <span style={{ background: color, color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 56, padding: "16px 44px", borderRadius: 16 }}>{text}</span>
    </div>
  );
};

export const MatchClock: React.FC<{ params: any }> = ({ params }) => {
  const f = useCurrentFrame();
  const mode = params?.mode || "stoppage";

  if (mode === "gk8") {
    const held = Math.min(8, interpolate(f, [0, 96], [0, 8], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
    const last5 = held >= 3 && held < 8 ? Math.ceil(8 - held) : 0;  // hand counts 5..1
    const over = f >= 100;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <Ring p={held / 8} color={over ? THEME.red : THEME.blue} n={`${Math.floor(held)}s`} sub="ball in hands" />
        {last5 > 0 && !over ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 1130, textAlign: "center", fontFamily: FONT, fontWeight: 900, fontSize: 44, color: THEME.blue }}>✋ ref counts {last5}</div>
        ) : null}
        <Stamp text="8s+ → CORNER" color={THEME.red} show={over} />
      </div>
    );
  }

  // stoppage
  const added = Math.round(interpolate(f, [10, 90], [0, 6], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const chips = ["Subs", "Injury", "VAR", "Celebrations"];
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 430, textAlign: "center", fontFamily: FONT, fontWeight: 900, fontSize: 150, letterSpacing: -4, color: THEME.navy }}>90:00</div>
      <Ring p={added / 6} color={THEME.blue} n={`+${added}`} sub="added time" />
      <div style={{ position: "absolute", left: 80, right: 80, top: 1170, display: "flex", flexWrap: "wrap", gap: 16, justifyContent: "center" }}>
        {chips.map((c, i) => {
          const o = interpolate(f, [20 + i * 14, 30 + i * 14], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          return <span key={i} style={{ opacity: o, background: "#fff", border: `3px solid ${THEME.line}`, borderRadius: 999, padding: "14px 26px", fontFamily: FONT, fontWeight: 700, fontSize: 30, color: THEME.ink }}>{c}</span>;
        })}
      </div>
    </div>
  );
};
