import React from "react";
import { AbsoluteFill, Img, staticFile, interpolate, useCurrentFrame, Easing } from "remotion";
import { W, H, FPS } from "./theme";

export type RankMemeProps = {
  imageFile: string; // file name inside public/
  topTitle: string;
  rankText: string;
  rankNumber: number;
  caption: string;
  durationSeconds: number;
};

const rankColors: Record<number, string> = {
  1: "#e63946",
  2: "#9d4edd",
  3: "#ffcc00",
  4: "#f77f00",
  5: "#06d6a0",
};

export const RankMeme: React.FC<RankMemeProps> = ({
  imageFile,
  topTitle,
  rankText,
  rankNumber,
  caption,
  durationSeconds,
}) => {
  const frame = useCurrentFrame();
  const totalFrames = Math.round(durationSeconds * FPS);

  // Slow zoom on the source image
  const zoom = interpolate(frame, [0, totalFrames], [1, 1.08], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.ease),
  });

  // Rank badge pop-in at frame 12 (0.4s)
  const badgeStart = 12;
  const badgePop = interpolate(frame, [badgeStart, badgeStart + 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.back(1.7)),
  });

  // Caption fade in at frame 24 (0.8s)
  const captionOpacity = interpolate(frame, [24, 32], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const rankColor = rankColors[rankNumber] || "#fff";

  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0a0a", overflow: "hidden" }}>
      <Img
        src={staticFile(imageFile)}
        style={{
          width: W,
          height: H,
          objectFit: "cover",
          transform: `scale(${zoom})`,
        }}
      />
      {/* Top title bar */}
      <div
        style={{
          position: "absolute",
          top: 40,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: "Arial Black, sans-serif",
          fontWeight: 900,
          fontSize: 48,
          textShadow: "0 3px 8px rgba(0,0,0,0.8)",
          color: "#fff",
          padding: "0 30px",
        }}
      >
        {topTitle}
      </div>

      {/* Ranking badge */}
      <div
        style={{
          position: "absolute",
          left: 50,
          top: 260,
          transform: `scale(${badgePop})`,
          transformOrigin: "left center",
          backgroundColor: "rgba(0,0,0,0.55)",
          borderLeft: `10px solid ${rankColor}`,
          borderRadius: 14,
          padding: "18px 28px",
          display: "flex",
          alignItems: "center",
          gap: 16,
          boxShadow: "0 6px 20px rgba(0,0,0,0.5)",
        }}
      >
        <span
          style={{
            fontFamily: "Arial Black, sans-serif",
            fontSize: 72,
            color: rankColor,
            lineHeight: 1,
          }}
        >
          {rankNumber}
        </span>
        <span
          style={{
            fontFamily: "Arial Black, sans-serif",
            fontSize: 42,
            color: "#fff",
            lineHeight: 1,
          }}
        >
          {rankText}
        </span>
      </div>

      {/* Caption / VO line */}
      <div
        style={{
          position: "absolute",
          bottom: 140,
          left: 0,
          right: 0,
          textAlign: "center",
          opacity: captionOpacity,
          fontFamily: "Arial, sans-serif",
          fontSize: 38,
          fontWeight: 700,
          color: "#fff",
          textShadow: "0 2px 6px rgba(0,0,0,0.9)",
          padding: "0 40px",
        }}
      >
        {caption}
      </div>
    </AbsoluteFill>
  );
};
