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

// ---------- the office cat ----------
let cat = { pos: [0, 0] as Pt, target: [0, 0] as Pt, next: 0, init: false, facing: 1 as 1 | -1, stride: 0 };
export function stepCat(t: number, dt: number, x0: number, y0: number, x1: number, y1: number): typeof cat {
  if (!cat.init) { cat = { ...cat, pos: [lerp(x0, x1, 0.5), lerp(y0, y1, 0.5)], target: [x0, y0], next: t, init: true }; }
  if (t >= cat.next) {
    const r = rng("cat" + Math.floor(t));
    cat.target = [lerp(x0, x1, r()), lerp(y0, y1, r())];
    cat.next = t + 4 + r() * 8;
  }
  const dx = cat.target[0] - cat.pos[0], dy = cat.target[1] - cat.pos[1], dist = Math.hypot(dx, dy);
  if (dist > 0.03) {
    const sl = Math.min(dist, 0.7 * dt);
    cat.pos = [cat.pos[0] + (dx / dist) * sl, cat.pos[1] + (dy / dist) * sl];
    cat.stride += sl * 8;
    if (Math.abs(dx - dy) > 0.05) cat.facing = dx - dy > 0 ? 1 : -1;
  }
  return cat;
}
export function drawCat(ctx: CanvasRenderingContext2D, p: Pt, s: number, moving: boolean, facing: 1 | -1, theme: Theme, t: number): void {
  const k = Math.min(1, s / 30);
  ctx.save(); ctx.translate(p[0], p[1]); ctx.scale(facing * k, k);
  ctx.fillStyle = "rgba(80,70,140,0.15)"; ctx.beginPath(); ctx.ellipse(0, 1, 7, 2.5, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#f2c39a";
  ctx.beginPath(); ctx.ellipse(0, -3, 6, 3.2, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.7; ctx.stroke();
  ctx.beginPath(); ctx.arc(5.5, -5.5, 2.8, 0, 7); ctx.fill(); ctx.stroke();
  for (const sx of [-1, 1]) { ctx.beginPath(); ctx.moveTo(5.5 + sx * 2.2, -7); ctx.lineTo(5.5 + sx * 1.6, -10); ctx.lineTo(5.5 + sx * 0.4, -7.5); ctx.closePath(); ctx.fill(); }
  // tail
  ctx.strokeStyle = "#e0a070"; ctx.lineWidth = 1.6; ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(-6, -3); ctx.quadraticCurveTo(-10, -4 + Math.sin(t * 3) * 3, -9, -9 + Math.sin(t * 2) * 2); ctx.stroke();
  // legs
  ctx.strokeStyle = "#e0a070"; ctx.lineWidth = 1.4;
  const sw = moving ? Math.sin(cat.stride) * 2 : 0;
  ctx.beginPath(); ctx.moveTo(-3, -1); ctx.lineTo(-3 + sw, 1); ctx.moveTo(3, -1); ctx.lineTo(3 - sw, 1); ctx.stroke();
  ctx.fillStyle = theme.ink; ctx.beginPath(); ctx.arc(6.5, -6, 0.5, 0, 7); ctx.fill();
  ctx.restore();
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
