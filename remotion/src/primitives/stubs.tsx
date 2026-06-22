import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { THEME, FONT } from "../theme";

// Remaining stub: RefereeApproach (for the captain_only topic). To be built out
// later like the other primitives. CardSystem/PenaltySpot/MatchClock/HandballZone
// now live in their own files.
export const RefereeApproach: React.FC<{ params: any }> = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f - 6, fps, config: { damping: 14 } });
  return (
    <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
      <div style={{ opacity: s, transform: `scale(${interpolate(s, [0, 1], [0.85, 1])})`, textAlign: "center" }}>
        <div style={{ display: "flex", gap: 60, justifyContent: "center", alignItems: "center" }}>
          <Figure color={THEME.navy} label="REF" />
          <Figure color={THEME.blue} label="©" />
        </div>
        <div style={{ marginTop: 30, fontFamily: FONT, fontWeight: 800, fontSize: 30, letterSpacing: 4, color: THEME.muted }}>REFEREE APPROACH</div>
        <div style={{ marginTop: 6, fontFamily: FONT, fontSize: 22, color: THEME.muted, opacity: 0.7 }}>primitive — to be built</div>
      </div>
    </div>
  );
};

const Figure: React.FC<{ color: string; label: string }> = ({ color, label }) => (
  <div style={{ display: "grid", placeItems: "center" }}>
    <div style={{ width: 110, height: 110, borderRadius: "50%", background: color, display: "grid", placeItems: "center", color: "#fff", fontFamily: FONT, fontWeight: 900, fontSize: 40, border: "4px solid #fff", boxShadow: "0 8px 20px rgba(8,42,96,.22)" }}>{label}</div>
  </div>
);
