import { C30, hull, inside, makeIso, mix, rng, shade } from "./core";

test("the projection is a true 30° isometric", () => {
  const P = makeIso(100, 50, 10);
  expect(P(0, 0, 0)).toEqual([100, 50]);
  expect(P(1, 0, 0)[0]).toBeCloseTo(100 + C30 * 10);
  expect(P(1, 0, 0)[1]).toBeCloseTo(55);
  expect(P(0, 1, 0)[0]).toBeCloseTo(100 - C30 * 10);
  expect(P(0, 0, 1)).toEqual([100, 40]); // up is up
});

test("seeded randomness is deterministic", () => {
  const a = rng("station-x"), b = rng("station-x"), c = rng("station-y");
  expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  expect(a()).not.toEqual(c());
});

test("three-tone shading lightens the top and darkens the right face", () => {
  const f = shade("#aab6e8");
  const lum = (s: string) => s.match(/\d+/g)!.slice(0, 3).map(Number).reduce((x, y) => x + y, 0);
  expect(lum(f.top)).toBeGreaterThan(lum(f.left));
  expect(lum(f.left)).toBeGreaterThan(lum(f.right));
  expect(mix("#000000", "#ffffff", 0.5).map(Math.round)).toEqual([128, 128, 128]);
});

test("hull and point-in-polygon pick a station footprint", () => {
  const h = hull([[0, 0], [4, 0], [4, 4], [0, 4], [2, 2]]);
  expect(h).toHaveLength(4);
  expect(inside([2, 2], h)).toBe(true);
  expect(inside([5, 2], h)).toBe(false);
});
