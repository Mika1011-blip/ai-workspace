// The office animals: a cat, a dog, a hopping sparrow and butterflies. The
// walkers follow the nav grid like the people do; the butterflies fly.

import { type Pt, lerp, rgba, rng } from "../iso/core";
import type { Theme } from "../theme";
import type { Nav } from "./nav";

export interface Animal { pos: Pt; route: Pt[]; next: number; facing: 1 | -1; stride: number; rest: number }
const animals = new Map<string, Animal>();

export function stepAnimal(id: string, nav: Nav, x0: number, y0: number, x1: number, y1: number, speed: number, idle: number, t: number, dt: number): Animal {
  let a = animals.get(id);
  if (!a) {
    const start = nav.randomFree("animal:" + id, x0, y0, x1, y1) ?? nav.nearestFree([x0, y0]);
    a = { pos: start, route: [], next: t, facing: 1, stride: 0, rest: 0 };
    animals.set(id, a);
  }
  if (!a.route.length && t >= a.next) {
    const k = Math.floor(t);
    const target = nav.randomFree(`${id}:${k}`, x0, y0, x1, y1);
    if (target) a.route = nav.path(a.pos, target) ?? [];
    a.next = t + idle + rng(`${id}:r${k}`)() * idle;
  }
  let budget = speed * dt;
  while (a.route.length && budget > 0) {
    const to = a.route[0];
    const dx = to[0] - a.pos[0], dy = to[1] - a.pos[1], dist = Math.hypot(dx, dy);
    if (dist < 0.03) { a.route.shift(); continue; }
    const sl = Math.min(dist, budget);
    a.pos = [a.pos[0] + (dx / dist) * sl, a.pos[1] + (dy / dist) * sl];
    a.stride += sl * 8;
    budget -= sl;
    if (Math.abs(dx - dy) > 0.05) a.facing = dx - dy > 0 ? 1 : -1;
  }
  return a;
}
export const moving = (a: Animal) => a.route.length > 0;
export function resetAnimals(): void { animals.clear(); }

