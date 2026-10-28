// Decor and ambiance: things that make the floor feel inhabited. All pure
// functions of (time, theme); the office cat keeps a little state.

import { type Pt, type Project, type Style, box, face, lerp, mix, poly, rgba, rng, shade } from "../iso/core";
import type { Theme } from "../theme";

export interface Decor { kind: "plant" | "sofa" | "cooler" | "coffee" | "shelf" | "lamp" | "rug" | "whiteboard"; x: number; y: number; r?: number }

export function drawDecor(ctx: CanvasRenderingContext2D, P: Project, s: number, d: Decor, theme: Theme, st: Style, t: number): void {
  const { x, y } = d;
  switch (d.kind) {
    case "plant": {
      box(ctx, P, x, y, 0, 0.5, 0.5, 0.45, shade(mix(theme.accent, "#ffffff", 0.35)), st, `pot${x}${y}`);
      const top = P(x + 0.25, y + 0.25, 0.45), r = 0.42 * s;
      const sway = Math.sin(t * 1.3 + x) * 1.5;
      for (const [dx, dy, k] of [[0, 0, 1], [-0.45, -0.3, 0.7], [0.4, -0.35, 0.65], [0.1, -0.6, 0.6]]) {
        ctx.fillStyle = rgba(mix(theme.good, "#ffffff", 0.2 + k * 0.3));
        ctx.beginPath(); ctx.ellipse(top[0] + dx * r + sway * k, top[1] - r * 0.55 + dy * r, r * 0.55 * k, r * 0.75 * k, dx * 0.6, 0, 7); ctx.fill();
        ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.8; ctx.stroke();
      }
      break;
    }
    case "sofa": {
      box(ctx, P, x, y, 0, 2.2, 0.9, 0.45, shade(mix(theme.machine, theme.accent, 0.35)), st, "sofa");
      box(ctx, P, x, y, 0.45, 2.2, 0.25, 0.5, shade(mix(theme.machine, theme.accent, 0.45)), st, "sofaback");
      box(ctx, P, x, y + 0.25, 0.45, 0.2, 0.65, 0.3, shade(mix(theme.machine, theme.accent, 0.45)), st, "arm1");
      box(ctx, P, x + 2.0, y + 0.25, 0.45, 0.2, 0.65, 0.3, shade(mix(theme.machine, theme.accent, 0.45)), st, "arm2");
      // a cushion
      box(ctx, P, x + 0.9, y + 0.35, 0.45, 0.45, 0.45, 0.12, shade(theme.good), st, "cushion");
      break;
    }
    case "cooler": {
      box(ctx, P, x, y, 0, 0.45, 0.45, 1.0, shade(theme.tagBg), st, "cooler");
      const b = P(x + 0.22, y + 0.22, 1.0);
      ctx.fillStyle = rgba(mix("#86c5f4", "#ffffff", 0.3), 0.9);
      ctx.beginPath(); ctx.ellipse(b[0], b[1] - 0.22 * s, 0.2 * s, 0.3 * s, 0, 0, 7); ctx.fill();
      ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
      // a bubble now and then
      const ph = (t * 0.6 + x) % 1;
      ctx.fillStyle = "rgba(255,255,255,0.8)"; ctx.beginPath(); ctx.arc(b[0] + Math.sin(ph * 6) * 2, b[1] - 0.1 * s - ph * 0.3 * s, 1.5 * (1 - ph) + 0.5, 0, 7); ctx.fill();
      break;
    }
    case "coffee": {
      box(ctx, P, x, y, 0, 1.4, 0.7, 0.85, shade(mix(theme.machineDark, "#ffffff", 0.35)), st, "counter");
      box(ctx, P, x + 0.15, y + 0.15, 0.85, 0.5, 0.4, 0.55, shade(theme.machineDark), st, "machine");
      const cup = P(x + 1.0, y + 0.3, 0.85);
      ctx.fillStyle = theme.tagBg; ctx.beginPath(); ctx.roundRect(cup[0] - 0.08 * s, cup[1] - 0.22 * s, 0.16 * s, 0.2 * s, 2); ctx.fill();
      ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.8; ctx.stroke();
      // steam
      for (let i = 0; i < 3; i++) {
        const ph = (t * 0.5 + i / 3 + x) % 1;
        ctx.fillStyle = `rgba(255,255,255,${0.5 * (1 - ph)})`;
        ctx.beginPath(); ctx.arc(cup[0] + Math.sin(ph * 8 + i) * 2, cup[1] - 0.25 * s - ph * 0.5 * s, 1.5 + ph * 2, 0, 7); ctx.fill();
      }
      break;
    }
    case "shelf": {
      box(ctx, P, x, y, 0, 1.6, 0.4, 1.6, shade(mix(theme.machine, theme.ink, 0.2)), st, "shelf");
      const r = rng("books" + x);
      for (let row = 0; row < 3; row++) for (let i = 0; i < 6; i++) {
        const bx = x + 0.12 + i * 0.23, bz = 0.1 + row * 0.5, h = 0.3 + r() * 0.12;
        const col = [theme.accent, theme.good, theme.machine, theme.tagBg, "#ffd166"][Math.floor(r() * 5)];
        poly(ctx, [P(bx, y + 0.41, bz), P(bx + 0.18, y + 0.41, bz), P(bx + 0.18, y + 0.41, bz + h), P(bx, y + 0.41, bz + h)], rgba(col));
      }
      break;
    }
    case "lamp": {
      const b = P(x, y), top = P(x, y, 2.2);
      ctx.strokeStyle = theme.machineDark; ctx.lineWidth = 3; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(b[0], b[1]); ctx.lineTo(top[0], top[1]); ctx.stroke();
      const flicker = 0.85 + 0.15 * Math.sin(t * 17 + x) * Math.sin(t * 3.1);
      const g = ctx.createRadialGradient(top[0], top[1], 2, top[0], top[1], 1.4 * s);
      g.addColorStop(0, `rgba(255,226,138,${0.45 * flicker})`); g.addColorStop(1, "rgba(255,226,138,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(top[0], top[1], 1.4 * s, 0, 7); ctx.fill();
      ctx.fillStyle = "#ffe28a"; ctx.beginPath(); ctx.arc(top[0], top[1], 0.14 * s, 0, 7); ctx.fill();
      ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
      break;
    }
    case "rug": {
      const w = d.r ?? 3, h = w * 0.7;
      face(ctx, [P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h)], rgba(mix(theme.accent, theme.floor, 0.7)), st, "rug", true);
      ctx.strokeStyle = rgba(theme.accent, 0.5); ctx.lineWidth = 1;
      const i1 = P(x + 0.3, y + 0.3), i2 = P(x + w - 0.3, y + 0.3), i3 = P(x + w - 0.3, y + h - 0.3), i4 = P(x + 0.3, y + h - 0.3);
      ctx.beginPath(); ctx.moveTo(i1[0], i1[1]); ctx.lineTo(i2[0], i2[1]); ctx.lineTo(i3[0], i3[1]); ctx.lineTo(i4[0], i4[1]); ctx.closePath(); ctx.stroke();
      break;
    }
    case "whiteboard": {
      box(ctx, P, x, y, 0, 0.1, 0.1, 1.5, shade(theme.machineDark), st, "post1");
      box(ctx, P, x + 1.9, y, 0, 0.1, 0.1, 1.5, shade(theme.machineDark), st, "post2");
      face(ctx, [P(x, y + 0.05, 0.6), P(x + 2.0, y + 0.05, 0.6), P(x + 2.0, y + 0.05, 1.6), P(x, y + 0.05, 1.6)], theme.tagBg, st, "board");
      // doodles: a little chart and some lines
      const o = P(x + 0.15, y + 0.05, 1.45);
      ctx.save(); ctx.transform(0.866, 0.5, 0, 1, o[0], o[1]); ctx.scale(s / 40, s / 40);
      ctx.strokeStyle = theme.accent; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(4, 26); ctx.lineTo(14, 14); ctx.lineTo(22, 20); ctx.lineTo(34, 6); ctx.stroke();
      ctx.strokeStyle = theme.machineDark; ctx.lineWidth = 1.5; ctx.beginPath(); for (let i = 0; i < 3; i++) { ctx.moveTo(40, 8 + i * 8); ctx.lineTo(62 - i * 6, 8 + i * 8); } ctx.stroke();
      ctx.restore();
      break;
    }
  }
}

