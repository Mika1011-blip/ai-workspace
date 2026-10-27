import { useEffect, useRef } from "react";
import { useTheme } from "../theme";
import { drawOffice, inside, type Hit, type SceneModel } from "./scene";

/** The scene clock starts when the module loads, so App and the canvas agree
 * on what "now" means for pop-in times. */
export const SCENE_T0 = performance.now();
export const sceneNow = () => (performance.now() - SCENE_T0) / 1000;

/** The office canvas: draws the scene every frame from `model`, picks
 * stations on click. It owns nothing but pixels. */
export default function Office({ model, onPick, insetLeft = 0 }: { model: SceneModel; onPick: (id: string | null) => void; insetLeft?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modelRef = useRef(model);
  const hitsRef = useRef<Hit[]>([]);
  const zoomRef = useRef(1);
  const insetRef = useRef(insetLeft);
  const { theme } = useTheme();
  const themeRef = useRef(theme);
  modelRef.current = model;
  themeRef.current = theme;
  insetRef.current = insetLeft;
  const smoothInset = useRef(insetLeft);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let frame = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
    };
    const loop = () => {
      resize();
      const dpr = canvas.width / Math.max(1, canvas.clientWidth);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // ease the camera as the pane opens and closes
      const target = insetRef.current;
      smoothInset.current += (target - smoothInset.current) * 0.12;
      hitsRef.current = drawOffice(ctx, canvas.clientWidth, canvas.clientHeight, sceneNow(), modelRef.current, themeRef.current, zoomRef.current, smoothInset.current);
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []);

  const pick = (ev: React.MouseEvent<HTMLCanvasElement>) => {
    const r = ev.currentTarget.getBoundingClientRect();
    const p: [number, number] = [ev.clientX - r.left, ev.clientY - r.top];
    // nearer stations are drawn later and sit lower on screen: test from the last hit back
    for (let i = hitsRef.current.length - 1; i >= 0; i--) {
      if (inside(p, hitsRef.current[i].poly)) { onPick(hitsRef.current[i].id); return; }
    }
    onPick(null);
  };
  const wheel = (ev: React.WheelEvent) => {
    zoomRef.current = Math.min(2.2, Math.max(0.6, zoomRef.current * (ev.deltaY > 0 ? 0.92 : 1.08)));
  };

  return <canvas ref={canvasRef} className="office" onClick={pick} onWheel={wheel} aria-label="The AI office: one station per worker; click a station to open its panel" role="img" />;
}
