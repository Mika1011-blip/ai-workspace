// The isometric drawing kit, ported from the "Isometric Pastel" reference and
// bent to this app's two house rules: every printed face carries a hand-drawn
// surface (paper grain + a faint ink wobble) and every object has a thin dark
// edge line, both set by the theme. Everything is a pure function of its
// inputs; randomness comes from seeded generators, never Math.random.

import type { Theme } from "../theme";

export type Pt = [number, number];
export type Project = (x: number, y: number, z?: number) => Pt;

// ---------- seeded randomness ----------
export function rng(seed: number | string = 1) {
  let a = typeof seed === "string" ? hashStr(seed) : seed >>> 0 || 1;
  const r = () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return r;
}
function hashStr(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// ---------- math ----------
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const clamp = (v: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));
export const ease = {
  inOut: (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  out: (t: number) => 1 - Math.pow(1 - t, 3),
  back: (t: number) => {
    const c = 1.70158;
    return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2);
  },
};

// ---------- colour ----------
export type RGB = [number, number, number];
export function hex(h: string): RGB {
  h = h.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export const rgba = (c: string | RGB, a = 1) => {
  const [r, g, b] = Array.isArray(c) ? c : hex(c);
  return `rgba(${r | 0},${g | 0},${b | 0},${a})`;
};
export const mix = (c1: string | RGB, c2: string | RGB, t: number): RGB => {
  const a = Array.isArray(c1) ? c1 : hex(c1);
  const b = Array.isArray(c2) ? c2 : hex(c2);
  return [0, 1, 2].map((i) => a[i] + (b[i] - a[i]) * t) as RGB;
};

// ---------- projection ----------
export const C30 = Math.cos(Math.PI / 6);
export const makeIso = (ox: number, oy: number, s: number): Project => (x, y, z = 0) => [ox + (x - y) * C30 * s, oy + (x + y) * 0.5 * s - z * s];

const SHADE_DARK: RGB = [92, 88, 150];
export interface Faces { top: string; left: string; right: string }
export const shade = (base: string | RGB, k = 1): Faces => ({
  top: rgba(mix(base, "#ffffff", 0.42 * k)),
  left: rgba(mix(base, "#ffffff", 0.08)),
  right: rgba(mix(base, SHADE_DARK, 0.28 * k)),
});

// ---------- hand-drawn surface ----------
// One grain tile per (theme, strength) pair, reused for every face: a
// seeded speckle of light and dark dots, multiplied over the fill so flat
// colour reads as printed on paper.
const grainCache = new Map<string, CanvasPattern | null>();
export function grainPattern(ctx: CanvasRenderingContext2D, strength: number): CanvasPattern | null {
  if (strength <= 0) return null;
  const key = strength.toFixed(2);
  if (grainCache.has(key)) return grainCache.get(key)!;
  const size = 96;
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const g = c.getContext("2d")!;
  const img = g.createImageData(size, size);
  const r = rng("grain");
  for (let i = 0; i < img.data.length; i += 4) {
    const v = r();
    const dark = v < 0.5;
    const a = Math.pow(Math.abs(v - 0.5) * 2, 2.2) * 110 * strength;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = dark ? 40 : 255;
    img.data[i + 3] = a;
  }
  g.putImageData(img, 0, 0);
  const pattern = ctx.createPattern(c, "repeat");
  grainCache.set(key, pattern);
  return pattern;
}

/** A polyline whose points wobble like an ink line drawn by hand. */
export function wobbly(ctx: CanvasRenderingContext2D, pts: Pt[], seed: string, amp = 0.7, close = true): void {
  const r = rng(seed);
  ctx.beginPath();
  const n = pts.length;
  for (let i = 0; i < n + (close ? 1 : 0); i++) {
    const a = pts[i % n];
    const b = pts[(i + 1) % n];
    if (i === n) break;
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const steps = Math.max(1, Math.round(len / 16));
    if (i === 0) ctx.moveTo(a[0], a[1]);
    for (let k = 1; k <= steps; k++) {
      const u = k / steps;
      const j = k === steps && !close && i === n - 1 ? 0 : (r() - 0.5) * 2 * amp;
      ctx.lineTo(lerp(a[0], b[0], u) + j, lerp(a[1], b[1], u) + j * 0.6);
    }
    if (!close && i === n - 2) break;
  }
  if (close) ctx.closePath();
}

export interface Style { theme: Theme }

/** The grain, once over the whole frame: cheaper than per face and reads
 * the same (paper everywhere, like a print). */
export function grainOverlay(ctx: CanvasRenderingContext2D, W: number, H: number, strength: number): void {
  const grain = grainPattern(ctx, strength);
  if (!grain) return;
  ctx.save();
  ctx.fillStyle = grain;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

/** Fill a face and ink its outline (the grain comes in one pass later). */
export function face(ctx: CanvasRenderingContext2D, pts: Pt[], fill: string, st: Style, seed: string, outline = true): void {
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  if (outline && st.theme.edge.width > 0) {
    ctx.save();
    ctx.strokeStyle = st.theme.edge.color;
    ctx.lineWidth = st.theme.edge.width;
    ctx.lineJoin = "round";
    wobbly(ctx, pts, seed, 0.35 + st.theme.grain * 0.5);
    ctx.stroke();
    ctx.restore();
  }
}

export function poly(ctx: CanvasRenderingContext2D, pts: Pt[], fill: string): void {
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
}

/** An isometric box at (x, y, z) of size w × d × h, three faces, grain, edges. */
export function box(ctx: CanvasRenderingContext2D, P: Project, x: number, y: number, z: number, w: number, d: number, h: number, c: Faces, st: Style, seed = "box"): void {
  const px = P(x, y, 0)[1] - P(x, y, 1)[1];
  const hp = h * px;
  if (Math.abs(z) < 0.01 && hp > 6) {
    // contact shadow where the box meets the floor
    const a = P(x, y + d, 0), b = P(x + w, y + d, 0), e = P(x + w, y, 0);
    ctx.save();
    ctx.lineCap = "butt";
    ctx.lineJoin = "round";
    for (const [lw, al] of [[Math.min(12, px * 0.3), 0.07], [Math.min(6, px * 0.15), 0.1], [Math.min(3, px * 0.07), 0.14]]) {
      ctx.strokeStyle = `rgba(60,50,110,${al})`;
      ctx.lineWidth = lw;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.lineTo(e[0], e[1]);
      ctx.stroke();
    }
    ctx.restore();
  }
  face(ctx, [P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)], c.right, st, seed + "r");
  face(ctx, [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)], c.left, st, seed + "l");
  face(ctx, [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)], c.top, st, seed + "t");
}

