import { PRESETS, applyCssVars, loadTheme, saveTheme } from "./theme";

beforeEach(() => localStorage.clear());

test("four presets, each with the single accent and an edge line", () => {
  expect(PRESETS.map((p) => p.name)).toEqual(["Pastel", "Mint", "Dusk", "Paper"]);
  for (const p of PRESETS) {
    expect(p.background).toHaveLength(3);
    expect(p.edge.width).toBeGreaterThan(0);
    expect(p.accent).toMatch(/^#[0-9a-f]{6}$/i);
  }
});

test("a saved theme comes back, with adjusted edges on top of its preset", () => {
  expect(loadTheme().name).toBe("Pastel");
  saveTheme({ ...PRESETS[2], edge: { color: "#000000", width: 2.5 }, grain: 0.1 });

  const t = loadTheme();

  expect(t.name).toBe("Dusk");
  expect(t.edge).toEqual({ color: "#000000", width: 2.5 });
  expect(t.grain).toBe(0.1);
  expect(t.accent).toBe(PRESETS[2].accent);
});

test("the HTML side follows the theme through CSS variables", () => {
  const root = document.createElement("div");

  applyCssVars({ ...PRESETS[1], edge: { color: "#123456", width: 1.75 } }, root);

  expect(root.style.getPropertyValue("--accent")).toBe(PRESETS[1].accent);
  expect(root.style.getPropertyValue("--edge")).toBe("#123456");
  expect(root.style.getPropertyValue("--edge-w")).toBe("1.75px");
});
