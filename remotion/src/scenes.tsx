import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { THEME, FONT } from "./theme";

// ---- shared chrome (header / watermark / progress / caption) ----------------

const Header: React.FC<{ index: number; total: number }> = ({ index, total }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        top: 70,
        left: 86,
        right: 86,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        opacity: o,
        fontFamily: FONT,
      }}
    >
      <div style={{ fontWeight: 800, fontSize: 36, color: THEME.ink }}>
        Build With <span style={{ color: THEME.blue }}>Abdallah</span>
      </div>
      <div style={{ fontWeight: 800, fontSize: 34, color: THEME.blue }}>
        {index}/{total}
      </div>
    </div>
  );
};

const Watermark: React.FC = () => (
  <div
    style={{
      position: "absolute",
      right: 56,
      bottom: 52,
      width: 104,
      height: 104,
      borderRadius: 22,
      background: "#fff",
      border: `4px solid ${THEME.blue}`,
      display: "grid",
      placeItems: "center",
      boxShadow: "0 10px 26px rgba(8,42,96,.16)",
      fontFamily: FONT,
      fontWeight: 900,
      fontSize: 56,
      color: THEME.navy,
    }}
  >
    A
  </div>
);

const Dots: React.FC = () => (
  <div style={{ position: "absolute", left: 60, bottom: 70, display: "grid", gridTemplateColumns: "repeat(6,12px)", gap: 9, opacity: 0.5 }}>
    {Array.from({ length: 24 }).map((_, i) => (
      <div key={i} style={{ width: 7, height: 7, borderRadius: "50%", background: THEME.blue }} />
    ))}
  </div>
);

// animated brand background — two slow-drifting soft blobs on white
const Backdrop: React.FC = () => {
  const f = useCurrentFrame();
  const dx = Math.sin(f / 60) * 40;
  const dy = Math.cos(f / 70) * 36;
  return (
    <AbsoluteFill style={{ background: THEME.bgGrad }}>
      <div style={{ position: "absolute", top: -120 + dy, right: -120 + dx, width: 520, height: 520, borderRadius: "50%", background: "radial-gradient(circle,rgba(8,102,255,.12),transparent 70%)" }} />
      <div style={{ position: "absolute", bottom: -160 - dy, left: -120 - dx, width: 560, height: 560, borderRadius: "50%", background: "radial-gradient(circle,rgba(8,102,255,.08),transparent 70%)" }} />
      {/* top-right brand triangle */}
      <div style={{ position: "absolute", top: 0, right: 0, width: 0, height: 0, borderTop: "220px solid rgba(8,102,255,.10)", borderLeft: "220px solid transparent" }} />
    </AbsoluteFill>
  );
};

const CaptionBar: React.FC<{ text?: string }> = ({ text }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!text) return null;
  const s = spring({ frame: f - 6, fps, config: { damping: 14, mass: 0.6 } });
  const y = interpolate(s, [0, 1], [40, 0]);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        right: 80,
        bottom: 300,
        display: "flex",
        justifyContent: "center",
        opacity: s,
        transform: `translateY(${y}px)`,
      }}
    >
      <div
        style={{
          background: THEME.blue,
          color: "#fff",
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 46,
          padding: "20px 38px",
          borderRadius: 18,
          textAlign: "center",
          boxShadow: "0 14px 30px rgba(8,102,255,.30)",
        }}
      >
        {text}
      </div>
    </div>
  );
};

const Frame: React.FC<{ index: number; total: number; caption?: string; children: React.ReactNode }> = ({ index, total, caption, children }) => (
  <AbsoluteFill style={{ fontFamily: FONT }}>
    <Backdrop />
    <Header index={index} total={total} />
    {children}
    <CaptionBar text={caption} />
    <Dots />
    <Watermark />
  </AbsoluteFill>
);

// ---- scene types ------------------------------------------------------------

export type Scene = {
  kind: string;
  title?: string;
  caption?: string;
  takeaway?: string;
  diagram?: string[];
};

const useIn = (delay = 0, damping = 14) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - delay, fps, config: { damping, mass: 0.7 } });
};

const TitleCard: React.FC<{ s: Scene; index: number; total: number; caption?: string }> = ({ s, index, total, caption }) => {
  const a = useIn(4);
  const b = useIn(14);
  const barH = interpolate(a, [0, 1], [0, 170]);
  return (
    <Frame index={index} total={total} caption={caption}>
      <div style={{ position: "absolute", top: 560, left: 96, right: 96 }}>
        <div style={{ display: "flex", gap: 30 }}>
          <div style={{ width: 12, height: barH, background: THEME.blue, borderRadius: 6, marginTop: 8 }} />
          <h1 style={{ margin: 0, fontSize: 92, lineHeight: 1.04, letterSpacing: -2, color: THEME.navy, fontWeight: 900, opacity: a, transform: `translateY(${interpolate(a, [0, 1], [40, 0])}px)` }}>
            {s.title}
          </h1>
        </div>
        <div style={{ marginTop: 40, fontSize: 46, lineHeight: 1.24, color: THEME.muted, opacity: b, transform: `translateY(${interpolate(b, [0, 1], [30, 0])}px)` }}>
          {s.caption}
        </div>
      </div>
      {s.takeaway ? (
        <div style={{ position: "absolute", left: 96, right: 96, bottom: 470, fontSize: 38, color: THEME.ink, borderTop: `4px solid ${THEME.line}`, paddingTop: 28, opacity: interpolate(useIn(24), [0, 1], [0, 1]) }}>
          {s.takeaway}
        </div>
      ) : null}
    </Frame>
  );
};

