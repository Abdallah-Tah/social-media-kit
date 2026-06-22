import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { THEME, FONT } from "../theme";

// Cards: yellow = caution; two yellows -> red; red = sent off, no replacement.
// In-force (Law 12). Param: sequence (default yellow,yellow,red).
const YELLOW = "#f5c518";

const Card: React.FC<{ color: string; x: number; rot: number; s: number; label: string }> = ({ color, x, rot, s, label }) => (
  <div style={{ position: "absolute", left: x, top: 720, opacity: s, transform: `translateY(${interpolate(s, [0, 1], [60, 0])}px) rotate(${rot}deg) scale(${interpolate(s, [0, 1], [0.7, 1])})` }}>
    <div style={{ width: 210, height: 300, borderRadius: 18, background: color, boxShadow: "0 18px 40px rgba(8,42,96,.28)", border: "4px solid #fff" }} />
    <div style={{ marginTop: 18, textAlign: "center", fontFamily: FONT, fontWeight: 900, fontSize: 32, color: THEME.navy }}>{label}</div>
  </div>
);

export const CardSystem: React.FC<{ params: any }> = ({ params }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const y1 = spring({ frame: f - 8, fps, config: { damping: 12 } });
  const y2 = spring({ frame: f - 40, fps, config: { damping: 12 } });
  const red = spring({ frame: f - 78, fps, config: { damping: 11 } });
  const showRed = f >= 78;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {!showRed ? (
        <>
          <Card color={YELLOW} x={250} rot={-6} s={y1} label="CAUTION" />
          <Card color={YELLOW} x={620} rot={6} s={y2} label="2nd YELLOW" />
        </>
      ) : (
        <>
          <Card color={THEME.red} x={435} rot={0} s={red} label="SENT OFF" />
          <div style={{ position: "absolute", left: 0, right: 0, top: 1140, textAlign: "center", opacity: interpolate(spring({ frame: f - 96, fps, config: { damping: 13 } }), [0, 1], [0, 1]) }}>
            <span style={{ background: THEME.navy, color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 44, padding: "16px 34px", borderRadius: 14 }}>10 vs 11 · no replacement</span>
          </div>
        </>
      )}
    </div>
  );
};
