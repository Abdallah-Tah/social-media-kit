import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { THEME, FONT } from "../theme";

// Param-driven offside animation (top-down pitch). Geometry only — no rule text.
// params: attackDir ('up'), defenders:number[] (x, 0..1), secondLastY (0..1),
//         passer:{x,y}, attacker:{x,startY,endY}, passFrame, verdict.
export type OffsideParams = {
  attackDir?: "up" | "down";
  defenders: number[];
  secondLastY: number;
  passer: { x: number; y: number };
  attacker: { x: number; startY: number; endY: number };
  passFrame: number;
  verdict?: "offside" | "onside";
  showVerdict?: boolean;
};

// pitch area inside the 1080x1920 frame (sits below the brand header, above
// the Shorts safe zone)
const PX = 80, PY = 440, PW = 920, PH = 1140;
const nx = (x: number) => PX + x * PW;
const ny = (y: number) => PY + y * PH;

const Pitch: React.FC = () => (
  <svg width={1080} height={1920} style={{ position: "absolute", inset: 0 }}>
    <defs>
      <linearGradient id="grass" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#e9f6ee" />
        <stop offset="100%" stopColor="#dcefe3" />
      </linearGradient>
    </defs>
    <rect x={PX} y={PY} width={PW} height={PH} rx={20} fill="url(#grass)" stroke="#bfe0cc" strokeWidth={3} />
    {/* mowing stripes */}
    {Array.from({ length: 8 }).map((_, i) => (
      <rect key={i} x={PX} y={PY + (PH / 8) * i} width={PW} height={PH / 16} fill="#ffffff" opacity={0.18} />
    ))}
    {/* penalty box at the top (attacking end) */}
    <rect x={nx(0.2)} y={PY} width={nx(0.8) - nx(0.2)} height={170} fill="none" stroke="#9ed3b3" strokeWidth={3} />
    <rect x={nx(0.36)} y={PY} width={nx(0.64) - nx(0.36)} height={70} fill="none" stroke="#9ed3b3" strokeWidth={3} />
    {/* halfway line */}
    <line x1={PX} y1={PY + PH} x2={PX + PW} y2={PY + PH} stroke="#bfe0cc" strokeWidth={3} />
  </svg>
);

const Dot: React.FC<{ x: number; y: number; color: string; r?: number; label?: string }> = ({ x, y, color, r = 22, label }) => (
  <div style={{ position: "absolute", left: nx(x) - r, top: ny(y) - r, width: r * 2, height: r * 2, borderRadius: "50%", background: color, border: "4px solid #fff", boxShadow: "0 6px 16px rgba(8,42,96,.28)", display: "grid", placeItems: "center", color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 22 }}>{label}</div>
);

export const OffsideLine: React.FC<{ params: OffsideParams }> = ({ params }) => {
  const f = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const passFrame = params.passFrame ?? 42;
  const verdict = params.verdict ?? "offside";
  const showVerdict = params.showVerdict !== false;

  // attacker runs from startY toward endY, reaching ~endY by the pass moment then drifting on
  const preRun = interpolate(f, [0, passFrame], [params.attacker.startY, params.attacker.endY], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const postRun = interpolate(f, [passFrame, durationInFrames], [params.attacker.endY, params.attacker.endY - 0.08], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const attY = f < passFrame ? preRun : postRun;

  // ball travels from passer to the attacker's freeze position after the pass
  const freezeY = interpolate(passFrame, [0, passFrame], [params.attacker.startY, params.attacker.endY]);
  const ballT = interpolate(f, [passFrame, passFrame + 22], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const ballX = interpolate(ballT, [0, 1], [params.passer.x, params.attacker.x]);
  const ballY = interpolate(ballT, [0, 1], [params.passer.y, freezeY]);

  // offside line draws across at the moment of the pass
  const lineGrow = spring({ frame: f - passFrame, fps, config: { damping: 18, mass: 0.6 } });
  const lineW = interpolate(lineGrow, [0, 1], [0, PW]);
  const lineColor = verdict === "offside" ? THEME.red : "#1a9e5f";
  const lineY = ny(params.secondLastY);

  // verdict badge after the line is drawn
  const vb = spring({ frame: f - (passFrame + 14), fps, config: { damping: 13 } });

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <Pitch />
      {/* offside line + tint of the offside zone */}
      {f >= passFrame ? (
        <>
          <div style={{ position: "absolute", left: PX, top: PY, width: lineW, height: Math.max(0, lineY - PY), background: lineColor, opacity: 0.07 }} />
          <div style={{ position: "absolute", left: PX, top: lineY - 3, width: lineW, height: 6, background: lineColor, boxShadow: `0 0 14px ${lineColor}` }} />
        </>
      ) : null}
      {/* second-last defender freeze marker */}
      {f >= passFrame ? (
        <div style={{ position: "absolute", left: nx(params.defenders[1]) - 30, top: lineY - 30, width: 60, height: 60, borderRadius: "50%", border: `4px dashed ${lineColor}` }} />
      ) : null}

      {/* defenders on the line */}
      {params.defenders.map((dx, i) => <Dot key={i} x={dx} y={params.secondLastY + (i === 1 ? 0 : 0.02 * ((i % 2) ? 1 : -1))} color={THEME.navy} label="D" />)}
      {/* passer + attacker + ball */}
      <Dot x={params.passer.x} y={params.passer.y} color="#0866ff" label="P" />
      <Dot x={params.attacker.x} y={attY} color={f >= passFrame ? lineColor : "#0866ff"} label="A" />
      {f >= passFrame ? <Dot x={ballX} y={ballY} color="#ffffff" r={12} /> : <Dot x={params.passer.x} y={params.passer.y - 0.02} color="#ffffff" r={12} />}

      {/* verdict pill (scenario outcome shown by the geometry — not a rule claim) */}
      {showVerdict && f >= passFrame + 10 ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: PY - 96, textAlign: "center", opacity: vb, transform: `scale(${interpolate(vb, [0, 1], [0.7, 1])})` }}>
          <span style={{ background: lineColor, color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 60, letterSpacing: 1, padding: "16px 46px", borderRadius: 18, boxShadow: "0 14px 30px rgba(8,42,96,.25)" }}>
            {verdict === "offside" ? "OFFSIDE" : "ONSIDE"}
          </span>
        </div>
      ) : null}
    </div>
  );
};
