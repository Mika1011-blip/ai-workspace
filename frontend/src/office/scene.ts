// The office scene: a function of (model, time, theme) that draws the
// floating tile, the master robot, one desk per worker with its person,
// the showroom, the decor and the ambiance. No business logic lives here;
// the model is built from API data by the Office component.

import { C30, type Pt, type Project, type Style, arrow, box, clamp, ease, face, grainOverlay, hull, inside, lerp, mix, poly, rgba, rng, shade, tag } from "../iso/core";
import type { Theme } from "../theme";
import { drawButterflies, drawCat, drawDog, drawSparrow, stepAnimal } from "./animals";
import { type Decor, drawAmbience, drawDecor, drawSunlight } from "./decor";
import { Nav } from "./nav";
import { drawPerson, look, step as stepPerson } from "./people";
import { ROBOT_D, ROBOT_H, ROBOT_W, drawRobot } from "./robot";

export type StationStatus = "idle" | "thinking" | "using_tool" | "waiting" | "error" | "stale";
export interface StationModel {
  id: string;
  status: StationStatus;
  tool: string | null;
  context: number; // 0..1
  bornAt: number; // scene seconds when it first appeared (for the pop-in)
  isMaster: boolean;
  role: string; // a word that picks the desk prop
}
export interface SceneModel {
  stations: StationModel[];
  selected: string | null;
  showroomLit: boolean; // a new video was published recently
}

/** The desk lamp says the state, one colour each; the screen says it in
 * words and glyphs too, so colour is never alone. */
export const LAMP: Record<StationStatus, string> = { idle: "#9aa3ad", thinking: "#4f8ef7", using_tool: "#ffb020", waiting: "#3ccf9a", error: "#ff6b5b", stale: "#c8c8c8" };
const SCREEN_WORD: Record<StationStatus, string> = { idle: "zZ", thinking: "", using_tool: "", waiting: "?", error: "✖", stale: "no signal" };

export const OWNER_LINE = "Mika's media producer office";
export const CREDIT_LINE = "created by mika1011-blip.github.io";

/** Where everything sits on the tile, in tile units. */
export function layout(stations: StationModel[]) {
  const others = stations.filter((s) => !s.isMaster).sort((a, b) => a.id.localeCompare(b.id));
  const cols = Math.max(2, Math.ceil(Math.sqrt(others.length + 1)));
  const rows = Math.max(1, Math.ceil(others.length / cols));
  const pitch = 4.4;
  const W = Math.max(cols * pitch + 5, 18), D = Math.max(rows * pitch + 11, 16);
  const pos = new Map<string, Pt>();
  const master = stations.find((s) => s.isMaster);
  if (master) pos.set(master.id, [W / 2 - ROBOT_W / 2, D - 5.2]);
  others.forEach((s, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    pos.set(s.id, [1.5 + c * pitch + (r % 2) * 1.2, 1.5 + r * pitch]);
  });
  // the free floor: the band in front of the desks, where people and the cat wander
  const lounge = { x0: 1, y0: rows * pitch + 2.2, x1: W - 1, y1: D - 1 };
  return { pos, W, D, showroom: [1.2, D - 4.6] as Pt, lounge, rows };
}

/** Decor placed around the lounge and the edges, from the tile size. */
export function decorFor(W: number, D: number, rows: number): Decor[] {
  const y = rows * 4.4 + 2.4;
  return [
    { kind: "rug", x: W / 2 - 1.6, y: D - 8.2, r: 3.4 },
    { kind: "sofa", x: W - 4.2, y: D - 3.2 },
    { kind: "coffee", x: W - 2.2, y: y },
    { kind: "cooler", x: W - 1.2, y: y + 1.6 },
    { kind: "shelf", x: 5.2, y: D - 1.9 },
    { kind: "whiteboard", x: W - 3.4, y: 0.4 },
    { kind: "plant", x: 0.6, y: 0.6 }, { kind: "plant", x: W - 1.2, y: D - 1.2 }, { kind: "plant", x: 4.6, y: D - 3.6 }, { kind: "plant", x: W - 5.2, y: y + 0.4 },
    { kind: "plant", x: W / 2 + 2.6, y: D - 1.4 }, { kind: "plant", x: 0.7, y: y + 0.2 }, { kind: "plant", x: W - 0.9, y: 3.2 }, { kind: "plant", x: 2.6, y: D - 1.2 }, { kind: "plant", x: W / 2 - 4.6, y: y + 0.3 },
    { kind: "lamp", x: 2.2, y: y + 1.2 }, { kind: "lamp", x: W - 2.6, y: D - 5.6 },
  ];
}

