// Where feet may go: a coarse grid over the tile with the footprints of
// desks, the robot, the showroom and the furniture blocked out, and an A*
// over it so people and animals walk around things instead of through them.

import type { Pt } from "../iso/core";
import { rng } from "../iso/core";

export const CELL = 0.5;

export interface Rect { x: number; y: number; w: number; d: number }

export class Nav {
  readonly cols: number;
  readonly rows: number;
  private blocked: Uint8Array;
  constructor(readonly W: number, readonly D: number) {
    this.cols = Math.ceil(W / CELL);
    this.rows = Math.ceil(D / CELL);
    this.blocked = new Uint8Array(this.cols * this.rows);
    // the tile's rim is off limits too
    for (let c = 0; c < this.cols; c++) for (let r = 0; r < this.rows; r++) {
      const x = (c + 0.5) * CELL, y = (r + 0.5) * CELL;
      if (x < 0.6 || y < 0.6 || x > W - 0.6 || y > D - 0.6) this.blocked[r * this.cols + c] = 1;
    }
  }
  /** Block a footprint, grown by `margin` so nobody brushes the furniture. */
  block(rect: Rect, margin = 0.25): void {
    const c0 = Math.max(0, Math.floor((rect.x - margin) / CELL)), c1 = Math.min(this.cols - 1, Math.floor((rect.x + rect.w + margin) / CELL));
    const r0 = Math.max(0, Math.floor((rect.y - margin) / CELL)), r1 = Math.min(this.rows - 1, Math.floor((rect.y + rect.d + margin) / CELL));
    for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) this.blocked[r * this.cols + c] = 1;
  }
  cell(p: Pt): [number, number] { return [Math.floor(p[0] / CELL), Math.floor(p[1] / CELL)]; }
  centre(c: number, r: number): Pt { return [(c + 0.5) * CELL, (r + 0.5) * CELL]; }
  free(p: Pt): boolean {
    const [c, r] = this.cell(p);
    return c >= 0 && r >= 0 && c < this.cols && r < this.rows && !this.blocked[r * this.cols + c];
  }
  /** A random free point inside a rectangle, seeded; null if none in 40 tries. */
  randomFree(seed: string, x0: number, y0: number, x1: number, y1: number): Pt | null {
    const r = rng(seed);
    for (let i = 0; i < 40; i++) {
      const p: Pt = [x0 + r() * (x1 - x0), y0 + r() * (y1 - y0)];
      if (this.free(p)) return p;
    }
    return null;
  }
  /** The nearest free cell centre to `p` (search rings outward). */
  nearestFree(p: Pt): Pt {
    if (this.free(p)) return p;
    const [c0, r0] = this.cell(p);
    for (let ring = 1; ring < 12; ring++) {
      for (let dc = -ring; dc <= ring; dc++) for (let dr = -ring; dr <= ring; dr++) {
        if (Math.max(Math.abs(dc), Math.abs(dr)) !== ring) continue;
        const c = c0 + dc, r = r0 + dr;
        if (c >= 0 && r >= 0 && c < this.cols && r < this.rows && !this.blocked[r * this.cols + c]) return this.centre(c, r);
      }
    }
    return p;
  }
  /** A* over the grid, 8 neighbours, no corner cutting. Returns waypoints
   * (tile units) from just after `from` up to `to`, or null if unreachable. */
  path(from: Pt, to: Pt): Pt[] | null {
    const start = this.cell(this.nearestFree(from)), goal = this.cell(this.nearestFree(to));
    const key = (c: number, r: number) => r * this.cols + c;
    const sk = key(...start), gk = key(...goal);
    if (sk === gk) return [to];
    const g = new Map<number, number>([[sk, 0]]);
    const came = new Map<number, number>();
    const open: [number, number][] = [[0, sk]]; // [f, key]
    const h = (k: number) => { const c = k % this.cols, r = Math.floor(k / this.cols); return Math.hypot(c - goal[0], r - goal[1]); };
    const closed = new Set<number>();
    let guard = 0;
    while (open.length && guard++ < 20000) {
      open.sort((a, b) => a[0] - b[0]);
      const [, k] = open.shift()!;
      if (k === gk) break;
      if (closed.has(k)) continue;
      closed.add(k);
      const c = k % this.cols, r = Math.floor(k / this.cols);
      for (let dc = -1; dc <= 1; dc++) for (let dr = -1; dr <= 1; dr++) {
        if (!dc && !dr) continue;
        const nc = c + dc, nr = r + dr;
        if (nc < 0 || nr < 0 || nc >= this.cols || nr >= this.rows) continue;
        if (this.blocked[key(nc, nr)]) continue;
        if (dc && dr && (this.blocked[key(c + dc, r)] || this.blocked[key(c, r + dr)])) continue; // no corner cutting
        const nk = key(nc, nr), cost = (g.get(k) ?? 0) + (dc && dr ? 1.414 : 1);
        if (cost < (g.get(nk) ?? Infinity)) { g.set(nk, cost); came.set(nk, k); open.push([cost + h(nk), nk]); }
      }
    }
    if (!came.has(gk)) return null;
    const cells: number[] = [];
    for (let k = gk; k !== sk; k = came.get(k)!) cells.push(k);
    cells.reverse();
    // drop cells that lie on a straight run so the walk looks natural
    const pts = cells.map((k) => this.centre(k % this.cols, Math.floor(k / this.cols)));
    const out: Pt[] = [];
    for (let i = 0; i < pts.length; i++) {
      if (i > 0 && i < pts.length - 1) {
        const a = pts[i - 1], b = pts[i], c = pts[i + 1];
        if (Math.sign(b[0] - a[0]) === Math.sign(c[0] - b[0]) && Math.sign(b[1] - a[1]) === Math.sign(c[1] - b[1])) continue;
      }
      out.push(pts[i]);
    }
    out[out.length - 1] = to;
    return out;
  }
}
