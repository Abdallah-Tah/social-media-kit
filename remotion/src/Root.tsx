import React from "react";
import { Composition } from "remotion";
import { Short, ShortProps } from "./Short";
import { Prediction, PredictionProps } from "./Prediction";
import { DailySlate, DailyProps } from "./DailySlate";
import { Explainer, ExplainerProps } from "./Explainer";
import { DataDive, DataDiveProps } from "./DataDive";
import { SurvivalLab, SurvivalLabProps } from "./SurvivalLab";
import { RankMeme, RankMemeProps } from "./RankMeme";
import { W, H, FPS } from "./theme";

const EXPLAINER_DEFAULT: ExplainerProps = {
  title: "What is offside?",
  beats: [
    { caption: "", visual: { type: "OffsideLine", params: { defenders: [0.22, 0.42, 0.6, 0.8], secondLastY: 0.34, passer: { x: 0.5, y: 0.82 }, attacker: { x: 0.58, startY: 0.52, endY: 0.22 }, passFrame: 42, verdict: "offside" } } },
  ],
  cta: "Follow for World Cup explainers",
  brand: "light_brand", durations: [6, 4], hasAudio: false, audioFile: "voiceover.mp3",
};

const DAILY_DEFAULT: DailyProps = {
  date: "June 16", teamsToday: [], results: [], matches: [], headline: null,
  modelRecord: "", credits: [], durations: [5, 6, 7, 6, 5],
  hasAudio: false, audioFile: "voiceover.mp3", atmosphere: null,
};

const DATA_DIVE_DEFAULT: DataDiveProps = {
  title: "I simulated the World Cup bracket 10,000 times",
  hook: "One penalty can flip an entire tournament path.",
  beats: [
    "We start with team strength, form, and group-path pressure.",
    "Then we replay each knockout branch thousands of times.",
    "The goal is not certainty. It is finding where chaos matters most.",
  ],
  statCards: [
    { label: "Iterations", value: "10K" },
    { label: "Format", value: "48 teams" },
    { label: "Swing point", value: "R32" },
    { label: "Dark-horse path", value: "alive" },
  ],
  finalCall: "The early knockout round is where the bracket explodes.",
  cta: "Follow for daily World Cup data dives",
  durations: [6, 8, 7, 6],
  hasAudio: false,
  audioFile: "voiceover.mp3",
};

const RANKMEME_DEFAULT: RankMemeProps = {
  imageFile: "scene01-china.png",
  topTitle: "Ranking Best World Cup Teams",
  rankText: "China Team 🇨🇳",
  rankNumber: 4,
  caption: "Number 4… China Team!",
  durationSeconds: 5,
};

const SURVIVAL_DEFAULT: SurvivalLabProps = {
  title: "The 2026 World Cup Has a Hidden Table",
  titleLines: ["The 2026 World Cup", "Has a Hidden Table"],
  hook: "Your team can finish 3rd and still survive.",
  subtitle: "One goal, one draw, or one card can change the knockout path.",
  groups: ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"],
  dangerExamples: ["4 points may be safe", "3 points may need goal difference", "cards can matter if tiebreakers go deep"],
  cta: "Follow BuildWithAbdallah for daily World Cup survival math.",
  durations: [3, 5, 7, 8, 6, 3],
  hasAudio: false,
  audioFile: "voiceover.mp3",
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
    <Composition
      id="Explainer"
      component={Explainer}
      durationInFrames={Math.round(20 * FPS)}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={EXPLAINER_DEFAULT}
      calculateMetadata={({ props }) => {
        const secs = (props.durations || []).reduce((a, b) => a + (b || 5), 0) || 20;
        return { durationInFrames: Math.max(FPS, Math.round(secs * FPS)) };
      }}
    />
    <Composition
      id="DataDive"
      component={DataDive}
      durationInFrames={Math.round(27 * FPS)}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={DATA_DIVE_DEFAULT}
      calculateMetadata={({ props }) => {
        const secs = (props.durations || []).reduce((a, b) => a + (b || 6), 0) || 27;
        return { durationInFrames: Math.max(FPS, Math.round(secs * FPS)) };
      }}
    />
    <Composition
      id="SurvivalLab"
      component={SurvivalLab}
      durationInFrames={Math.round(32 * FPS)}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={SURVIVAL_DEFAULT}
      calculateMetadata={({ props }) => {
        const secs = (props.durations || []).reduce((a, b) => a + (b || 5), 0) || 32;
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