export interface Hit { id: string; poly: Pt[] }
let lastT = 0;
let navCache: { key: string; nav: Nav } | null = null;

/** Footprints nobody may walk through: desks, the robot, the showroom, the furniture, the trees. */
function navFor(stations: StationModel[], pos: Map<string, Pt>, W: number, D: number, rows: number, showroom: Pt): Nav {
  const key = [W, D, ...[...pos.entries()].map(([id, p]) => `${id}@${p[0]},${p[1]}`)].join(";");
  if (navCache && navCache.key === key) return navCache.nav;
  const nav = new Nav(W, D);
  for (const m of stations) {
    const [x, y] = pos.get(m.id)!;
    if (m.isMaster) nav.block({ x: x - 0.6, y, w: ROBOT_W + 1.2, d: ROBOT_D }, 0.3);
    else nav.block({ x, y, w: 2, d: 1.6 }, 0.15);
  }
  nav.block({ x: showroom[0], y: showroom[1], w: 3.2, d: 2.6 }, 0.3);
  for (const d of decorFor(W, D, rows)) {
    const size = DECOR_SIZE[d.kind];
    if (size[2] > 0) nav.block({ x: d.x, y: d.y, w: size[0], d: size[1] }, d.kind === "lamp" ? 0.1 : 0.2);
  }
  for (const [tx, ty] of [[0.7, D - 0.7], [W - 0.7, 0.7], [W - 0.7, D - 0.7]]) nav.block({ x: tx - 0.3, y: ty - 0.3, w: 0.6, d: 0.6 }, 0.2);
  navCache = { key, nav };
  return nav;
}
const DECOR_SIZE: Record<Decor["kind"], [number, number, number]> = {
  sofa: [2.2, 0.9, 1], coffee: [1.4, 0.7, 1.4], shelf: [1.6, 0.4, 1.6], whiteboard: [2, 0.1, 1.6], rug: [0, 0, 0], lamp: [0.1, 0.1, 2.2], plant: [0.5, 0.5, 1.2], cooler: [0.45, 0.45, 1.0],
};

