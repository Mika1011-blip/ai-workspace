// The people of the office: every worker has a look of their own (seeded by
// name, so it never changes between reloads) and a life of their own: they
// wander the lounge while idle, walk to their desk when work arrives, sit
// and type while busy, and sulk when something went wrong. Walking follows
// the nav grid, so nobody passes through a desk or a sofa.

import { type Pt, type Style, lerp, mix, rgba, rng } from "../iso/core";
import type { Theme } from "../theme";
import type { Nav } from "./nav";
import type { StationStatus } from "./scene";

export interface Look {
  skin: string;
  hair: "none" | "short" | "long" | "bun" | "spiky" | "curly";
  hairColor: string;
  shirt: string;
  trousers: string;
  accessory: "none" | "glasses" | "hat" | "bag" | "headphones";
  height: number; // 0.85..1.15
}

const SKINS = ["#f1c6a8", "#e7b28f", "#c98f67", "#8d5a3b", "#5b3a26", "#f7d8c4"];
const HAIRS = ["#2d2320", "#5a3a22", "#b0702a", "#e8c66a", "#8a8a8a", "#c1452a", "#3b2a6b"];
const SHIRTS = ["#ff6b5b", "#7f8fd8", "#9fd8c2", "#f5b78f", "#ffd166", "#b9c2ea", "#e0a4e8", "#86c5f4"];
const TROUSERS = ["#2d3058", "#4a4f78", "#6b5b95", "#3a5a40", "#7a5c3e", "#8a8a9a"];
const HAIR_STYLES: Look["hair"][] = ["none", "short", "short", "long", "bun", "spiky", "curly"];
const ACCESSORIES: Look["accessory"][] = ["none", "none", "glasses", "hat", "bag", "headphones"];

/** A stable random mix of parts for a worker name. */
export function look(name: string): Look {
  const r = rng("look:" + name);
  const pick = <T,>(xs: T[]) => xs[Math.floor(r() * xs.length)];
  return {
    skin: pick(SKINS), hair: pick(HAIR_STYLES), hairColor: pick(HAIRS), shirt: pick(SHIRTS), trousers: pick(TROUSERS),
    accessory: pick(ACCESSORIES), height: 0.85 + r() * 0.3,
  };
}

export type Mood = "wander" | "toDesk" | "seated" | "upset";
export interface Person {
  id: string;
  pos: Pt; // tile units
  route: Pt[]; // waypoints still to walk
  mood: Mood;
  facing: 1 | -1;
  nextPick: number; // scene time when a new wander target is chosen
  pauseUntil: number;
  stride: number; // walk-cycle phase
}

export interface Bounds { x0: number; y0: number; x1: number; y1: number }

const people = new Map<string, Person>();

/** Advance one person by `dt` seconds. `seat` is where they sit at their desk. */
export function step(id: string, status: StationStatus, seat: Pt, bounds: Bounds, nav: Nav, t: number, dt: number): Person {
  let p = people.get(id);
  if (!p) {
    const start = nav.randomFree("spawn:" + id, bounds.x0, bounds.y0, bounds.x1, bounds.y1) ?? nav.nearestFree([bounds.x0, bounds.y0]);
    p = { id, pos: start, route: [], mood: "wander", facing: 1, nextPick: t, pauseUntil: 0, stride: 0 };
    people.set(id, p);
  }
  const busy = status === "thinking" || status === "using_tool" || status === "waiting";
  if (status === "error") { if (p.mood !== "upset") { p.mood = "upset"; p.route = nav.path(p.pos, nav.nearestFree([seat[0] - 0.7, seat[1] + 0.2])) ?? []; } }
  else if (busy) { if (p.mood !== "seated" && p.mood !== "toDesk") { p.mood = "toDesk"; p.route = nav.path(p.pos, seat) ?? [seat]; } }
  else if (p.mood !== "wander") { p.mood = "wander"; p.route = []; p.nextPick = t; p.pauseUntil = 0; }

  if (p.mood === "wander") {
    if (!p.route.length && t >= p.nextPick) {
      const k = Math.floor(t / 7 + rng("phase:" + id)() * 7);
      const target = nav.randomFree(`${id}:wander:${k}`, bounds.x0, bounds.y0, bounds.x1, bounds.y1);
      if (target) p.route = nav.path(p.pos, target) ?? [];
      p.nextPick = t + 6 + rng(`${id}:${k}`)() * 6;
      p.pauseUntil = t + 1 + rng(`${id}:p${k}`)() * 2; // look around first
    }
    if (t >= p.pauseUntil) follow(p, 0.9, dt);
  } else if (p.mood === "toDesk") {
    if (!follow(p, 3.0, dt)) { p.mood = "seated"; p.pos = [seat[0], seat[1]]; }
  } else if (p.mood === "seated") {
    p.pos = [seat[0], seat[1]];
  } else if (p.mood === "upset") {
    follow(p, 1.5, dt);
  }
  return p;
}

