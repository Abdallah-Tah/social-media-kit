import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { THEME, FONT } from "../theme";

// Penalty (Law 14): spot kick from ~12 yds, keeper on the line, everyone else
// outside the box + arc. In-force only — does NOT depict the "dead ball after a
// save" proposal. Param: verdict (goal|save), default goal.
const PX = 110, PY = 470, PW = 860, GOAL_Y = 470;

export const PenaltySpot: React.FC<{ params: any }> = ({ params }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const verdict = params?.verdict || "goal";
  const cx = PX + PW / 2;
  const spotY = PY + 360;            // penalty spot
  const kick = spring({ frame: f - 50, fps, config: { damping: 16, mass: 0.8 } });
  // ball travels from spot into the goal (top), keeper dives aside
  const ballY = interpolate(kick, [0, 1], [spotY, GOAL_Y + 24]);
  const ballX = interpolate(kick, [0, 1], [cx, cx + (verdict === "goal" ? 150 : 60)]);
  const keeperX = interpolate(kick, [0, 1], [cx, cx + (verdict === "goal" ? -150 : 150)]);

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <svg width={1080} height={1920} style={{ position: "absolute", inset: 0 }}>
        <rect x={PX} y={PY} width={PW} height={1020} rx={16} fill="#e9f6ee" stroke="#bfe0cc" strokeWidth={3} />
        {/* goal */}
        <rect x={cx - 200} y={GOAL_Y - 26} width={400} height={26} fill="#fff" stroke={THEME.navy} strokeWidth={5} />
        {/* 18-yard box */}
        <rect x={PX + 70} y={GOAL_Y} width={PW - 140} height={520} fill="none" stroke="#9ed3b3" strokeWidth={3} />
        {/* 6-yard box */}
        <rect x={cx - 200} y={GOAL_Y} width={400} height={190} fill="none" stroke="#9ed3b3" strokeWidth={3} />
        {/* penalty arc */}
        <path d={`M ${cx - 130} ${spotY + 70} A 150 150 0 0 0 ${cx + 130} ${spotY + 70}`} fill="none" stroke="#9ed3b3" strokeWidth={3} />
        {/* spot */}
        <circle cx={cx} cy={spotY} r={7} fill={THEME.navy} />
      </svg>
      {/* keeper on the line */}
      <Dot x={keeperX} y={GOAL_Y + 4} color="#0866ff" label="GK" />
      {/* taker */}
      <Dot x={cx} y={spotY + 120} color={THEME.navy} label="" r={20} />
      {/* ball */}
      <div style={{ position: "absolute", left: ballX - 13, top: ballY - 13, width: 26, height: 26, borderRadius: "50%", background: "#fff", border: `2px solid ${THEME.navy}` }} />
      {/* 12 yards label */}
      <div style={{ position: "absolute", left: cx + 24, top: spotY - 18, fontFamily: FONT, fontWeight: 800, fontSize: 26, color: THEME.muted }}>~12 yds</div>
      {/* verdict */}
      {f >= 80 ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: PY - 92, textAlign: "center", opacity: interpolate(spring({ frame: f - 80, fps, config: { damping: 13 } }), [0, 1], [0, 1]) }}>
          <span style={{ background: verdict === "goal" ? "#1a9e5f" : THEME.navy, color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 52, padding: "14px 40px", borderRadius: 16 }}>{verdict === "goal" ? "GOAL" : "SAVED"}</span>
        </div>
      ) : null}
    </div>
  );
};

const Dot: React.FC<{ x: number; y: number; color: string; label: string; r?: number }> = ({ x, y, color, label, r = 24 }) => (
  <div style={{ position: "absolute", left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: "50%", background: color, border: "4px solid #fff", boxShadow: "0 6px 16px rgba(8,42,96,.25)", display: "grid", placeItems: "center", color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 22 }}>{label}</div>
);
