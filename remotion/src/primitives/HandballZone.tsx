import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { THEME, FONT } from "../theme";

// Handball (Law 12): offence if deliberate or the arm makes the body
// "unnaturally bigger"; boundary ~ bottom of the armpit. Param: verdict
// (handball|no), default handball.
export const HandballZone: React.FC<{ params: any }> = ({ params }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const verdict = params?.verdict || "handball";
  const handball = verdict === "handball";
  const cx = 470, headY = 560, boundaryY = 760; // armpit boundary line

  // arm angle: handball = raised/extended (above boundary); no = down/natural
  const raise = spring({ frame: f - 14, fps, config: { damping: 14 } });
  const armAngle = handball ? interpolate(raise, [0, 1], [25, -38]) : interpolate(raise, [0, 1], [25, 12]);

  // ball flies toward the arm
  const kick = spring({ frame: f - 44, fps, config: { damping: 16, mass: 0.8 } });
  const ballX = interpolate(kick, [0, 1], [980, cx + 150]);
  const ballY = interpolate(kick, [0, 1], [520, handball ? 660 : 880]);
  const col = handball ? THEME.red : "#1a9e5f";

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <svg width={1080} height={1920} style={{ position: "absolute", inset: 0 }}>
        {/* body */}
        <circle cx={cx} cy={headY} r={52} fill={THEME.navy} />
        <rect x={cx - 60} y={headY + 52} width={120} height={300} rx={36} fill={THEME.navy} />
        {/* arm (rotates from shoulder) */}
        <g transform={`rotate(${armAngle} ${cx + 50} ${headY + 120})`}>
          <rect x={cx + 50} y={headY + 100} width={260} height={40} rx={20} fill="#274a86" />
        </g>
        {/* armpit boundary */}
        <line x1={120} y1={boundaryY} x2={960} y2={boundaryY} stroke={THEME.muted} strokeWidth={3} strokeDasharray="14 12" />
      </svg>
      <div style={{ position: "absolute", left: 130, top: boundaryY - 44, fontFamily: FONT, fontWeight: 800, fontSize: 26, color: THEME.muted }}>armpit line</div>
      {/* ball */}
      <div style={{ position: "absolute", left: ballX - 16, top: ballY - 16, width: 32, height: 32, borderRadius: "50%", background: "#fff", border: `2px solid ${THEME.navy}` }} />
      {/* verdict */}
      {f >= 78 ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: 360, textAlign: "center", opacity: interpolate(spring({ frame: f - 78, fps, config: { damping: 13 } }), [0, 1], [0, 1]) }}>
          <span style={{ background: col, color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 56, padding: "16px 44px", borderRadius: 16 }}>{handball ? "HANDBALL" : "NO HANDBALL"}</span>
        </div>
      ) : null}
    </div>
  );
};
