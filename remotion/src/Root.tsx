import React from "react";
import { Composition } from "remotion";
import { Short, ShortProps } from "./Short";
import { Prediction, PredictionProps } from "./Prediction";
import { DailySlate, DailyProps } from "./DailySlate";
import { W, H, FPS } from "./theme";

const DAILY_DEFAULT: DailyProps = {
  date: "June 16", teamsToday: [], results: [], matches: [], headline: null,
  modelRecord: "", credits: [], durations: [5, 6, 7, 6, 5],
  hasAudio: false, audioFile: "voiceover.mp3", atmosphere: null,
};

const PRED_DEFAULT: PredictionProps = {
  home: "Iran", away: "New Zealand", competition: "World Cup 2026",
  hook: "Our model sees one clear edge.",
  lean: "Iran 1 – 0 New Zealand", confidence: "Slight Iran edge",
  reasons: ["Defensive structure", "Transition risk", "First goal matters"],
  probs: { homeP: 46, drawP: 30, awayP: 24 },
  factors: ["Group stage pressure", "First goal changes the game", "Iran rate higher in our model", "New Zealand threaten in transition"],
  finalCall: "Iran 1 – 0",
  durations: [4, 6, 6, 6, 5], hasAudio: false, audioFile: "voiceover.mp3",
  homeFlag: "flag_home.png", awayFlag: "flag_away.png",
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
      id="Prediction"
      component={Prediction}
      durationInFrames={Math.round(27 * FPS)}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={PRED_DEFAULT}
      calculateMetadata={({ props }) => {
        const secs = (props.durations || []).reduce((a, b) => a + (b || 5), 0) || 27;
        return { durationInFrames: Math.max(FPS, Math.round(secs * FPS)) };
      }}
    />
    <Composition
      id="DailySlate"
      component={DailySlate}
      durationInFrames={Math.round(29 * FPS)}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={DAILY_DEFAULT}
      calculateMetadata={({ props }) => {
        const secs = (props.durations || []).reduce((a, b) => a + (b || 6), 0) || 29;
        return { durationInFrames: Math.max(FPS, Math.round(secs * FPS)) };
      }}
    />
    </>
  );
};