/** Birds crossing the sky, dust motes in the light: tiny, cheap, alive. */
export function drawAmbience(ctx: CanvasRenderingContext2D, W: number, H: number, t: number, theme: Theme): void {
  // dust motes
  const r = rng("motes");
  ctx.fillStyle = rgba(theme.tagBg, 0.55);
  for (let i = 0; i < 28; i++) {
    const x0 = r() * W, y0 = r() * H, sp = 6 + r() * 10, ph = r() * 6.28;
    const x = (x0 + Math.sin(t * 0.3 + ph) * 18 + t * sp * 0.3) % W, y = (y0 + Math.cos(t * 0.25 + ph) * 12 + t * 2) % H;
    ctx.globalAlpha = 0.25 + 0.25 * Math.sin(t * 1.3 + ph);
    ctx.beginPath(); ctx.arc(x, y, 1.2 + r() * 1.2, 0, 7); ctx.fill();
  }
  ctx.globalAlpha = 1;
  // a pair of birds every so often
  const cycle = 28, u = (t % cycle) / cycle;
  if (u < 0.45) {
    const bx = W * (-0.1 + u / 0.45 * 1.2), by = H * 0.12 + Math.sin(u * 20) * 10;
    ctx.strokeStyle = rgba(theme.ink, 0.6); ctx.lineWidth = 1.4; ctx.lineCap = "round";
    for (const [dx, dy] of [[0, 0], [22, 9]]) {
      const flap = Math.sin(t * 12 + dx) * 3;
      ctx.beginPath(); ctx.moveTo(bx + dx - 6, by + dy + flap); ctx.quadraticCurveTo(bx + dx, by + dy - 2, bx + dx, by + dy); ctx.quadraticCurveTo(bx + dx, by + dy - 2, bx + dx + 6, by + dy + flap); ctx.stroke();
    }
  }
}