export function cylinder(ctx: CanvasRenderingContext2D, P: Project, s: number, cx: number, cy: number, z: number, r: number, h: number, base: string, st: Style): void {
  const b = P(cx, cy, z), tp = P(cx, cy, z + h);
  const rx = 1.2247 * r * s, ry = 0.7071 * r * s;
  const g = ctx.createLinearGradient(b[0] - rx, 0, b[0] + rx, 0);
  g.addColorStop(0, rgba(mix(base, "#ffffff", 0.15)));
  g.addColorStop(0.35, rgba(mix(base, "#ffffff", 0.3)));
  g.addColorStop(0.55, rgba(base));
  g.addColorStop(1, rgba(mix(base, SHADE_DARK, 0.32)));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.ellipse(b[0], b[1], rx, ry, 0, 0, Math.PI);
  ctx.lineTo(tp[0] - rx, tp[1]);
  ctx.ellipse(tp[0], tp[1], rx, ry, 0, Math.PI, 0, true);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = st.theme.edge.color;
  ctx.lineWidth = st.theme.edge.width;
  ctx.stroke();
  ctx.fillStyle = rgba(mix(base, "#ffffff", 0.5));
  ctx.beginPath();
  ctx.ellipse(tp[0], tp[1], rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

/** Convex hull (monotone chain) of 2D points, for the long soft shadows. */
export function hull(pts: Pt[]): Pt[] {
  pts = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cr = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo: Pt[] = [], up: Pt[] = [];
  for (const p of pts) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
  for (let i = pts.length - 1; i >= 0; i--) { const p = pts[i]; while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
  up.pop(); lo.pop();
  return lo.concat(up);
}

// ---------- lettering ----------
export interface TagOpts { font?: string; bg?: string; col?: string; k?: number; icon?: string; iconCol?: string }
const tagCache = new Map<string, HTMLCanvasElement>();
const PAD = 18; // room for the shadow
const TAG_DPR = 2;
/** A white pill tag with a soft shadow; `k` scales it (pop-in). Drawn once
 * per look into an offscreen canvas, then blitted: shadows are costly. */
export function tag(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, st: Style, o: TagOpts = {}): void {
  const k = o.k ?? 1;
  if (k <= 0.01) return;
  const font = o.font || '600 13px "Inter", system-ui, sans-serif';
  const key = [text, font, o.bg, o.col, o.icon, o.iconCol, st.theme.tagBg, st.theme.ink, st.theme.edge.color, st.theme.edge.width].join("|");
  let img = tagCache.get(key);
  if (!img) {
    if (tagCache.size > 400) tagCache.clear();
    img = renderTag(text, st, o, font);
    tagCache.set(key, img);
  }
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(k, k);
  ctx.drawImage(img, -img.width / (2 * TAG_DPR), -img.height / (2 * TAG_DPR) + 2, img.width / TAG_DPR, img.height / TAG_DPR);
  ctx.restore();
}
function renderTag(text: string, st: Style, o: TagOpts, font: string): HTMLCanvasElement {
  const probe = document.createElement("canvas").getContext("2d")!;
  probe.font = font;
  const fsz = parseInt((font.match(/(\d+)px/) || ["", "14"])[1]);
  const w = probe.measureText(text).width + (o.icon ? fsz * 2.6 : fsz * 1.4), h = Math.round(fsz * 1.75);
  const c = document.createElement("canvas");
  c.width = Math.ceil((w + PAD * 2) * TAG_DPR);
  c.height = Math.ceil((h + PAD * 2) * TAG_DPR);
  const g = c.getContext("2d")!;
  g.scale(TAG_DPR, TAG_DPR);
  g.translate(w / 2 + PAD, h / 2 + PAD - 2);
  g.font = font;
  g.shadowColor = "rgba(80,70,140,0.22)";
  g.shadowBlur = 14;
  g.shadowOffsetY = 4;
  g.fillStyle = o.bg || st.theme.tagBg;
  g.beginPath();
  g.roundRect(-w / 2, -h / 2, w, h, h / 2);
  g.fill();
  g.shadowColor = "transparent";
  g.strokeStyle = st.theme.edge.color;
  g.lineWidth = Math.max(0.6, st.theme.edge.width * 0.8);
  g.stroke();
  g.textBaseline = "middle";
  if (o.icon) {
    g.font = `${fsz}px system-ui, "Segoe UI Emoji", sans-serif`;
    g.textAlign = "left";
    g.fillStyle = o.iconCol || st.theme.ink;
    g.fillText(o.icon, -w / 2 + fsz * 0.6, 1);
    g.font = font;
  }
  g.fillStyle = o.col || st.theme.ink;
  g.textAlign = "center";
  g.fillText(text, o.icon ? fsz * 0.6 : 0, 1);
  return c;
}

export function numberTag(ctx: CanvasRenderingContext2D, x: number, y: number, num: string, label: string, st: Style, o: TagOpts = {}): void {
  const k = o.k ?? 1;
  if (k <= 0.01) return;
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(k, k);
  ctx.font = '800 44px "Inter", system-ui, sans-serif';
  const nw = ctx.measureText(num).width;
  ctx.font = '600 16px "Inter", system-ui, sans-serif';
  const lw = ctx.measureText(label).width;
  const w = Math.max(nw, lw) + 40, h = 84;
  ctx.shadowColor = "rgba(80,70,140,0.25)";
  ctx.shadowBlur = 22;
  ctx.shadowOffsetY = 6;
  ctx.fillStyle = o.bg || st.theme.tagBg;
  ctx.beginPath();
  ctx.roundRect(-w / 2, -h / 2, w, h, 20);
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.strokeStyle = st.theme.edge.color;
  ctx.lineWidth = st.theme.edge.width;
  ctx.stroke();
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = st.theme.muted;
  ctx.fillText(label, 0, -h / 2 + 24);
  ctx.font = '800 44px "Inter", system-ui, sans-serif';
  ctx.fillStyle = o.col || st.theme.ink;
  ctx.fillText(num, 0, h / 2 - 14);
  ctx.restore();
}

/** A quadratic arrow drawn on up to `prog`; returns the point function. */
export function arrow(ctx: CanvasRenderingContext2D, pts: [Pt, Pt, Pt], prog: number, col: string, dash: number[] | null, w = 2) {
  if (prog <= 0) return null;
  const [a, c, b] = pts;
  const q = (u: number): Pt => [(1 - u) * (1 - u) * a[0] + 2 * u * (1 - u) * c[0] + u * u * b[0], (1 - u) * (1 - u) * a[1] + 2 * u * (1 - u) * c[1] + u * u * b[1]];
  ctx.save();
  ctx.strokeStyle = col;
  ctx.lineWidth = w;
  ctx.lineCap = "round";
  if (dash) ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.moveTo(a[0], a[1]);
  const n = 30;
  for (let i = 1; i <= n; i++) { const p = q((prog * i) / n); ctx.lineTo(p[0], p[1]); }
  ctx.stroke();
  ctx.setLineDash([]);
  const e = q(prog), e0 = q(Math.max(0, prog - 0.04)), ang = Math.atan2(e[1] - e0[1], e[0] - e0[0]);
  ctx.fillStyle = col;
  ctx.translate(e[0], e[1]);
  ctx.rotate(ang);
  ctx.beginPath();
  ctx.moveTo(4, 0);
  ctx.lineTo(-7, -5.5);
  ctx.lineTo(-7, 5.5);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
  return q;
}

/** Point-in-polygon (screen space), for picking stations. */
export function inside(p: Pt, poly: Pt[]): boolean {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}
