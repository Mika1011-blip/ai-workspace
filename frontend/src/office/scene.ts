// The office scene: a pure function of (model, time, theme) that draws the
// floating tile, the master's machine in the middle, one station per worker
// around it, the showroom, and the tags. No business logic lives here; the
// model is built from API data by the Office component.

import { C30, Pt, Project, Style, arrow, box, clamp, ease, face, hull, inside, lerp, mix, poly, rgba, rng, shade, tag } from "../iso/core";
import type { Theme } from "../theme";

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
  cards: { from: string; to: string; at: number }[]; // hand-offs riding the belt
}

const STATUS_LABEL: Record<StationStatus, string> = { idle: "idle", thinking: "thinking", using_tool: "using tool", waiting: "waiting", error: "error", stale: "stale" };
const STATUS_ICON: Record<StationStatus, string> = { idle: "○", thinking: "💭", using_tool: "🔧", waiting: "⏸", error: "✖", stale: "?" };

/** Where everything sits on the tile, in tile units. */
export function layout(stations: StationModel[]) {
  const others = stations.filter((s) => !s.isMaster).sort((a, b) => a.id.localeCompare(b.id));
  const cols = Math.max(2, Math.ceil(Math.sqrt(others.length + 1)));
  const rows = Math.max(1, Math.ceil(others.length / cols));
  const pitch = 4.4;
  const W = Math.max(cols * pitch + 5, 16), D = Math.max(rows * pitch + 9, 14);
  const pos = new Map<string, Pt>();
  // the master's machine sits front and centre; the showroom in the front-left corner
  const master = stations.find((s) => s.isMaster);
  if (master) pos.set(master.id, [W / 2 - 2, D - 5.5]);
  others.forEach((s, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    pos.set(s.id, [1.5 + c * pitch + (r % 2) * 1.2, 1.5 + r * pitch]);
  });
  return { pos, W, D, showroom: [1.2, D - 4.6] as Pt };
}

export interface Hit { id: string; poly: Pt[] }