/** A slow band of sunlight drifting over the tile. */
export function drawSunlight(ctx: CanvasRenderingContext2D, tile: Pt[], t: number): void {
  ctx.save();
  ctx.beginPath(); tile.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]))); ctx.closePath(); ctx.clip();
  const xs = tile.map((p) => p[0]), minX = Math.min(...xs), maxX = Math.max(...xs);
  const u = (t % 40) / 40, cx = lerp(minX - 200, maxX + 200, u);
  const g = ctx.createLinearGradient(cx - 160, 0, cx + 160, 0);
  g.addColorStop(0, "rgba(255,255,255,0)"); g.addColorStop(0.5, "rgba(255,250,220,0.22)"); g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g; ctx.fillRect(minX - 300, 0, maxX - minX + 600, 4000);
  ctx.restore();
}

// ---------- the sky: the office floats on a tile among drifting clouds ----------
export function drawSky(ctx: CanvasRenderingContext2D, W: number, H: number, theme: Theme): void {
  const top = rgba(mix(theme.background[2], "#86bdf5", 0.6));
  const mid = rgba(mix(theme.background[1], "#cfe5ff", 0.5));
  const low = rgba(mix(theme.background[0], "#ffffff", 0.35));
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, top); g.addColorStop(0.55, mid); g.addColorStop(1, low);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  // a soft sun, high on the left
  const sun = ctx.createRadialGradient(W * 0.18, H * 0.12, 10, W * 0.18, H * 0.12, Math.max(W, H) * 0.35);
  sun.addColorStop(0, "rgba(255,246,214,0.75)"); sun.addColorStop(1, "rgba(255,246,214,0)");
  ctx.fillStyle = sun;
  ctx.fillRect(0, 0, W, H);
}

interface Cloud { x: number; y: number; w: number; h: number; speed: number; puffs: [number, number, number][] }
const cloudCache = new Map<string, Cloud[]>();
function clouds(layer: "far" | "near", W: number, H: number, minY: number): Cloud[] {
  const key = `${layer}|${W}|${H}|${Math.round(minY)}`;
  if (cloudCache.has(key)) return cloudCache.get(key)!;
  const r = rng("clouds:" + layer);
  const n = layer === "far" ? 9 : 5;
  const out: Cloud[] = [];
  for (let i = 0; i < n; i++) {
    const w = layer === "far" ? 90 + r() * 120 : 220 + r() * 220;
    const h = w * (0.28 + r() * 0.12);
    const puffs: [number, number, number][] = [];
    const k = 4 + Math.floor(r() * 3);
    for (let j = 0; j < k; j++) puffs.push([(j / (k - 1) - 0.5) * w * 0.7, -r() * h * 0.45, h * (0.45 + r() * 0.4)]);
    out.push({
      x: r() * (W + w), y: layer === "far" ? r() * H * 0.55 : minY + r() * Math.max(60, H - minY), w, h,
      speed: layer === "far" ? 4 + r() * 5 : 12 + r() * 10, puffs,
    });
  }
  cloudCache.set(key, out);
  return out;
}
function cloudPath(ctx: CanvasRenderingContext2D, c: Cloud, x: number, y: number): void {
  ctx.beginPath();
  for (const [dx, dy, pr] of c.puffs) { ctx.moveTo(x + dx + pr, y + dy); ctx.ellipse(x + dx, y + dy, pr, pr * 0.8, 0, 0, 7); }
  ctx.moveTo(x + c.w * 0.45, y + c.h * 0.1);
  ctx.ellipse(x, y + c.h * 0.1, c.w * 0.45, c.h * 0.45, 0, 0, 7);
}
/** Flat pastel clouds: a lit top, a shaded underside, the thin ink edge only
 * around the silhouette (the edge is drawn first, the fill covers the rest).
 * Near clouds stay below `minY`, under the island. */
export function drawClouds(ctx: CanvasRenderingContext2D, W: number, H: number, t: number, theme: Theme, layer: "far" | "near", minY = 0): void {
  const list = clouds(layer, W, H, minY);
  const lit = layer === "far" ? rgba(mix(theme.background[1], "#ffffff", 0.75)) : "#ffffff";
  const under = rgba(mix(theme.slab, "#ffffff", layer === "far" ? 0.78 : 0.6));
  for (const c of list) {
    const x = ((c.x + t * c.speed) % (W + c.w * 1.4)) - c.w * 0.7;
    const y = c.y + Math.sin(t * 0.25 + c.x) * (layer === "far" ? 3 : 6);
    if (theme.edge.width > 0) {
      cloudPath(ctx, c, x, y);
      ctx.strokeStyle = rgba(theme.edge.color, layer === "far" ? 0.22 : 0.45);
      ctx.lineWidth = theme.edge.width * 2;
      ctx.stroke();
    }
    cloudPath(ctx, c, x, y);
    ctx.fillStyle = under;
    ctx.fill();
    ctx.save();
    ctx.clip();
    ctx.fillStyle = lit;
    ctx.fillRect(x - c.w, y - c.h * 2, c.w * 2, c.h * 1.98);
    ctx.restore();
  }
}
