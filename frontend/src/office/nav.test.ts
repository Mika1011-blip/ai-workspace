import { Nav } from "./nav";
import { reset, step } from "./people";
import { resetAnimals, stepAnimal } from "./animals";

function office(): Nav {
  const nav = new Nav(20, 20);
  nav.block({ x: 8, y: 8, w: 4, d: 2 }); // a desk across the middle
  return nav;
}

test("blocked cells are not free; the rim is blocked", () => {
  const nav = office();
  expect(nav.free([10, 9])).toBe(false);
  expect(nav.free([10, 12])).toBe(true);
  expect(nav.free([0.2, 10])).toBe(false);
});

test("a path goes around a desk, never through it", () => {
  const nav = office();
  const route = nav.path([10, 5], [10, 14])!;
  expect(route).not.toBeNull();
  expect(route[route.length - 1]).toEqual([10, 14]);
  for (const p of route) expect(nav.free(p)).toBe(true);
  expect(route.length).toBeGreaterThan(1); // it had to bend
});

test("a target inside a desk is moved to the nearest free spot", () => {
  const nav = office();
  const route = nav.path([3, 3], [10, 9])!;
  for (const p of route.slice(0, -1)) expect(nav.free(p)).toBe(true);
});

test("people and animals walking around never stand inside a blocked cell", () => {
  reset(); resetAnimals();
  const nav = new Nav(20, 20);
  nav.block({ x: 4, y: 4, w: 3, d: 2 }); nav.block({ x: 12, y: 10, w: 2, d: 5 }); nav.block({ x: 6, y: 13, w: 5, d: 1 });
  const bounds = { x0: 1, y0: 1, x1: 19, y1: 19 };
  let t = 0;
  for (let i = 0; i < 3000; i++) {
    const p = step("w", "idle", [5, 7], bounds, nav, t, 0.05);
    const a = stepAnimal("dog", nav, 1, 1, 19, 19, 1.5, 2, t, 0.05);
    expect(nav.free(p.pos)).toBe(true);
    expect(nav.free(a.pos)).toBe(true);
    t += 0.05;
  }
});

test("a worker walks to the seat around obstacles when work arrives", () => {
  reset();
  const nav = office();
  const seat: [number, number] = [10, 11]; // just below the desk
  let t = 0;
  let p = step("w", "idle", seat, { x0: 1, y0: 1, x1: 19, y1: 6 }, nav, t, 0.05);
  for (let i = 0; i < 400; i++) { p = step("w", "thinking", seat, { x0: 1, y0: 1, x1: 19, y1: 6 }, nav, t, 0.05); t += 0.05; }
  expect(p.mood).toBe("seated");
  expect(p.pos).toEqual(seat);
});
