// The master as a giant robot: boxy, friendly, with a visor that shows its
// mood, an antenna that blinks when it is busy, and arms that move while it
// works or waits.

import { type Project, type Style, box, mix, poly, rgba, shade } from "../iso/core";
import type { Theme } from "../theme";
import type { StationStatus } from "./scene";

export const ROBOT_W = 2.6, ROBOT_D = 2.2, ROBOT_H = 5.4;

export function drawRobot(ctx: CanvasRenderingContext2D, P: Project, s: number, x: number, y: number, status: StationStatus, theme: Theme, st: Style, t: number): void {
  const busy = status === "thinking" || status === "using_tool";
  const err = status === "error";
  const shake = err ? Math.sin(t * 40) * 0.04 : 0;
  const body = mix(theme.machine, theme.tagBg, 0.15);
  const dark = theme.machineDark;
  const breathe = busy ? Math.sin(t * 2.5) * 0.04 : Math.sin(t * 1.2) * 0.015;
  // feet + legs
  box(ctx, P, x + 0.2 + shake, y + 0.2, 0, 0.9, 0.9, 0.4, shade(dark), st, "footL");
  box(ctx, P, x + 1.5 + shake, y + 0.2, 0, 0.9, 0.9, 0.4, shade(dark), st, "footR");
  box(ctx, P, x + 0.4 + shake, y + 0.4, 0.4, 0.5, 0.5, 1.2, shade(mix(body, dark, 0.3)), st, "legL");
  box(ctx, P, x + 1.7 + shake, y + 0.4, 0.4, 0.5, 0.5, 1.2, shade(mix(body, dark, 0.3)), st, "legR");
  // torso
  const tz = 1.6 + breathe;
  box(ctx, P, x + shake, y, tz, ROBOT_W, ROBOT_D, 2.2, shade(body), st, "torso");
  // chest panel: a screen with a little waveform, and three lights
  poly(ctx, [P(x + 0.4 + shake, y + ROBOT_D, tz + 0.5), P(x + 2.2 + shake, y + ROBOT_D, tz + 0.5), P(x + 2.2 + shake, y + ROBOT_D, tz + 1.5), P(x + 0.4 + shake, y + ROBOT_D, tz + 1.5)], rgba(mix(dark, "#000000", 0.3)));
  {
    const o = P(x + 0.5 + shake, y + ROBOT_D, tz + 1.0);
    ctx.save(); ctx.transform(0.866, 0.5, 0, 1, o[0], o[1]); ctx.scale(s / 40, s / 40);
    ctx.strokeStyle = busy ? theme.good : err ? theme.accent : rgba(theme.good, 0.5); ctx.lineWidth = 2; ctx.lineCap = "round";
    ctx.beginPath();
    for (let i = 0; i <= 24; i++) { const xx = i * 2.6, amp = busy ? 8 : 3; const yy = Math.sin(i * 0.9 + t * (busy ? 9 : 2)) * amp * Math.sin((i / 24) * Math.PI); i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); }
    ctx.stroke();
    ctx.restore();
  }
  for (let i = 0; i < 3; i++) {
    const p = P(x + 0.5 + i * 0.6 + shake, y + ROBOT_D, tz + 1.85);
    const on = busy ? Math.sin(t * 6 + i * 2) > 0 : i === 0;
    ctx.fillStyle = on ? [theme.good, "#ffd166", theme.accent][i] : rgba(dark, 0.6);
    ctx.beginPath(); ctx.arc(p[0], p[1], 0.07 * s, 0, 7); ctx.fill();
    ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width * 0.7; ctx.stroke();
  }
  // arms: swing while busy, hang when idle, up when upset
  const swing = busy ? Math.sin(t * 3) * 0.5 : status === "waiting" ? Math.sin(t * 1.5) * 0.15 : 0;
  const armZ = err ? tz + 2.0 : tz + 0.6 + Math.max(0, swing) * 0.6;
  box(ctx, P, x - 0.55 + shake, y + 0.6, armZ, 0.5, 0.9, 1.3, shade(mix(body, dark, 0.25)), st, "armL");
  box(ctx, P, x + ROBOT_W + 0.05 + shake, y + 0.6, err ? tz + 2.0 : tz + 0.6 + Math.max(0, -swing) * 0.6, 0.5, 0.9, 1.3, shade(mix(body, dark, 0.25)), st, "armR");
  // head
  const hz = tz + 2.2;
  box(ctx, P, x + 0.35 + shake, y + 0.3, hz, 1.9, 1.6, 1.35, shade(body), st, "head");
  // visor on the front (+y face)
  const vis = err ? rgba(mix(theme.accent, "#000", 0.2)) : busy ? rgba(mix(theme.good, "#000", 0.35)) : rgba(mix(dark, "#000", 0.3));
  poly(ctx, [P(x + 0.55 + shake, y + 1.9, hz + 0.45), P(x + 2.05 + shake, y + 1.9, hz + 0.45), P(x + 2.05 + shake, y + 1.9, hz + 1.05), P(x + 0.55 + shake, y + 1.9, hz + 1.05)], vis);
  {
    // eyes on the visor: two bars that blink; ^ ^ when happy, x x when upset
    const o = P(x + 0.8 + shake, y + 1.9, hz + 0.8);
    ctx.save(); ctx.transform(0.866, 0.5, 0, 1, o[0], o[1]); ctx.scale(s / 40, s / 40);
    ctx.strokeStyle = err ? theme.accent : busy ? theme.good : "#9ff5d6"; ctx.lineWidth = 3; ctx.lineCap = "round";
    const blink = Math.sin(t * 0.9) > 0.97 ? 0.2 : 1;
    ctx.beginPath();
    for (const ex of [6, 26]) {
      if (err) { ctx.moveTo(ex - 4, -4); ctx.lineTo(ex + 4, 4); ctx.moveTo(ex + 4, -4); ctx.lineTo(ex - 4, 4); }
      else if (status === "waiting") { ctx.moveTo(ex - 5, 2); ctx.lineTo(ex, -3 * blink); ctx.lineTo(ex + 5, 2); }
      else { ctx.moveTo(ex - 5, 0); ctx.lineTo(ex + 5, 0); if (blink === 1) { ctx.moveTo(ex - 5, -5); ctx.lineTo(ex + 5, -5); } }
    }
    ctx.stroke();
    ctx.restore();
  }
  // antenna
  const ab = P(x + 1.3 + shake, y + 1.1, hz + 1.35), at = P(x + 1.3 + shake, y + 1.1, hz + 2.1);
  ctx.strokeStyle = dark; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.moveTo(ab[0], ab[1]); ctx.lineTo(at[0], at[1]); ctx.stroke();
  const lit = busy ? (Math.sin(t * 8) > 0 ? 1 : 0.2) : 0.5;
  const g = ctx.createRadialGradient(at[0], at[1], 1, at[0], at[1], 0.6 * s);
  g.addColorStop(0, rgba(err ? theme.accent : theme.accent, 0.5 * lit)); g.addColorStop(1, rgba(theme.accent, 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(at[0], at[1], 0.6 * s, 0, 7); ctx.fill();
  ctx.fillStyle = rgba(mix(theme.accent, "#ffffff", 1 - lit * 0.8)); ctx.beginPath(); ctx.arc(at[0], at[1], 0.12 * s, 0, 7); ctx.fill();
  ctx.strokeStyle = theme.edge.color; ctx.lineWidth = theme.edge.width; ctx.stroke();
}
