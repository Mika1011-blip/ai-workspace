import { forget, look, reset, step } from "./people";

beforeEach(() => reset());

test("a worker's look is a random mix of parts, stable for the same name", () => {
  const a = look("scriptwriter"), b = look("scriptwriter"), c = look("renderer");
  expect(a).toEqual(b);
  expect(JSON.stringify(a)).not.toEqual(JSON.stringify(c));
  const looks = ["a", "b", "c", "d", "e", "f", "g", "h"].map(look);
  expect(new Set(looks.map((l) => l.hair)).size).toBeGreaterThan(1);
  expect(new Set(looks.map((l) => l.shirt)).size).toBeGreaterThan(1);
});

const bounds = { x0: 1, y0: 10, x1: 15, y1: 18 };
const seat: [number, number] = [5, 3];

test("an idle worker wanders inside the lounge and never onto the desks", () => {
  let t = 0;
  const seen: [number, number][] = [];
  for (let i = 0; i < 2000; i++) {
    const p = step("w", "idle", seat, bounds, t, 0.05);
    seen.push([...p.pos] as [number, number]);
    t += 0.05;
  }
  for (const [x, y] of seen) {
    expect(x).toBeGreaterThanOrEqual(bounds.x0 - 1e-6);
    expect(x).toBeLessThanOrEqual(bounds.x1 + 1e-6);
    expect(y).toBeGreaterThanOrEqual(bounds.y0 - 1e-6);
  }
  const travelled = seen.reduce((d, p, i) => (i ? d + Math.hypot(p[0] - seen[i - 1][0], p[1] - seen[i - 1][1]) : 0), 0);
  expect(travelled).toBeGreaterThan(5); // they do move about
});

test("when work arrives the worker runs to the desk and sits; when it ends they wander again", () => {
  let t = 0;
  for (let i = 0; i < 40; i++) { step("w", "idle", seat, bounds, t, 0.05); t += 0.05; }
  let p = step("w", "thinking", seat, bounds, t, 0.05);
  expect(p.mood).toBe("toDesk");
  for (let i = 0; i < 200; i++) { p = step("w", "thinking", seat, bounds, t, 0.05); t += 0.05; }
  expect(p.mood).toBe("seated");
  expect(p.pos).toEqual(seat);

  p = step("w", "error", seat, bounds, t, 0.05);
  expect(p.mood).toBe("upset");
  p = step("w", "idle", seat, bounds, t, 0.05);
  expect(p.mood).toBe("wander");
  forget("w");
});
