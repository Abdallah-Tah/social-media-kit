import React from "react";
import { AbsoluteFill, Audio, Series, staticFile } from "remotion";
import { FPS } from "./theme";
import { Scene, SceneView } from "./scenes";

export type ShortProps = {
  scenes: Scene[];
  durations: number[]; // seconds per scene
  captions: string[];
  url: string;
  hasAudio: boolean;
  audioFile: string; // file name inside public/
};

export const Short: React.FC<ShortProps> = ({ scenes, durations, captions, url, hasAudio, audioFile }) => {
  const total = scenes.length;
  return (
    <AbsoluteFill style={{ backgroundColor: "#f8fbff" }}>
      <Series>
        {scenes.map((scene, i) => (
          <Series.Sequence key={i} durationInFrames={Math.max(1, Math.round((durations[i] || 4) * FPS))}>
            <SceneView scene={scene} index={i + 1} total={total} caption={captions[i]} url={url} />
          </Series.Sequence>
        ))}
      </Series>
      {hasAudio ? <Audio src={staticFile(audioFile)} /> : null}
    </AbsoluteFill>
  );
};