const DiagramCard: React.FC<{ s: Scene; index: number; total: number; caption?: string }> = ({ s, index, total, caption }) => {
  const head = useIn(4);
  const nodes = s.diagram || [];
  return (
    <Frame index={index} total={total} caption={caption}>
      <div style={{ position: "absolute", top: 230, left: 74, right: 74 }}>
        <h1 style={{ margin: 0, fontSize: 66, color: THEME.navy, fontWeight: 900, opacity: head, transform: `translateX(${interpolate(head, [0, 1], [-30, 0])}px)` }}>{s.title}</h1>
        <div style={{ marginTop: 16, fontSize: 38, color: THEME.muted, opacity: useIn(12) }}>{s.caption}</div>
        <div style={{ marginTop: 56, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
          {nodes.map((n, i) => {
            const sp = useIn(24 + i * 14, 12);
            return (
              <React.Fragment key={i}>
                <div style={{ width: 820, minHeight: 120, borderRadius: 16, background: "#fff", border: `3px solid ${THEME.line}`, boxShadow: "0 10px 26px rgba(8,42,96,.10)", display: "grid", placeItems: "center", padding: 24, fontSize: 44, fontWeight: 800, color: THEME.navy, opacity: sp, transform: `scale(${interpolate(sp, [0, 1], [0.85, 1])})` }}>
                  {n}
                </div>
                {i < nodes.length - 1 ? (
                  <div style={{ fontSize: 56, color: THEME.blue, fontWeight: 900, opacity: useIn(30 + i * 14) }}>↓</div>
                ) : null}
              </React.Fragment>
            );
          })}
        </div>
      </div>
      {s.takeaway ? (
        <div style={{ position: "absolute", left: 74, right: 74, bottom: 470, fontSize: 36, color: THEME.ink, borderTop: `4px solid ${THEME.blue}`, paddingTop: 26, opacity: useIn(40) }}>{s.takeaway}</div>
      ) : null}
    </Frame>
  );
};

const MistakeFix: React.FC<{ s: Scene; index: number; total: number; caption?: string }> = ({ s, index, total, caption }) => {
  const head = useIn(4);
  const m = useIn(16, 13);
  const fx = useIn(30, 13);
  return (
    <Frame index={index} total={total} caption={caption}>
      <div style={{ position: "absolute", top: 320, left: 72, right: 72 }}>
        <h1 style={{ margin: "0 0 48px", fontSize: 68, color: THEME.navy, fontWeight: 900, opacity: head }}>{s.title}</h1>
        <div style={{ borderRadius: 16, border: `3px solid #f3c7c7`, background: THEME.redSoft, padding: 44, opacity: m, transform: `translateX(${interpolate(m, [0, 1], [-60, 0])}px)` }}>
          <div style={{ fontSize: 32, fontWeight: 900, color: THEME.red, marginBottom: 22 }}>THE TRAP</div>
          <div style={{ fontSize: 46, lineHeight: 1.22, color: THEME.ink }}>{s.caption}</div>
        </div>
        <div style={{ marginTop: 44, borderRadius: 16, border: `3px solid #cfe0ff`, background: THEME.blueSoft, padding: 44, opacity: fx, transform: `translateX(${interpolate(fx, [0, 1], [60, 0])}px)` }}>
          <div style={{ fontSize: 32, fontWeight: 900, color: THEME.blue, marginBottom: 22 }}>THE FIX</div>
          <div style={{ fontSize: 42, lineHeight: 1.22, color: THEME.muted }}>{s.takeaway}</div>
        </div>
      </div>
    </Frame>
  );
};

const CtaCard: React.FC<{ s: Scene; index: number; total: number; caption?: string; url: string }> = ({ s, index, total, caption, url }) => {
  const head = useIn(4);
  const pill = useIn(20, 11);
  const f = useCurrentFrame();
  const pulse = 1 + Math.sin(f / 8) * 0.015;
  return (
    <Frame index={index} total={total} caption={caption}>
      <div style={{ position: "absolute", top: 560, left: 96, right: 96 }}>
        <h1 style={{ margin: "0 0 36px", fontSize: 80, color: THEME.navy, fontWeight: 900, opacity: head, transform: `translateY(${interpolate(head, [0, 1], [40, 0])}px)` }}>{s.title}</h1>
        <div style={{ fontSize: 46, color: THEME.muted, opacity: useIn(12) }}>{s.caption}</div>
      </div>
      <div style={{ position: "absolute", left: 96, right: 96, bottom: 470, opacity: pill, transform: `scale(${interpolate(pill, [0, 1], [0.8, 1]) * pulse})` }}>
        <div style={{ background: THEME.blue, color: "#fff", fontSize: 44, fontWeight: 900, borderRadius: 18, padding: "30px 50px", textAlign: "center", boxShadow: "0 16px 34px rgba(8,102,255,.34)" }}>
          Read the full breakdown
        </div>
        <div style={{ marginTop: 26, color: THEME.blue, fontSize: 32, fontWeight: 800, textAlign: "center", textDecoration: "underline", overflowWrap: "anywhere" }}>{url}</div>
      </div>
    </Frame>
  );
};

export const SceneView: React.FC<{ scene: Scene; index: number; total: number; caption?: string; url: string }> = ({ scene, index, total, caption, url }) => {
  const k = scene.kind;
  if (k === "architecture_diagram") return <DiagramCard s={scene} index={index} total={total} caption={caption} />;
  if (k === "mistake_fix") return <MistakeFix s={scene} index={index} total={total} caption={caption} />;
  if (k === "cta_card") return <CtaCard s={scene} index={index} total={total} caption={caption} url={url} />;
  return <TitleCard s={scene} index={index} total={total} caption={caption} />;
};
