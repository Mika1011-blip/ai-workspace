import { useEffect, useRef } from "react";
import { useTheme } from "../theme";
import { drawOffice, inside, type Hit, type SceneModel } from "./scene";

/** The scene clock starts when the module loads, so App and the canvas agree
 * on what "now" means for pop-in times. */
export const SCENE_T0 = performance.now();
export const sceneNow = () => (performance.now() - SCENE_T0) / 1000;

const PAN_LIMIT = 0.45; // of the stage size, in each direction

/** The office canvas: draws the scene every frame from `model`, pans on
 * drag, zooms on wheel, picks stations on click. It owns nothing but pixels. */
export default function Office({ model, onPick, insetLeft = 0 }: { model: SceneModel; onPick: (id: string | null) => void; insetLeft?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modelRef = useRef(model);
  const hitsRef = useRef<Hit[]>([]);
  const zoomRef = useRef(1);
  const panRef = useRef<[number, number]>([0, 0]);
  const dragRef = useRef<{ x: number; y: number; pan: [number, number]; moved: boolean } | null>(null);
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
      smoothInset.current += (insetRef.current - smoothInset.current) * 0.12;
      const started = performance.now();
      try {
        hitsRef.current = drawOffice(ctx, canvas.clientWidth, canvas.clientHeight, sceneNow(), modelRef.current, themeRef.current, zoomRef.current, smoothInset.current, panRef.current);
      } catch (err) {
        // one bad frame must not stop the office; say so once
        if (!(window as unknown as { __officeError?: boolean }).__officeError) { console.error("office frame failed", err); (window as unknown as { __officeError?: boolean }).__officeError = true; }
      }
      (window as unknown as { __office?: unknown }).__office = { t: sceneNow(), frameMs: performance.now() - started, stations: modelRef.current.stations.map((s) => [s.id, s.bornAt, s.status]) };
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []);

  const clampPan = (p: [number, number]): [number, number] => {
    const c = canvasRef.current!;
    const lx = c.clientWidth * PAN_LIMIT * zoomRef.current, ly = c.clientHeight * PAN_LIMIT * zoomRef.current;
    return [Math.max(-lx, Math.min(lx, p[0])), Math.max(-ly, Math.min(ly, p[1]))];
  };
  const down = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    dragRef.current = { x: ev.clientX, y: ev.clientY, pan: [...panRef.current] as [number, number], moved: false };
    ev.currentTarget.setPointerCapture(ev.pointerId);
  };
  const moveEv = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = ev.clientX - d.x, dy = ev.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true;
    panRef.current = clampPan([d.pan[0] + dx, d.pan[1] + dy]);
  };
  const up = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d || d.moved) return; // a drag, not a click
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
    panRef.current = clampPan(panRef.current);
  };

  return (
    <canvas
      ref={canvasRef}
      className="office"
      onPointerDown={down}
      onPointerMove={moveEv}
      onPointerUp={up}
      onPointerCancel={() => { dragRef.current = null; }}
      onWheel={wheel}
      aria-label="The AI office: one station per worker; click a station to open its panel, drag to look around"
      role="img"
    />
  );
}