export function drawOffice(ctx: CanvasRenderingContext2D, W: number, H: number, t: number, model: SceneModel, theme: Theme, zoom = 1, insetLeft = 0): Hit[] {
  const st: Style = { theme };
  const { pos, W: LX, D: LY, showroom } = layout(model.stations);
  // camera: centre the tile in the free part of the screen (the pane covers
  // `insetLeft` px on the left), scale to fit, slow breathing push
  const free = Math.max(200, W - insetLeft);
  const fit = Math.min(free / ((LX + LY) * C30 * 1.1), H / ((LX + LY) * 0.5 + 9));
  const s = fit * zoom * (1 + 0.012 * Math.sin(t * 0.3));
  const bob = Math.sin(t * 1.2) * 2;
  const cx = insetLeft + free / 2, cy = H / 2 + bob - (LX + LY) * 0.25 * s * 0.1;
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
  // long soft shadow under the slab
  {
    ctx.save();
    ctx.filter = `blur(${Math.round(s * 0.5)}px)`;
    const G = (x: number, y: number): Pt => { const p = P(x + 2.2, y, -TH); return [p[0], p[1] + s * 3.2]; };
    poly(ctx, [G(0, 0), G(LX, 0), G(LX, LY), G(0, LY)], rgba(mix(theme.ink, "#8070c0", 0.5), 0.16));
    ctx.restore();
  }
  // slab + floor
  box(ctx, P, 0.3, 0.3, -TH - 0.6, LX - 0.6, LY - 0.6, 0.6, shade(mix(theme.slab, theme.ink, 0.12)), st, "under");
  box(ctx, P, 0, 0, -TH, LX, LY, TH, shade(theme.slab), st, "slab");
  face(ctx, [P(0, 0), P(LX, 0), P(LX, LY), P(0, LY)], theme.floor, st, "floor");
  ctx.strokeStyle = rgba(theme.muted, 0.18);
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 1; i < LX; i++) { const a = P(i, 0), b = P(i, LY); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
  for (let i = 1; i < LY; i++) { const a = P(0, i), b = P(LX, i); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
  ctx.stroke();
  // zone tints
  poly(ctx, [P(0.3, 0.3), P(LX - 0.3, 0.3), P(LX - 0.3, LY - 7), P(0.3, LY - 7)], rgba(theme.machine, 0.12));
  // painted floor words
  const floorText = (x: number, y: number, str: string, size = 20) => {
    const o = P(x, y);
    ctx.save();
    ctx.transform(C30, 0.5, -C30, 0.5, o[0], o[1]);
    ctx.scale(s / 35, s / 35);
    ctx.font = `800 ${size}px "Inter", system-ui, sans-serif`;
    ctx.fillStyle = rgba(theme.muted, 0.45);
    ctx.fillText(str, 0, 0);
    ctx.restore();
  };
  floorText(0.8, LY - 0.6, "AI OFFICE");
  floorText(LX - 7.5, LY - 0.6, "DISPATCH →", 16);

  // ---------- objects, painter-sorted ----------
  const objs: { key: number; fn: () => void }[] = [];
  const shadows: [number, number, number, number, number][] = [];
  const add = (key: number, fn: () => void) => objs.push({ key, fn });

  // the conveyor from the master towards the stations
  const master = model.stations.find((m) => m.isMaster);
  const mp = master ? pos.get(master.id)! : null;
  if (mp) {
    const bx = mp[0] - 3.5, by = mp[1] + 1.2, len = 7;
    for (let i = 0; i < len; i++) {
      add(bx + i + 0.5 + by + 0.5, () => {
        box(ctx, P, bx + i, by, 0, 1, 0.9, 0.35, shade(theme.machineDark), st, "belt" + i);
        ctx.strokeStyle = "rgba(255,255,255,0.35)";
        ctx.lineWidth = 1;
        const off = (t * 1.6) % 0.5;
        for (let k = 0; k < 2; k++) {
          const xx = bx + i + k * 0.5 + off;
          if (xx > bx + i + 1) continue;
          const a = P(xx, by, 0.35), b = P(xx, by + 0.9, 0.35);
          ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        }
      });
    }
    // cards: one per recent hand-off, riding for 4 s
    for (const card of model.cards) {
      const u = clamp((t - card.at) / 4);
      if (u >= 1) continue;
      const x = bx + 0.2 + u * (len - 1.2);
      add(x + 0.5 + by + 1.1, () => {
        box(ctx, P, x, by + 0.35, 0.35, 0.9, 0.08, 0.8, shade(theme.tagBg), st, "card");
        const p = P(x + 0.45, by + 0.4, 1.25);
        tag(ctx, p[0], p[1], card.to, st, { font: '700 11px "Inter", system-ui, sans-serif', k: Math.min(1, s / 40) });
      });
    }
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
    const w = m.isMaster ? 4 : 2, d = m.isMaster ? 3.4 : 1.6, h = m.isMaster ? 2.4 : 0.8;
    shadows.push([x, y, w, d, (m.isMaster ? 2.6 : 1.6) * k]);
    const foot: Pt[] = [P(x, y), P(x + w, y), P(x + w, y + d), P(x, y + d)];
    hits.push({ id: m.id, poly: [P(x, y, 0), P(x + w, y, 0), P(x + w, y + d, 0), P(x + w, y + d, h + 1.4), P(x, y + d, h + 1.4), P(x, y, h + 1.4)].map((p) => [p[0], p[1]] as Pt) });
    add(x + w / 2 + y + d / 2, () => {
      ctx.save();
      const base = P(x + w / 2, y + d / 2, 0);
      ctx.translate(base[0], base[1]);
      ctx.scale(k, k);
      ctx.translate(-base[0], -base[1]);
      const shake = m.status === "error" ? Math.sin(t * 40) * 0.04 : 0;
      const bodyCol = m.isMaster ? theme.machine : isSel ? mix(theme.machine, theme.accent, 0.25) : theme.machine;
      const fadeK = m.status === "stale" ? 0.55 : 1;
      ctx.globalAlpha = fadeK;
      // desk / machine body
      box(ctx, P, x + shake, y, 0, w, d, h, shade(bodyCol), st, m.id + "body");
      if (m.isMaster) {
        // glass-top panel with a small net of nodes
        face(ctx, [P(x + 0.3, y + 0.3, h + 0.01), P(x + w - 0.3, y + 0.3, h + 0.01), P(x + w - 0.3, y + d - 0.3, h + 0.01), P(x + 0.3, y + d - 0.3, h + 0.01)], rgba(mix(theme.tagBg, theme.machine, 0.25), 0.9), st, "glass");
        const nodes: Pt[] = [];
        for (let c = 0; c < 3; c++) for (let rr = 0; rr < 3; rr++) nodes.push([x + 0.8 + c * 1.1, y + 0.7 + rr * 1.0]);
        ctx.strokeStyle = rgba(theme.machineDark, 0.5);
        ctx.lineWidth = 1;
        for (let i = 0; i < 9; i++) for (let j = 0; j < 9; j++) {
          if (Math.floor(j / 3) !== Math.floor(i / 3) + 1) continue;
          const a = P(nodes[i][0], nodes[i][1], h + 0.02), b = P(nodes[j][0], nodes[j][1], h + 0.02);
          ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        }
        const live = m.status === "thinking" || m.status === "using_tool";
        nodes.forEach(([nx, ny], i) => {
          const p = P(nx, ny, h + 0.02), rr = 0.14 * s;
          const lit = live ? Math.max(0, Math.sin(t * 5 - i * 0.7)) : 0.1;
          ctx.fillStyle = rgba(mix(theme.machineDark, theme.accent, lit));
          ctx.beginPath(); ctx.ellipse(p[0], p[1], rr, rr * 0.7, 0, 0, 7); ctx.fill();
        });
        // dials on the front
        for (let i = 0; i < 3; i++) {
          const o = P(x + 0.8 + i * 1.1, y + d, h * 0.5);
          ctx.save(); ctx.transform(C30, 0.5, 0, 1, o[0], o[1]); ctx.scale(s / 40, s / 40);
          ctx.fillStyle = theme.tagBg; ctx.beginPath(); ctx.arc(0, 0, 9, 0, 7); ctx.fill();
          ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
          const ang = -0.9 + i * 0.7 + (m.status === "using_tool" ? Math.sin(t * 3 + i) * 0.6 : 0);
          ctx.strokeStyle = theme.ink; ctx.lineWidth = 2.2; ctx.lineCap = "round";
          ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(ang) * 7, Math.sin(ang) * 7); ctx.stroke();
          ctx.restore();
        }
      } else {
        // monitor at the back of the desk
        box(ctx, P, x + 0.45 + shake, y + 0.15, h, 1.1, 0.12, 0.75, shade(theme.machineDark), st, m.id + "mon");
        const scr = m.status === "error" ? mix(theme.tagBg, theme.accent, 0.45 + 0.3 * Math.sin(t * 12)) : m.status === "idle" || m.status === "stale" ? mix(theme.tagBg, theme.machineDark, 0.5) : mix(theme.tagBg, theme.good, 0.25);
        poly(ctx, [P(x + 0.55 + shake, y + 0.27, h + 0.1), P(x + 1.45 + shake, y + 0.27, h + 0.1), P(x + 1.45 + shake, y + 0.27, h + 0.65), P(x + 0.55 + shake, y + 0.27, h + 0.65)], rgba(scr));
        // the role prop, on the desk's left
        prop(ctx, P, s, x + 0.25, y + 1.0, h, m.role, theme, st, t + phase);
        // lamp: the status light
        const lp = P(x + 1.75, y + 1.2, h + 0.35);
        const lampCol = m.status === "error" ? theme.accent : m.status === "idle" || m.status === "stale" ? theme.muted : theme.good;
        const pulse = m.status === "thinking" ? 0.55 + 0.45 * Math.sin(t * 4 + phase) : m.status === "waiting" ? (Math.sin(t * 1.5 + phase) > 0 ? 1 : 0.25) : m.status === "using_tool" ? 1 : 0.35;
        const rr = 0.16 * s;
        const glow = ctx.createRadialGradient(lp[0], lp[1], 1, lp[0], lp[1], rr * 3.2);
        glow.addColorStop(0, rgba(lampCol, 0.45 * pulse)); glow.addColorStop(1, rgba(lampCol, 0));
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(lp[0], lp[1], rr * 3.2, 0, 7); ctx.fill();
        ctx.fillStyle = rgba(mix(lampCol, "#ffffff", 1 - pulse * 0.8)); ctx.beginPath(); ctx.arc(lp[0], lp[1], rr, 0, 7); ctx.fill();
        ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
        // tiny person at the desk
        person(ctx, P(x + 1.0, y + d + 0.3, 0), s, m.status, theme, st, t + phase);
        // using a tool: a spinning fan on the monitor
        if (m.status === "using_tool") {
          const c = P(x + 1.0 + shake, y + 0.1, h + 0.95);
          ctx.save(); ctx.translate(c[0], c[1]); ctx.scale(1, 0.577); ctx.rotate(t * 7);
          ctx.fillStyle = theme.tagBg;
          for (let b = 0; b < 3; b++) { ctx.rotate((Math.PI * 2) / 3); ctx.beginPath(); ctx.ellipse(0.11 * s, 0, 0.14 * s, 0.05 * s, 0, 0, 7); ctx.fill(); ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.8; ctx.stroke(); }
          ctx.restore();
        }
        // thinking: cubes rise from the desk
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
      }
      // context gauge: a pile of cubes beside the desk
      const n = Math.round(m.context * 8);
      for (let i = 0; i < n; i++) {
        const col = m.context > 0.8 ? theme.accent : m.context > 0.5 ? mix(theme.accent, theme.machine, 0.5) : theme.machine;
        box(ctx, P, x + w + 0.15, y + d - 0.5, i * 0.22, 0.4, 0.4, 0.2, shade(col), st, "ctx" + i);
      }
      ctx.restore();
    });
    // the name tag, in screen space, above the station (drawn after the objects)
    add(1e6 + x + y, () => {
      const p = P(x + w / 2, y + d / 2, (m.isMaster ? h + 1.6 : h + 1.5));
      const popK = ease.back(clamp((t - m.bornAt - 0.3) / 0.5)) * Math.min(1, s / 34);
      ctx.save();
      ctx.globalAlpha = m.status === "stale" ? 0.7 : 1;
      tag(ctx, p[0], p[1] - 14 * Math.min(1, s / 34), m.id, st, { font: '800 16px "Inter", system-ui, sans-serif', k: popK, bg: isSel ? theme.accent : undefined, col: isSel ? "#fff" : undefined });
      tag(ctx, p[0], p[1] + 10 * Math.min(1, s / 34), STATUS_LABEL[m.status], st, { font: '600 12px "Inter", system-ui, sans-serif', k: popK, icon: STATUS_ICON[m.status], bg: m.status === "error" ? mix(theme.tagBg, theme.accent, 0.25) as unknown as string : undefined });
      if (m.status === "using_tool" && m.tool) tag(ctx, p[0], p[1] + 32 * Math.min(1, s / 34), m.tool.replace(/^mcp__[^_]+__/, ""), st, { font: '600 11px "Inter", system-ui, sans-serif', k: popK, bg: theme.machineDark, col: "#fff" });
      ctx.restore();
    });
    void foot;
  }

  // showroom: a small cinema with a marquee
  {
    const [sx, sy] = showroom;
    shadows.push([sx, sy, 3.2, 2.6, 2.2]);
    hits.push({ id: "__showroom", poly: [P(sx, sy), P(sx + 3.2, sy), P(sx + 3.2, sy + 2.6), P(sx + 3.2, sy + 2.6, 3.2), P(sx, sy + 2.6, 3.2), P(sx, sy, 3.2)] });
    add(sx + 1.6 + sy + 1.3, () => {
      box(ctx, P, sx, sy, 0, 3.2, 2.6, 2.0, shade(mix(theme.machine, theme.accent, 0.15)), st, "cinema");
      box(ctx, P, sx + 0.2, sy - 0.1, 2.0, 2.8, 0.3, 0.6, shade(theme.tagBg), st, "marquee");
      // door + poster on the front
      poly(ctx, [P(sx + 1.3, sy + 2.6, 0), P(sx + 1.9, sy + 2.6, 0), P(sx + 1.9, sy + 2.6, 1.1), P(sx + 1.3, sy + 2.6, 1.1)], rgba(theme.machineDark));
      poly(ctx, [P(sx + 0.3, sy + 2.6, 0.5), P(sx + 1.0, sy + 2.6, 0.5), P(sx + 1.0, sy + 2.6, 1.5), P(sx + 0.3, sy + 2.6, 1.5)], rgba(theme.accent, 0.85));
      // marquee bulbs
      for (let i = 0; i < 7; i++) {
        const p = P(sx + 0.4 + i * 0.4, sy - 0.1, 2.35);
        const on = model.showroomLit ? Math.sin(t * 6 + i) > 0 : i % 2 === 0;
        ctx.fillStyle = on ? "#ffe28a" : rgba(theme.muted, 0.4);
        ctx.beginPath(); ctx.arc(p[0], p[1], 0.07 * s, 0, 7); ctx.fill();
      }
      const p = P(sx + 1.6, sy + 1.3, 3.2);
      tag(ctx, p[0], p[1], "showroom", st, { font: '800 14px "Inter", system-ui, sans-serif', icon: "🎬", k: Math.min(1, s / 34) });
    });
  }

  // decorative trees in the corners
  for (const [tx, ty] of [[0.7, 0.7], [LX - 0.7, 0.7], [LX - 0.7, LY - 0.7]] as Pt[]) {
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
    // clip to the tile
    ctx.save();
    ctx.beginPath();
    for (const [i, p] of [P(0, 0), P(LX, 0), P(LX, LY), P(0, LY)].entries()) i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
    ctx.closePath();
    ctx.clip();
    ctx.restore();
    ctx.fill();
    ctx.restore();
  }

  objs.sort((a, b) => a.key - b.key);
  for (const o of objs) { ctx.save(); o.fn(); ctx.restore(); }

  // a dashed connector from the master to the selected station
  if (mp && model.selected && model.selected !== master?.id && pos.has(model.selected)) {
    const [tx, ty] = pos.get(model.selected)!;
    const a = P(mp[0] + 2, mp[1], 2.6), b = P(tx + 1, ty + 0.8, 1.2);
    arrow(ctx, [a, [(a[0] + b[0]) / 2, Math.min(a[1], b[1]) - 1.2 * s], b], 1, rgba(theme.machineDark, 0.6), [6, 6], 2);
  }
  return hits;
}