export function drawOffice(ctx: CanvasRenderingContext2D, W: number, H: number, t: number, model: SceneModel, theme: Theme, zoom = 1, insetLeft = 0, pan: Pt = [0, 0]): Hit[] {
  const st: Style = { theme };
  const dt = clamp(t - lastT, 0, 0.1);
  lastT = t;
  const { pos, W: LX, D: LY, showroom, lounge, rows } = layout(model.stations);
  const nav = navFor(model.stations, pos, LX, LY, rows, showroom);
  // camera: centre the tile in the free part of the screen, scale to fit,
  // slow breathing push, plus whatever the user dragged
  const free = Math.max(200, W - insetLeft);
  const fit = Math.min(free / ((LX + LY) * C30 * 1.1), H / ((LX + LY) * 0.5 + 9));
  const s = fit * zoom * (1 + 0.012 * Math.sin(t * 0.3));
  const bob = Math.sin(t * 1.2) * 2;
  const cx = insetLeft + free / 2 + pan[0], cy = H / 2 + bob - (LX + LY) * 0.25 * s * 0.1 + pan[1];
  const P: Project = (x, y, z = 0) => [cx + ((x - LX / 2) - (y - LY / 2)) * C30 * s, cy + ((x - LX / 2) + (y - LY / 2)) * 0.5 * s - z * s];
  const TH = 0.9;
  const hits: Hit[] = [];

  // ---------- background ----------
  const bg = ctx.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, theme.background[0]);
  bg.addColorStop(0.55, theme.background[1]);
  bg.addColorStop(1, theme.background[2]);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = rgba(theme.muted, 0.12);
  for (let y = 18; y < H; y += 28) for (let x = 18 + ((y / 28) % 2) * 14; x < W; x += 28) ctx.fillRect(x, y, 2, 2);
  {
    const glow = ctx.createRadialGradient(cx, cy, 40, cx, cy, Math.max(W, H) * 0.55);
    glow.addColorStop(0, "rgba(255,255,255,0.65)");
    glow.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, W, H);
  }
  drawAmbience(ctx, W, H, t, theme);
  // long soft shadow under the slab: a few stacked, growing layers (a blur
  // filter every frame is far too slow)
  for (let i = 0; i < 4; i++) {
    const grow = i * 0.35;
    const G = (x: number, y: number): Pt => { const p = P(x + 2.2, y, -TH); return [p[0], p[1] + s * 3.2]; };
    poly(ctx, [G(-grow, -grow), G(LX + grow, -grow), G(LX + grow, LY + grow), G(-grow, LY + grow)], rgba(mix(theme.ink, "#8070c0", 0.5), 0.05));
  }
  // slab + floor
  box(ctx, P, 0.3, 0.3, -TH - 0.6, LX - 0.6, LY - 0.6, 0.6, shade(mix(theme.slab, theme.ink, 0.12)), st, "under");
  box(ctx, P, 0, 0, -TH, LX, LY, TH, shade(theme.slab), st, "slab");
  const tile: Pt[] = [P(0, 0), P(LX, 0), P(LX, LY), P(0, LY)];
  face(ctx, tile, theme.floor, st, "floor");
  ctx.strokeStyle = rgba(theme.muted, 0.18);
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 1; i < LX; i++) { const a = P(i, 0), b = P(i, LY); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
  for (let i = 1; i < LY; i++) { const a = P(0, i), b = P(LX, i); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
  ctx.stroke();
  // the desk zone and the lounge, tinted
  poly(ctx, [P(0.3, 0.3), P(LX - 0.3, 0.3), P(LX - 0.3, rows * 4.4 + 1.2), P(0.3, rows * 4.4 + 1.2)], rgba(theme.machine, 0.12));
  poly(ctx, [P(0.3, lounge.y0 - 0.6), P(LX - 0.3, lounge.y0 - 0.6), P(LX - 0.3, LY - 0.3), P(0.3, LY - 0.3)], rgba(theme.good, 0.07));
  drawSunlight(ctx, tile, t);
  // painted floor words: the owner's name along the front edge, the credit under it
  const floorText = (x: number, y: number, str: string, size: number, alpha: number) => {
    const o = P(x, y);
    ctx.save();
    ctx.transform(C30, 0.5, -C30, 0.5, o[0], o[1]);
    ctx.scale(s / 35, s / 35);
    ctx.font = `800 ${size}px "Inter", system-ui, sans-serif`;
    ctx.fillStyle = rgba(theme.ink, alpha);
    ctx.fillText(str, 0, 0);
    ctx.restore();
  };
  floorText(5.2, LY - 1.3, OWNER_LINE, 24, 0.38);
  floorText(5.2, LY - 0.55, CREDIT_LINE, 13, 0.34);

  // ---------- objects, painter-sorted ----------
  const objs: { key: number; fn: () => void }[] = [];
  const shadows: [number, number, number, number, number][] = [];
  const add = (key: number, fn: () => void) => objs.push({ key, fn });

  // decor
  const plantSpots: Pt[] = [];
  for (const d of decorFor(LX, LY, rows)) {
    const size = DECOR_SIZE[d.kind];
    if (d.kind === "plant") plantSpots.push([d.x + 0.25, d.y + 0.25]);
    if (size[2] > 0) shadows.push([d.x, d.y, size[0], size[1], size[2]]);
    add(d.kind === "rug" ? -1 : d.x + size[0] / 2 + d.y + size[1] / 2, () => drawDecor(ctx, P, s, d, theme, st, t));
  }
  // the animals: a cat and a dog on the floor, a sparrow, butterflies by the plants
  {
    const cat = stepAnimal("cat", nav, lounge.x0, lounge.y0, lounge.x1, lounge.y1, 0.7, 5, t, dt);
    add(cat.pos[0] + cat.pos[1] + 0.3, () => drawCat(ctx, P(cat.pos[0], cat.pos[1]), s, cat, theme, t));
    const dog = stepAnimal("dog", nav, 1, 1, LX - 1, LY - 1, 1.4, 3, t, dt);
    add(dog.pos[0] + dog.pos[1] + 0.3, () => drawDog(ctx, P(dog.pos[0], dog.pos[1]), s, dog, theme, t));
    add(1e5, () => drawSparrow(ctx, P, s, 1, 1, LX - 1, LY - 1, theme, t));
    add(1e5 + 1, () => drawButterflies(ctx, P, s, plantSpots.slice(0, 4), theme, t));
  }

  // stations
  const born = (m: StationModel) => ease.back(clamp((t - m.bornAt) / 0.6));
  for (const m of model.stations) {
    const [x, y] = pos.get(m.id)!;
    const k = born(m);
    if (k <= 0.001) continue;
    const r = rng(m.id);
    const phase = r() * 6.28;
    const isSel = model.selected === m.id;
    if (m.isMaster) {
      shadows.push([x, y, ROBOT_W, ROBOT_D, ROBOT_H * k]);
      hits.push({ id: m.id, poly: [P(x - 0.6, y, 0), P(x + ROBOT_W + 0.6, y, 0), P(x + ROBOT_W + 0.6, y + ROBOT_D, 0), P(x + ROBOT_W + 0.6, y + ROBOT_D, ROBOT_H + 0.8), P(x - 0.6, y + ROBOT_D, ROBOT_H + 0.8), P(x - 0.6, y, ROBOT_H + 0.8)] });
      add(x + ROBOT_W / 2 + y + ROBOT_D / 2, () => {
        ctx.save();
        const base = P(x + ROBOT_W / 2, y + ROBOT_D / 2, 0);
        ctx.translate(base[0], base[1]); ctx.scale(k, k); ctx.translate(-base[0], -base[1]);
        if (isSel) { ctx.shadowColor = rgba(theme.accent, 0.6); ctx.shadowBlur = 24; }
        drawRobot(ctx, P, s, x, y, m.status, theme, st, t + phase);
        ctx.restore();
      });
      add(1e6 + x + y, () => nameTags(ctx, P(x + ROBOT_W / 2, y + ROBOT_D / 2, ROBOT_H + 0.9), m, isSel, t, s, theme, st));
      continue;
    }
    const w = 2, d = 1.6, h = 0.8;
    shadows.push([x, y, w, d, 1.6 * k]);
    hits.push({ id: m.id, poly: [P(x, y, 0), P(x + w, y, 0), P(x + w, y + d, 0), P(x + w, y + d, h + 1.4), P(x, y + d, h + 1.4), P(x, y, h + 1.4)] });
    // the person: seated in front of the desk, or wherever they wandered
    const seat: Pt = [x + 1.0, y + d + 0.5];
    const person = stepPerson(m.id, m.status, seat, { x0: 1, y0: 1, x1: LX - 1, y1: LY - 1 }, nav, t, dt, lounge);
    add(x + w / 2 + y + d / 2, () => {
      ctx.save();
      const base = P(x + w / 2, y + d / 2, 0);
      ctx.translate(base[0], base[1]); ctx.scale(k, k); ctx.translate(-base[0], -base[1]);
      const shake = m.status === "error" ? Math.sin(t * 40) * 0.04 : 0;
      const bodyCol = isSel ? mix(theme.machine, theme.accent, 0.25) : theme.machine;
      const fadeK = m.status === "stale" ? 0.55 : 1;
      ctx.globalAlpha = fadeK;
      box(ctx, P, x + shake, y, 0, w, d, h, shade(bodyCol), st, m.id + "body");
      // monitor at the back of the desk
      box(ctx, P, x + 0.45 + shake, y + 0.15, h, 1.1, 0.12, 0.75, shade(theme.machineDark), st, m.id + "mon");
      const live = m.status === "thinking" || m.status === "using_tool" || m.status === "waiting";
      const flicker = live ? 0.9 + 0.1 * Math.sin(t * 23 + phase) : 1;
      const scr = m.status === "error" ? mix(theme.tagBg, theme.accent, 0.45 + 0.3 * Math.sin(t * 12)) : !live ? mix(theme.tagBg, theme.machineDark, 0.5) : mix(theme.tagBg, theme.good, 0.25 * flicker);
      poly(ctx, [P(x + 0.55 + shake, y + 0.27, h + 0.1), P(x + 1.45 + shake, y + 0.27, h + 0.1), P(x + 1.45 + shake, y + 0.27, h + 0.65), P(x + 0.55 + shake, y + 0.27, h + 0.65)], rgba(scr));
      { // what the screen shows: the state in words and glyphs
        const o = P(x + 0.62 + shake, y + 0.27, h + 0.58);
        ctx.save(); ctx.transform(C30, 0.5, 0, 1, o[0], o[1]); ctx.scale(s / 40, s / 40);
        if (m.status === "thinking") {
          ctx.strokeStyle = rgba(theme.ink, 0.35); ctx.lineWidth = 1.5;
          for (let i = 0; i < 4; i++) { const len = 8 + ((i * 7 + Math.floor(t * 3 + phase)) % 5) * 4; ctx.beginPath(); ctx.moveTo(2, 3 + i * 4); ctx.lineTo(2 + len, 3 + i * 4); ctx.stroke(); }
        } else if (m.status === "using_tool") {
          ctx.strokeStyle = rgba(theme.ink, 0.55); ctx.lineWidth = 1.6;
          ctx.save(); ctx.translate(9, 9); ctx.rotate(t * 3);
          for (let i = 0; i < 6; i++) { ctx.rotate(Math.PI / 3); ctx.beginPath(); ctx.moveTo(0, -3); ctx.lineTo(0, -6); ctx.stroke(); }
          ctx.beginPath(); ctx.arc(0, 0, 3.2, 0, 7); ctx.stroke(); ctx.restore();
          ctx.font = '700 7px "Inter", system-ui, sans-serif'; ctx.fillStyle = rgba(theme.ink, 0.7);
          ctx.fillText((m.tool ?? "").replace(/^mcp__[^_]+__/, "").slice(0, 9), 16, 12);
        } else if (m.status === "stale") {
          const r2 = rng(Math.floor(t * 8) + m.id);
          ctx.fillStyle = rgba(theme.ink, 0.25);
          for (let i = 0; i < 40; i++) ctx.fillRect(r2() * 32, r2() * 18, 2, 1.5);
        } else if (SCREEN_WORD[m.status]) {
          const blink = m.status === "waiting" ? Math.sin(t * 3 + phase) > -0.2 : true;
          if (blink) { ctx.font = `800 ${m.status === "idle" ? 10 : 13}px "Inter", system-ui, sans-serif`; ctx.fillStyle = m.status === "error" ? theme.accent : rgba(theme.ink, 0.55); ctx.fillText(SCREEN_WORD[m.status], 4, 14); }
        }
        ctx.restore();
      }
      prop(ctx, P, s, x + 0.25, y + 1.0, h, m.role, theme, st, t + phase);
      // lamp: the status light
      const lp = P(x + 1.75, y + 1.2, h + 0.35);
      const lampCol = LAMP[m.status];
      const pulse = m.status === "thinking" ? 0.55 + 0.45 * Math.sin(t * 4 + phase) : m.status === "waiting" ? (Math.sin(t * 1.5 + phase) > 0 ? 1 : 0.25) : m.status === "using_tool" ? 1 : m.status === "error" ? 0.8 + 0.2 * Math.sin(t * 12) : 0.12;
      const rr = 0.16 * s;
      { // the lamp's arm and shade
        const base = P(x + 1.85, y + 1.35, h);
        ctx.strokeStyle = theme.machineDark; ctx.lineWidth = 2; ctx.lineCap = "round";
        ctx.beginPath(); ctx.moveTo(base[0], base[1]); ctx.lineTo(lp[0] + 0.06 * s, lp[1] - 0.22 * s); ctx.stroke();
        ctx.fillStyle = rgba(theme.machineDark); ctx.beginPath(); ctx.moveTo(lp[0] - rr * 1.3, lp[1] - rr * 0.2); ctx.lineTo(lp[0] + rr * 1.3, lp[1] - rr * 0.2); ctx.lineTo(lp[0] + rr * 0.6, lp[1] - rr * 1.6); ctx.lineTo(lp[0] - rr * 0.6, lp[1] - rr * 1.6); ctx.closePath(); ctx.fill();
        ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.8; ctx.stroke();
      }
      const glow = ctx.createRadialGradient(lp[0], lp[1], 1, lp[0], lp[1], rr * 3.2);
      glow.addColorStop(0, rgba(lampCol, 0.45 * pulse)); glow.addColorStop(1, rgba(lampCol, 0));
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(lp[0], lp[1], rr * 3.2, 0, 7); ctx.fill();
      ctx.fillStyle = rgba(mix(lampCol, "#ffffff", 1 - pulse * 0.8)); ctx.beginPath(); ctx.arc(lp[0], lp[1], rr, 0, 7); ctx.fill();
      ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
      if (m.status === "using_tool") {
        const c = P(x + 1.0 + shake, y + 0.1, h + 0.95);
        ctx.save(); ctx.translate(c[0], c[1]); ctx.scale(1, 0.577); ctx.rotate(t * 7);
        ctx.fillStyle = theme.tagBg;
        for (let b = 0; b < 3; b++) { ctx.rotate((Math.PI * 2) / 3); ctx.beginPath(); ctx.ellipse(0.11 * s, 0, 0.14 * s, 0.05 * s, 0, 0, 7); ctx.fill(); ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.8; ctx.stroke(); }
        ctx.restore();
      }
      if (m.status === "thinking") {
        for (let i = 0; i < 4; i++) {
          const ph = (t * 0.45 + i / 4 + phase) % 1;
          const z = h + 0.2 + ph * 1.6;
          ctx.globalAlpha = fadeK * Math.sin(ph * Math.PI);
          const sz = 0.18 * (1 - ph * 0.4);
          box(ctx, P, x + 1.3 + Math.sin(i * 2.1) * 0.25, y + 0.9 + Math.cos(i * 1.7) * 0.2, z, sz, sz, sz, shade(i % 2 ? theme.accent : mix(theme.accent, "#ffffff", 0.5)), st, "cube" + i);
        }
        ctx.globalAlpha = fadeK;
      }
      // context gauge: a pile of cubes beside the desk
      const n = Math.round(m.context * 8);
      for (let i = 0; i < n; i++) {
        const col = m.context > 0.8 ? theme.accent : m.context > 0.5 ? mix(theme.accent, theme.machine, 0.5) : theme.machine;
        box(ctx, P, x + w + 0.15, y + d - 0.5, i * 0.22, 0.4, 0.4, 0.2, shade(col), st, "ctx" + i);
      }
      ctx.restore();
    });
    // the person is sorted on their own position so they walk behind and in front of things
    add(person.pos[0] + person.pos[1] + 0.2, () => {
      ctx.save();
      ctx.globalAlpha = m.status === "stale" ? 0.55 : 1;
      drawPerson(ctx, P(person.pos[0], person.pos[1], 0), s, look(m.id), person, m.status, theme, st, t + phase);
      ctx.restore();
    });
    add(1e6 + x + y, () => nameTags(ctx, P(x + w / 2, y + d / 2, h + 1.5), m, isSel, t, s, theme, st));
  }

  // showroom: a small cinema with a marquee
  {
    const [sx, sy] = showroom;
    shadows.push([sx, sy, 3.2, 2.6, 2.2]);
    hits.push({ id: "__showroom", poly: [P(sx, sy), P(sx + 3.2, sy), P(sx + 3.2, sy + 2.6), P(sx + 3.2, sy + 2.6, 3.2), P(sx, sy + 2.6, 3.2), P(sx, sy, 3.2)] });
    add(sx + 1.6 + sy + 1.3, () => {
      box(ctx, P, sx, sy, 0, 3.2, 2.6, 2.0, shade(mix(theme.machine, theme.accent, 0.15)), st, "cinema");
      box(ctx, P, sx + 0.2, sy - 0.1, 2.0, 2.8, 0.3, 0.6, shade(theme.tagBg), st, "marquee");
      poly(ctx, [P(sx + 1.3, sy + 2.6, 0), P(sx + 1.9, sy + 2.6, 0), P(sx + 1.9, sy + 2.6, 1.1), P(sx + 1.3, sy + 2.6, 1.1)], rgba(theme.machineDark));
      poly(ctx, [P(sx + 0.3, sy + 2.6, 0.5), P(sx + 1.0, sy + 2.6, 0.5), P(sx + 1.0, sy + 2.6, 1.5), P(sx + 0.3, sy + 2.6, 1.5)], rgba(theme.accent, 0.85));
      for (let i = 0; i < 7; i++) {
        const p = P(sx + 0.4 + i * 0.4, sy - 0.1, 2.35);
        const on = model.showroomLit ? Math.sin(t * 6 + i) > 0 : Math.sin(t * 1.5 + i * 0.9) > 0.3;
        ctx.fillStyle = on ? "#ffe28a" : rgba(theme.muted, 0.4);
        ctx.beginPath(); ctx.arc(p[0], p[1], 0.07 * s, 0, 7); ctx.fill();
      }
      const p = P(sx + 1.6, sy + 1.3, 3.2);
      tag(ctx, p[0], p[1], "showroom", st, { font: '800 14px "Inter", system-ui, sans-serif', icon: "🎬", k: Math.min(1, s / 34) });
    });
  }

  // trees in the corners
  for (const [tx, ty] of [[0.7, LY - 0.7], [LX - 0.7, 0.7], [LX - 0.7, LY - 0.7]] as Pt[]) {
    shadows.push([tx - 0.3, ty - 0.3, 0.6, 0.6, 1.8]);
    add(tx + ty, () => {
      const b = P(tx, ty), top = P(tx, ty, 1.4), rr = 0.55 * s;
      ctx.strokeStyle = "#b79a8a"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(b[0], b[1]); ctx.lineTo(top[0], top[1] + 4); ctx.stroke();
      const sway = Math.sin(t * 1.5 + tx) * 1.2;
      ctx.fillStyle = rgba(mix(theme.good, "#ffffff", 0.35)); ctx.beginPath(); ctx.arc(top[0] + sway, top[1] - rr * 0.3, rr, 0, 7); ctx.fill();
      ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
      ctx.fillStyle = rgba(mix(theme.good, "#ffffff", 0.6)); ctx.beginPath(); ctx.arc(top[0] + sway - rr * 0.22, top[1] - rr * 0.5, rr * 0.6, 0, 7); ctx.fill();
    });
  }

  // shadows, one layer so overlaps do not double
  {
    ctx.save();
    ctx.globalAlpha = 0.16;
    ctx.fillStyle = rgba(mix(theme.ink, "#8070c0", 0.5));
    ctx.beginPath();
    for (const [x, y, w, d, h] of shadows) {
      const base: Pt[] = [[x, y], [x + w, y], [x + w, y + d], [x, y + d]];
      const pts = hull(base.concat(base.map((p) => [p[0] + 1.1 * h, p[1] + 0.12 * h] as Pt))).map((p) => P(p[0], p[1]));
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.closePath();
    }
    ctx.fill();
    ctx.restore();
  }

  objs.sort((a, b) => a.key - b.key);
  for (const o of objs) { ctx.save(); o.fn(); ctx.restore(); }
  grainOverlay(ctx, W, H, theme.grain);

  // a dashed connector from the master to the selected station
  const master = model.stations.find((m) => m.isMaster);
  if (master && model.selected && model.selected !== master.id && pos.has(model.selected)) {
    const mp = pos.get(master.id)!, [tx, ty] = pos.get(model.selected)!;
    const a = P(mp[0] + ROBOT_W / 2, mp[1], ROBOT_H - 1), b = P(tx + 1, ty + 0.8, 1.2);
    arrow(ctx, [a, [(a[0] + b[0]) / 2, Math.min(a[1], b[1]) - 1.2 * s], b], 1, rgba(theme.machineDark, 0.6), [6, 6], 2);
  }
  return hits;
}

function nameTags(ctx: CanvasRenderingContext2D, p: Pt, m: StationModel, isSel: boolean, t: number, s: number, theme: Theme, st: Style) {
  const k = Math.min(1, s / 34);
  const popK = ease.back(clamp((t - m.bornAt - 0.3) / 0.5)) * k;
  ctx.save();
  ctx.globalAlpha = m.status === "stale" ? 0.7 : 1;
  tag(ctx, p[0], p[1] - 14 * k, m.id, st, { font: '800 16px "Inter", system-ui, sans-serif', k: popK, bg: isSel ? theme.accent : undefined, col: isSel ? "#fff" : undefined });
  if (m.status === "using_tool" && m.tool) tag(ctx, p[0], p[1] + 10 * k, m.tool.replace(/^mcp__[^_]+__/, ""), st, { font: '600 11px "Inter", system-ui, sans-serif', k: popK, bg: theme.machineDark, col: "#fff" });
  if (m.status === "error") tag(ctx, p[0], p[1] + 10 * k, "error", st, { font: '700 11px "Inter", system-ui, sans-serif', k: popK, icon: "✖", bg: rgba(mix(theme.tagBg, theme.accent, 0.25)) });
  ctx.restore();
}

// ---------- desk props ----------
function prop(ctx: CanvasRenderingContext2D, P: Project, s: number, x: number, y: number, z: number, role: string, theme: Theme, st: Style, t: number) {
  const r = role.toLowerCase();
  if (/script|writ|news|digest/.test(r)) {
    box(ctx, P, x, y - 0.3, z, 0.6, 0.45, 0.25, shade(theme.machineDark), st, "tw");
    face(ctx, [P(x + 0.1, y - 0.2, z + 0.26), P(x + 0.5, y - 0.2, z + 0.26), P(x + 0.5, y - 0.2, z + 0.8), P(x + 0.1, y - 0.2, z + 0.8)], theme.tagBg, st, "sheet");
  } else if (/asset|art|draw|design|storyboard/.test(r)) {
    face(ctx, [P(x, y - 0.1, z + 0.1), P(x + 0.6, y - 0.1, z + 0.1), P(x + 0.6, y - 0.1, z + 0.75), P(x, y - 0.1, z + 0.75)], rgba(mix(theme.tagBg, theme.accent, 0.2)), st, "easel");
    ctx.fillStyle = theme.accent; const p = P(x + 0.3, y - 0.1, z + 0.45); ctx.beginPath(); ctx.arc(p[0], p[1], 0.08 * s, 0, 7); ctx.fill();
  } else if (/render|video|publish/.test(r)) {
    const c = P(x + 0.3, y - 0.1, z + 0.35);
    ctx.save(); ctx.translate(c[0], c[1]); ctx.rotate(t * 2);
    ctx.fillStyle = rgba(theme.machineDark); ctx.beginPath(); ctx.arc(0, 0, 0.22 * s, 0, 7); ctx.fill();
    ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
    ctx.fillStyle = theme.tagBg; for (let i = 0; i < 3; i++) { ctx.rotate((Math.PI * 2) / 3); ctx.beginPath(); ctx.arc(0.1 * s, 0, 0.05 * s, 0, 7); ctx.fill(); }
    ctx.restore();
  } else if (/review/.test(r)) {
    const c = P(x + 0.3, y - 0.1, z + 0.3);
    ctx.strokeStyle = theme.edge.color; ctx.lineWidth = Math.max(1.5, theme.edge.width * 1.5);
    ctx.fillStyle = rgba(mix(theme.tagBg, theme.machine, 0.3), 0.8);
    ctx.beginPath(); ctx.arc(c[0], c[1], 0.17 * s, 0, 7); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(c[0] + 0.12 * s, c[1] + 0.12 * s); ctx.lineTo(c[0] + 0.3 * s, c[1] + 0.3 * s); ctx.stroke();
  } else if (/produc|manag|dispatch/.test(r)) {
    box(ctx, P, x, y - 0.3, z, 0.5, 0.5, 0.5, shade(theme.accent), st, "crate");
  } else {
    const b = P(x + 0.3, y - 0.1, z);
    ctx.fillStyle = theme.tagBg; ctx.beginPath(); ctx.roundRect(b[0] - 0.09 * s, b[1] - 0.26 * s, 0.18 * s, 0.24 * s, 3); ctx.fill();
    ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
    ctx.fillStyle = theme.accent; ctx.fillRect(b[0] - 0.09 * s, b[1] - 0.26 * s, 0.18 * s, 0.05 * s);
  }
}

export { inside, lerp };
