import React from "react";
import { AbsoluteFill, Audio, staticFile } from "remotion";
import { THEME } from "../theme";
import { KeyFactorMystery, KeyFactorMysteryProps } from "./variants/KeyFactorMystery";
import { MatchTension, MatchTensionProps } from "./variants/MatchTension";
import { ResultCuriosity, ResultCuriosityProps } from "./variants/ResultCuriosity";
import { ProgressBar } from "./components";

export type PredictionShortVariant = "key-factor-mystery" | "match-tension" | "result-curiosity";

export type PredictionShortProps = {
  variant: PredictionShortVariant;
  home: string;
  away: string;
  competition: string;
  homeFlag: string;
  awayFlag: string;
  leader: string;
  confidence: number;
  winProb: number;
  drawProb: number;
  lossProb: number;
  verdict: string;
  credibilityChip: string;
  hook: string;
  subheadline: string;
  factorLabel: string;
  factors: string[];
  tensionLabel?: string;
  tensionFactors?: string[];
  cta: string;
  durations: number[];
  hasAudio: boolean;
  audioFile: string;
};

export const PredictionShort: React.FC<PredictionShortProps> = (p) => {
  const FPS = 30;
  const d = p.durations && p.durations.length === 5 ? p.durations : [2, 4, 7, 4, 3];
  const frames = d.map((x) => Math.max(1, Math.round(x * FPS)));

  const common = {
    home: p.home,
    away: p.away,
    competition: p.competition,
    homeFlag: p.homeFlag,
    awayFlag: p.awayFlag,
    leader: p.leader,
    confidence: p.confidence,
    winProb: p.winProb,
    drawProb: p.drawProb,
    lossProb: p.lossProb,
    verdict: p.verdict,
    credibilityChip: p.credibilityChip,
    cta: p.cta,
    frames,
  };

  return (
    <AbsoluteFill style={{ backgroundColor: THEME.bg }}>
      {p.variant === "key-factor-mystery" && (
        <KeyFactorMystery
          {...common}
          hook={p.hook}
          subheadline={p.subheadline}
          factorLabel={p.factorLabel}
          factors={p.factors}
        />
      )}
      {p.variant === "match-tension" && (
        <MatchTension
          {...common}
          hook={p.hook}
          subheadline={p.subheadline}
          tensionLabel={p.tensionLabel || "TIGHT MATCHUP"}
          tensionFactors={p.tensionFactors || p.factors}
        />
      )}
      {p.variant === "result-curiosity" && (
        <ResultCuriosity
          {...common}
          hook={p.hook}
          subheadline={p.subheadline}
          factorLabel={p.factorLabel}
          factors={p.factors}
        />
      )}
      <ProgressBar />
      {p.hasAudio ? <Audio src={staticFile(p.audioFile)} /> : null}
    </AbsoluteFill>
  );
};