// ---------- props ----------
function prop(ctx: CanvasRenderingContext2D, P: Project, s: number, x: number, y: number, z: number, role: string, theme: Theme, st: Style, t: number) {
  const r = role.toLowerCase();
  if (/script|writ|news|digest/.test(r)) {
    // a typewriter: a small box with a paper sheet
    box(ctx, P, x, y - 0.3, z, 0.6, 0.45, 0.25, shade(theme.machineDark), st, "tw");
    face(ctx, [P(x + 0.1, y - 0.2, z + 0.26), P(x + 0.5, y - 0.2, z + 0.26), P(x + 0.5, y - 0.2, z + 0.8), P(x + 0.1, y - 0.2, z + 0.8)], theme.tagBg, st, "sheet");
  } else if (/asset|art|draw|design|storyboard/.test(r)) {
    // an easel with a canvas
    face(ctx, [P(x, y - 0.1, z + 0.1), P(x + 0.6, y - 0.1, z + 0.1), P(x + 0.6, y - 0.1, z + 0.75), P(x, y - 0.1, z + 0.75)], rgba(mix(theme.tagBg, theme.accent, 0.2)), st, "easel");
    ctx.fillStyle = theme.accent; const p = P(x + 0.3, y - 0.1, z + 0.45); ctx.beginPath(); ctx.arc(p[0], p[1], 0.08 * s, 0, 7); ctx.fill();
  } else if (/render|video|publish/.test(r)) {
    // a projector / film reel
    const c = P(x + 0.3, y - 0.1, z + 0.35);
    ctx.save(); ctx.translate(c[0], c[1]); ctx.rotate(t * 2);
    ctx.fillStyle = rgba(theme.machineDark); ctx.beginPath(); ctx.arc(0, 0, 0.22 * s, 0, 7); ctx.fill();
    ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
    ctx.fillStyle = theme.tagBg; for (let i = 0; i < 3; i++) { ctx.rotate((Math.PI * 2) / 3); ctx.beginPath(); ctx.arc(0.1 * s, 0, 0.05 * s, 0, 7); ctx.fill(); }
    ctx.restore();
  } else if (/review/.test(r)) {
    // a magnifying glass
    const c = P(x + 0.3, y - 0.1, z + 0.3);
    ctx.strokeStyle = theme.edge.color; ctx.lineWidth = Math.max(1.5, theme.edge.width * 1.5);
    ctx.fillStyle = rgba(mix(theme.tagBg, theme.machine, 0.3), 0.8);
    ctx.beginPath(); ctx.arc(c[0], c[1], 0.17 * s, 0, 7); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(c[0] + 0.12 * s, c[1] + 0.12 * s); ctx.lineTo(c[0] + 0.3 * s, c[1] + 0.3 * s); ctx.stroke();
  } else if (/master|produc|manag|dispatch/.test(r)) {
    box(ctx, P, x, y - 0.3, z, 0.5, 0.5, 0.5, shade(theme.accent), st, "crate");
  } else {
    // a mug of coffee
    const b = P(x + 0.3, y - 0.1, z);
    ctx.fillStyle = theme.tagBg; ctx.beginPath(); ctx.roundRect(b[0] - 0.09 * s, b[1] - 0.26 * s, 0.18 * s, 0.24 * s, 3); ctx.fill();
    ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
    ctx.fillStyle = theme.accent; ctx.fillRect(b[0] - 0.09 * s, b[1] - 0.26 * s, 0.18 * s, 0.05 * s);
  }
}