/** Walk along the route; true while there is still somewhere to go. */
function follow(p: Person, speed: number, dt: number): boolean {
  let budget = speed * dt;
  while (p.route.length && budget > 0) {
    const to = p.route[0];
    const dx = to[0] - p.pos[0], dy = to[1] - p.pos[1];
    const dist = Math.hypot(dx, dy);
    if (dist < 0.03) { p.route.shift(); continue; }
    const stepLen = Math.min(dist, budget);
    p.pos = [p.pos[0] + (dx / dist) * stepLen, p.pos[1] + (dy / dist) * stepLen];
    p.stride += stepLen * 6;
    budget -= stepLen;
    const sx = dx - dy; // screen-x direction decides which way the body faces
    if (Math.abs(sx) > 0.05) p.facing = sx > 0 ? 1 : -1;
  }
  return p.route.length > 0;
}

export const isWalking = (p: Person, t: number) => p.route.length > 0 && (p.mood !== "wander" || t >= p.pauseUntil);
export function forget(id: string): void { people.delete(id); }
export function reset(): void { people.clear(); }

/** Draw a person at screen point `p` (feet). */
export function drawPerson(ctx: CanvasRenderingContext2D, p: Pt, s: number, lk: Look, person: Person | null, status: StationStatus, theme: Theme, st: Style, t: number): void {
  const H = 0.95 * s * lk.height * Math.min(1, s / 30);
  const walking = person ? isWalking(person, t) : false;
  const running = person?.mood === "toDesk";
  const seated = person?.mood === "seated";
  const upset = person?.mood === "upset";
  const swing = walking ? Math.sin(person!.stride) * (running ? 0.5 : 0.3) : 0;
  const bob = walking ? Math.abs(Math.sin(person!.stride)) * (running ? 2.2 : 1.2) : seated ? Math.sin(t * 7) * 0.6 : 0;
  const face = person?.facing ?? 1;
  const edge = () => { ctx.strokeStyle = theme.edge.color; ctx.lineWidth = Math.max(0.6, theme.edge.width * 0.7); ctx.stroke(); };
  ctx.save();
  ctx.translate(p[0], p[1] - bob);
  ctx.scale(face, 1);
  ctx.fillStyle = "rgba(80,70,140,0.18)";
  ctx.beginPath(); ctx.ellipse(2, bob + 1, 6, 2.4, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = lk.trousers; ctx.lineWidth = 2.8; ctx.lineCap = "round";
  const legH = seated ? H * 0.3 : H * 0.42;
  ctx.beginPath();
  ctx.moveTo(-2, 0); ctx.lineTo(-2 + swing * 4, -legH);
  ctx.moveTo(2, 0); ctx.lineTo(2 - swing * 4, -legH);
  ctx.stroke();
  const bodyTop = -(legH + H * 0.4);
  ctx.fillStyle = upset ? rgba(mix(lk.shirt, theme.accent, 0.5)) : lk.shirt;
  ctx.beginPath(); ctx.roundRect(-4.5, bodyTop, 9, H * 0.4, 3.5); ctx.fill(); edge();
  ctx.strokeStyle = lk.shirt; ctx.lineWidth = 2.4;
  ctx.beginPath();
  if (upset) { ctx.moveTo(-4, bodyTop + 3); ctx.lineTo(-8, bodyTop - 6 + Math.sin(t * 9) * 2); ctx.moveTo(4, bodyTop + 3); ctx.lineTo(8, bodyTop - 6 - Math.sin(t * 9) * 2); }
  else if (seated) { ctx.moveTo(-4, bodyTop + 4); ctx.lineTo(-1, bodyTop + 9 + Math.sin(t * 14) * 1.2); ctx.moveTo(4, bodyTop + 4); ctx.lineTo(7, bodyTop + 9 - Math.sin(t * 14) * 1.2); }
  else { ctx.moveTo(-4, bodyTop + 3); ctx.lineTo(-5 - swing * 5, bodyTop + 11); ctx.moveTo(4, bodyTop + 3); ctx.lineTo(5 + swing * 5, bodyTop + 11); }
  ctx.stroke();
  if (lk.accessory === "bag") { ctx.fillStyle = theme.machineDark; ctx.beginPath(); ctx.roundRect(5, bodyTop + 5, 4, 6, 1); ctx.fill(); }
  const headY = bodyTop - 4.6;
  ctx.fillStyle = lk.skin; ctx.beginPath(); ctx.arc(0, headY, 3.9, 0, 7); ctx.fill(); edge();
  ctx.fillStyle = lk.hairColor;
  switch (lk.hair) {
    case "short": ctx.beginPath(); ctx.arc(0, headY - 0.6, 3.9, Math.PI * 1.05, Math.PI * 2.05); ctx.fill(); break;
    case "long": ctx.beginPath(); ctx.arc(0, headY - 0.6, 3.9, Math.PI * 1.05, Math.PI * 2.05); ctx.fill(); ctx.fillRect(-4.2, headY - 1, 2.2, 7); break;
    case "bun": ctx.beginPath(); ctx.arc(0, headY - 0.6, 3.9, Math.PI * 1.05, Math.PI * 2.05); ctx.fill(); ctx.beginPath(); ctx.arc(-2.5, headY - 3.5, 1.8, 0, 7); ctx.fill(); break;
    case "spiky": for (let i = -2; i <= 2; i++) { ctx.beginPath(); ctx.moveTo(i * 1.6 - 1, headY - 2.5); ctx.lineTo(i * 1.6, headY - 7); ctx.lineTo(i * 1.6 + 1, headY - 2.5); ctx.closePath(); ctx.fill(); } break;
    case "curly": for (let i = -2; i <= 2; i++) { ctx.beginPath(); ctx.arc(i * 1.7, headY - 3.4, 1.6, 0, 7); ctx.fill(); } break;
    default: break;
  }
  ctx.fillStyle = theme.ink;
  ctx.beginPath(); ctx.arc(1.2, headY - 0.4, 0.55, 0, 7); ctx.arc(2.8, headY - 0.4, 0.55, 0, 7); ctx.fill();
  ctx.strokeStyle = theme.ink; ctx.lineWidth = 0.6;
  ctx.beginPath();
  if (upset) ctx.arc(2, headY + 2.2, 1.1, Math.PI * 1.15, Math.PI * 1.85); else ctx.arc(2, headY + 1, 1.1, 0.15, Math.PI - 0.15);
  ctx.stroke();
  if (lk.accessory === "glasses") { ctx.strokeStyle = theme.ink; ctx.lineWidth = 0.6; ctx.beginPath(); ctx.arc(1.2, headY - 0.4, 1.3, 0, 7); ctx.moveTo(4.1, headY - 0.4); ctx.arc(2.8, headY - 0.4, 1.3, 0, 7); ctx.stroke(); }
  if (lk.accessory === "hat") { ctx.fillStyle = theme.accent; ctx.beginPath(); ctx.roundRect(-4.5, headY - 4.8, 9, 2.2, 1); ctx.fill(); ctx.fillRect(-2.5, headY - 8, 5, 3.6); }
  if (lk.accessory === "headphones") { ctx.strokeStyle = theme.machineDark; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(0, headY - 0.8, 4.4, Math.PI * 1.05, Math.PI * 1.95); ctx.stroke(); ctx.fillStyle = theme.machineDark; ctx.fillRect(-5.2, headY - 1.6, 1.8, 2.6); ctx.fillRect(3.4, headY - 1.6, 1.8, 2.6); }
  if (status === "thinking" && seated) { ctx.fillStyle = rgba(theme.tagBg, 0.9); for (let i = 0; i < 3; i++) { ctx.beginPath(); ctx.arc(4 + i * 2.2, headY - 6 - i * 2.2, 0.8 + i * 0.5, 0, 7); ctx.fill(); } }
  if (status === "using_tool" && seated) { ctx.fillStyle = "#86c5f4"; ctx.beginPath(); ctx.ellipse(5.5, headY - 2 + (t * 10) % 3, 0.9, 1.4, 0, 0, 7); ctx.fill(); }
  ctx.restore();
  void lerp;
}
