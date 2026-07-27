import React from "react";
import { Composition } from "remotion";
import { Short, ShortProps } from "./Short";
import { RankMeme, RankMemeProps } from "./RankMeme";
import { W, H, FPS } from "./theme";

const RANKMEME_DEFAULT: RankMemeProps = {
  imageFile: "scene01.png",
  topTitle: "AI Projects Exploding on GitHub",
  rankText: "hallmark (+8,948 stars)",
  rankNumber: 2,
  caption: "Number 2… hallmark, +8,948 stars this week.",
  durationSeconds: 5,
};

const DEFAULT: ShortProps = {
  scenes: [
    { kind: "title_card", title: "Build With Abdallah", caption: "Animated brand Shorts via Remotion.", takeaway: "Pass a plan JSON to render any topic." },
    { kind: "cta_card", title: "Full breakdown", caption: "On the site." },
  ],
  durations: [4, 3],
  captions: ["Hello", "Read more"],
  url: "buildwithabdallah.com",
  hasAudio: false,
  audioFile: "voiceover.mp3",
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
    <Composition
      id="Short"
      component={Short}
      durationInFrames={Math.round(7 * FPS)}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={DEFAULT}
      calculateMetadata={({ props }) => {
        const secs = (props.durations || []).reduce((a, b) => a + (b || 4), 0) || 7;
        return { durationInFrames: Math.max(FPS, Math.round(secs * FPS)) };
      }}
    />
    <Composition
      id="RankMemeTest"
      component={RankMeme}
      durationInFrames={Math.round((RANKMEME_DEFAULT.durationSeconds || 5) * FPS)}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={RANKMEME_DEFAULT}
      calculateMetadata={({ props }) => {
        const secs = props.durationSeconds || 5;
        return { durationInFrames: Math.max(FPS, Math.round(secs * FPS)) };
      }}
    />
    </>
  );
};