export function drawCat(ctx: CanvasRenderingContext2D, p: Pt, s: number, a: Animal, theme: Theme, t: number): void {
  const k = Math.min(1, s / 30);
  ctx.save(); ctx.translate(p[0], p[1]); ctx.scale(a.facing * k, k);
  ctx.fillStyle = "rgba(80,70,140,0.15)"; ctx.beginPath(); ctx.ellipse(0, 1, 7, 2.5, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#f2c39a";
  ctx.beginPath(); ctx.ellipse(0, -3, 6, 3.2, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.7; ctx.stroke();
  ctx.beginPath(); ctx.arc(5.5, -5.5, 2.8, 0, 7); ctx.fill(); ctx.stroke();
  for (const sx of [-1, 1]) { ctx.beginPath(); ctx.moveTo(5.5 + sx * 2.2, -7); ctx.lineTo(5.5 + sx * 1.6, -10); ctx.lineTo(5.5 + sx * 0.4, -7.5); ctx.closePath(); ctx.fill(); }
  ctx.strokeStyle = "#e0a070"; ctx.lineWidth = 1.6; ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(-6, -3); ctx.quadraticCurveTo(-10, -4 + Math.sin(t * 3) * 3, -9, -9 + Math.sin(t * 2) * 2); ctx.stroke();
  ctx.lineWidth = 1.4;
  const sw = moving(a) ? Math.sin(a.stride) * 2 : 0;
  ctx.beginPath(); ctx.moveTo(-3, -1); ctx.lineTo(-3 + sw, 1); ctx.moveTo(3, -1); ctx.lineTo(3 - sw, 1); ctx.stroke();
  ctx.fillStyle = theme.ink; ctx.beginPath(); ctx.arc(6.5, -6, 0.5, 0, 7); ctx.fill();
  ctx.restore();
}

export function drawDog(ctx: CanvasRenderingContext2D, p: Pt, s: number, a: Animal, theme: Theme, t: number): void {
  const k = Math.min(1, s / 30);
  ctx.save(); ctx.translate(p[0], p[1]); ctx.scale(a.facing * k, k);
  ctx.fillStyle = "rgba(80,70,140,0.15)"; ctx.beginPath(); ctx.ellipse(0, 1, 8, 2.8, 0, 0, 7); ctx.fill();
  const sw = moving(a) ? Math.sin(a.stride) * 2.5 : 0;
  ctx.strokeStyle = "#8a5a3a"; ctx.lineWidth = 2; ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(-4, -2); ctx.lineTo(-4 + sw, 1); ctx.moveTo(4, -2); ctx.lineTo(4 - sw, 1); ctx.moveTo(-2, -2); ctx.lineTo(-2 - sw, 1); ctx.moveTo(2, -2); ctx.lineTo(2 + sw, 1); ctx.stroke();
  ctx.fillStyle = "#b07a4c";
  ctx.beginPath(); ctx.ellipse(0, -4.5, 7, 3.6, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.7; ctx.stroke();
  ctx.beginPath(); ctx.ellipse(6.5, -7.5, 3.4, 2.8, 0.2, 0, 7); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#8a5a3a"; ctx.beginPath(); ctx.ellipse(5.2, -9.5, 1.4, 2.4, -0.4, 0, 7); ctx.fill();
  ctx.fillStyle = theme.ink; ctx.beginPath(); ctx.arc(9.4, -7.6, 0.9, 0, 7); ctx.fill(); ctx.beginPath(); ctx.arc(7.6, -8.4, 0.5, 0, 7); ctx.fill();
  // a wagging tail
  ctx.strokeStyle = "#b07a4c"; ctx.lineWidth = 1.8;
  ctx.beginPath(); ctx.moveTo(-7, -6); ctx.lineTo(-10, -9 + Math.sin(t * 14) * 2.5); ctx.stroke();
  ctx.restore();
}

/** A sparrow that lands, hops about, and flies off to land elsewhere. */
export function drawSparrow(ctx: CanvasRenderingContext2D, P: (x: number, y: number, z?: number) => Pt, s: number, x0: number, y0: number, x1: number, y1: number, theme: Theme, t: number): void {
  const cycle = 16, u = (t % cycle) / cycle;
  const k = Math.floor(t / cycle);
  const r = rng("sparrow" + k), r2 = rng("sparrow" + (k + 1));
  const a: Pt = [lerp(x0, x1, r()), lerp(y0, y1, r())], b: Pt = [lerp(x0, x1, r2()), lerp(y0, y1, r2())];
  let pos: Pt, z = 0, hop = 0;
  if (u < 0.7) { // on the ground, hopping now and then
    const hops = Math.floor(u * 10);
    pos = [a[0] + Math.sin(hops * 2.3) * 0.3, a[1] + Math.cos(hops * 1.7) * 0.3];
    hop = Math.abs(Math.sin(u * 10 * Math.PI)) * (hops % 3 === 0 ? 0.15 : 0);
  } else { // flying to the next spot
    const v = (u - 0.7) / 0.3;
    pos = [lerp(a[0], b[0], v), lerp(a[1], b[1], v)];
    z = Math.sin(v * Math.PI) * 2.5;
  }
  const p = P(pos[0], pos[1], z + hop);
  const kk = Math.min(1, s / 30);
  ctx.save(); ctx.translate(p[0], p[1]); ctx.scale(kk, kk);
  ctx.fillStyle = "#8c6a4f"; ctx.beginPath(); ctx.ellipse(0, -2, 3.2, 2.2, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.6; ctx.stroke();
  ctx.beginPath(); ctx.arc(2.8, -3.6, 1.6, 0, 7); ctx.fill();
  ctx.fillStyle = "#ffb347"; ctx.beginPath(); ctx.moveTo(4.2, -3.6); ctx.lineTo(5.8, -3.2); ctx.lineTo(4.2, -2.8); ctx.closePath(); ctx.fill();
  if (z > 0) { ctx.strokeStyle = "#8c6a4f"; ctx.lineWidth = 1.5; const f = Math.sin(t * 25) * 3; ctx.beginPath(); ctx.moveTo(-1, -3); ctx.lineTo(-4, -5 + f); ctx.moveTo(1, -3); ctx.lineTo(3, -5 + f); ctx.stroke(); }
  ctx.restore();
}

export function drawButterflies(ctx: CanvasRenderingContext2D, P: (x: number, y: number, z?: number) => Pt, s: number, spots: Pt[], theme: Theme, t: number): void {
  spots.forEach(([bx, by], i) => {
    const ph = t * 0.7 + i * 2.1;
    const p = P(bx + Math.sin(ph) * 0.8, by + Math.cos(ph * 1.3) * 0.6, 1.2 + Math.sin(ph * 2.2) * 0.4);
    const flap = Math.abs(Math.sin(t * 18 + i)) * 0.6 + 0.4;
    const kk = Math.min(1, s / 30) * 0.9;
    ctx.save(); ctx.translate(p[0], p[1]); ctx.scale(kk, kk);
    ctx.fillStyle = i % 2 ? rgba(theme.accent, 0.9) : "#ffd166";
    for (const sx of [-1, 1]) { ctx.beginPath(); ctx.ellipse(sx * 2.4 * flap, 0, 2.4 * flap, 1.6, 0, 0, 7); ctx.fill(); }
    ctx.strokeStyle = theme.edge.color; ctx.lineWidth = 0.6; ctx.beginPath(); ctx.moveTo(0, -1.6); ctx.lineTo(0, 1.6); ctx.stroke();
    ctx.restore();
  });
}
