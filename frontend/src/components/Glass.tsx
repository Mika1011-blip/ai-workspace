import type { CSSProperties, ReactNode } from "react";
import LiquidGlass from "liquid-glass-react";

/** The one glass we use everywhere: calm settings, over a light office. */
export default function Glass({ children, radius = 22, padding = "0", className = "", style, elastic = 0.08 }: {
  children: ReactNode; radius?: number; padding?: string; className?: string; style?: CSSProperties; elastic?: number;
}) {
  return (
    <LiquidGlass
      displacementScale={36}
      blurAmount={0.5}
      saturation={125}
      aberrationIntensity={1.2}
      elasticity={elastic}
      cornerRadius={radius}
      padding={padding}
      overLight
      mode="standard"
      className={className}
      // The library centres itself with translate(-50%, -50%), so it is
      // anchored at the middle of whatever box it is given.
      style={{ position: "absolute", top: "50%", left: "50%", width: "100%", height: "100%", ...style }}
    >
      {children}
    </LiquidGlass>
  );
}