function person(ctx: CanvasRenderingContext2D, p: Pt, s: number, status: StationStatus, theme: Theme, st: Style, t: number) {
  const hh = 0.9 * s * Math.min(1, s / 30);
  const bob = status === "thinking" || status === "using_tool" ? Math.sin(t * 6) * 1.2 : 0;
  ctx.fillStyle = "rgba(80,70,140,0.18)"; ctx.beginPath(); ctx.ellipse(p[0] + 4, p[1] + 1, 6, 2.5, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = theme.machineDark; ctx.lineWidth = 2.6; ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(p[0] - 2, p[1]); ctx.lineTo(p[0] - 1.5, p[1] - hh * 0.42); ctx.moveTo(p[0] + 2, p[1] - 1); ctx.lineTo(p[0] + 1.5, p[1] - hh * 0.42); ctx.stroke();
  ctx.fillStyle = status === "error" ? theme.accent : theme.machine;
  ctx.beginPath(); ctx.roundRect(p[0] - 4.5, p[1] - hh * 0.8 - bob, 9, hh * 0.42, 3.5); ctx.fill();
  ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.8; ctx.stroke();
  ctx.fillStyle = "#f1c6a8"; ctx.beginPath(); ctx.arc(p[0], p[1] - hh * 0.9 - bob, 3.8, 0, 7); ctx.fill(); ctx.stroke();
  ctx.fillStyle = theme.ink; ctx.beginPath(); ctx.arc(p[0] + 0.6, p[1] - hh * 0.93 - bob, 3.9, Math.PI * 1.05, Math.PI * 2.05); ctx.fill();
}

export { inside, lerp };
