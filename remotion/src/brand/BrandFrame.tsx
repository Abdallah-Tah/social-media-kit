import React from "react";
import { AbsoluteFill, interpolate, staticFile, useCurrentFrame } from "remotion";
import { BRAND, CHROME } from "./tokens";

// Shared Pitch Agent brand frame (9:16) — reproduces the prediction/social
// card chrome: gradient bg, faint "A" watermark, two rounded navy→navy-2
// corner blocks (top-right + bottom-left) with a blue border, two dot grids,
// the header lockup, and the football footer. Pillar bodies render in {children}.

const DotGrid: React.FC<{ pos: "tl" | "br" }> = ({ pos }) => {
  const style: React.CSSProperties = pos === "tl"
    ? { top: 40, left: 40 }
    : { right: 46, bottom: 320 }; // kept above the Shorts UI safe zone
  return (
    <div style={{ position: "absolute", display: "grid", gridTemplateColumns: `repeat(${CHROME.dotCols}, ${CHROME.dotSize}px)`, gap: CHROME.dotGap, opacity: CHROME.dotOpacity, ...style }}>
      {Array.from({ length: CHROME.dotCols * 4 }).map((_, i) => (
        <span key={i} style={{ width: CHROME.dotSize, height: CHROME.dotSize, borderRadius: "50%", background: BRAND.dot }} />
      ))}
    </div>
  );
};

const CornerBlock: React.FC<{ where: "tr" | "bl" }> = ({ where }) => {
  const base: React.CSSProperties = {
    position: "absolute", width: CHROME.cornerSize, height: CHROME.cornerSize,
    background: `linear-gradient(135deg, ${BRAND.navy} 0%, ${BRAND.navy2} 100%)`,
    border: `${CHROME.cornerBorder}px solid ${BRAND.blue}`,
    boxShadow: "0 18px 35px rgba(7,26,68,.18)", borderRadius: CHROME.cornerRadius,
  };
  const pos: React.CSSProperties = where === "tr"
    ? { top: -100, right: -100, transform: "rotate(30deg)" }
    : { bottom: -104, left: -104, transform: "rotate(63deg)" };
  return <div style={{ ...base, ...pos }} />;
};

const Header: React.FC<{ pageBadge?: string }> = ({ pageBadge }) => (
  <div style={{ position: "absolute", top: 92, left: 80, right: 80, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
      {/* Real Build With Abdallah logo mark */}
      <img src={staticFile(BRAND.logoFile)} alt="Build With Abdallah" style={{ width: 78, height: 78, objectFit: "contain" }} />
      <div style={{ width: 2, height: 70, background: BRAND.blue, opacity: 0.75 }} />
      <div>
        <div style={{ fontFamily: BRAND.font, fontSize: 38, fontWeight: 850, letterSpacing: -1, color: BRAND.navy, lineHeight: 1 }}>
          {BRAND.brandName[0]}<span style={{ color: BRAND.blue }}>{BRAND.brandName[1]}</span>
        </div>
        <div style={{ fontFamily: BRAND.font, fontSize: 17, fontWeight: 750, letterSpacing: 4, textTransform: "uppercase", color: BRAND.navy, marginTop: 9 }}>
          The Pitch Agent <span style={{ color: BRAND.blue }}>•</span> Independent Football Analytics
        </div>
      </div>
    </div>
    {pageBadge ? (
      <div style={{ fontFamily: BRAND.font, fontWeight: 900, fontSize: 34, color: BRAND.blue }}>{pageBadge}</div>
    ) : null}
  </div>
);

const Watermark: React.FC = () => (
  <div style={{ position: "absolute", right: 30, top: 470, fontFamily: BRAND.font, fontWeight: 900, fontSize: CHROME.watermarkSize, lineHeight: 1, letterSpacing: -60, color: BRAND.watermark, userSelect: "none" }}>A</div>
);

const Footer: React.FC<{ text?: string }> = ({ text }) => (
  <div style={{ position: "absolute", bottom: 40, left: 0, right: 0, textAlign: "center", fontFamily: BRAND.font, fontSize: 22, fontStyle: "italic", color: BRAND.navy, opacity: 0.9 }}>{text || BRAND.footer}</div>
);

export const BrandFrame: React.FC<{
  children?: React.ReactNode;
  pageBadge?: string;
  footer?: string;
  fadeIn?: boolean;
}> = ({ children, pageBadge, footer, fadeIn = true }) => {
  const f = useCurrentFrame();
  const o = fadeIn ? interpolate(f, [0, 8], [0, 1], { extrapolateRight: "clamp" }) : 1;
  return (
    <AbsoluteFill style={{ background: BRAND.bgGradient, fontFamily: BRAND.font }}>
      <Watermark />
      {/* pillar body sits between bg/watermark and the chrome overlay */}
      <AbsoluteFill>{children}</AbsoluteFill>
      <div style={{ opacity: o }}>
        <CornerBlock where="tr" />
        <CornerBlock where="bl" />
        <DotGrid pos="tl" />
        <DotGrid pos="br" />
        <Header pageBadge={pageBadge} />
        <Footer text={footer} />
      </div>
    </AbsoluteFill>
  );
};
