// Themes: a named colour set plus the edge-line settings (docs/ui-spec.md).
// The office canvas, the glass panes and the HTML all read from the same
// theme, chosen from the theme panel and kept in localStorage.

import { createContext, useContext } from "react";

export interface Theme {
  name: string;
  background: [string, string, string]; // page gradient, top-left → bottom-right
  slab: string; // the floating tile's side colour
  floor: string; // the tile's top
  ink: string; // text and dark details
  muted: string;
  accent: string; // the single warm accent (coral in the reference)
  good: string; // success / mint
  machine: string; // machines, desks
  machineDark: string;
  tagBg: string;
  edge: { color: string; width: number };
  grain: number; // 0..1 strength of the hand-drawn surface texture
}

export const PRESETS: Theme[] = [
  {
    name: "Pastel",
    background: ["#f6efe8", "#efeaf4", "#e4e3f3"],
    slab: "#cfc6ea", floor: "#fbf8f3", ink: "#2d3058", muted: "#7b7aa3", accent: "#ff6b5b", good: "#3ccf9a",
    machine: "#aab6e8", machineDark: "#4a5488", tagBg: "#ffffff", edge: { color: "#1f1d33", width: 1.25 }, grain: 0.2,
  },
  {
    name: "Mint",
    background: ["#eef8f1", "#e6f3ee", "#dcebe9"],
    slab: "#b8d9cc", floor: "#f7fbf6", ink: "#1f3a33", muted: "#6b8a80", accent: "#ff7a59", good: "#2fb58a",
    machine: "#9fcbbe", machineDark: "#3f6b60", tagBg: "#ffffff", edge: { color: "#17302a", width: 1.25 }, grain: 0.2,
  },
  {
    name: "Dusk",
    background: ["#e9e1f2", "#dcd3ec", "#cfc6e6"],
    slab: "#a995d6", floor: "#f4eef8", ink: "#2a2140", muted: "#6f6594", accent: "#ff8c5a", good: "#4fd1a0",
    machine: "#9d9ae0", machineDark: "#3f3a7a", tagBg: "#fbf8ff", edge: { color: "#241c3a", width: 1.5 }, grain: 0.25,
  },
  {
    name: "Paper",
    background: ["#fbfaf7", "#f4f3ef", "#ebeae5"],
    slab: "#cdcac3", floor: "#fdfcfa", ink: "#262626", muted: "#6f6f6f", accent: "#e4572e", good: "#3a9f6a",
    machine: "#c9c6bd", machineDark: "#55524b", tagBg: "#ffffff", edge: { color: "#111111", width: 1.75 }, grain: 0.3,
  },
];

const KEY = "ai-workspace.theme";

export function loadTheme(): Theme {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const saved = JSON.parse(raw) as Partial<Theme>;
      const base = PRESETS.find((p) => p.name === saved.name) ?? PRESETS[0];
      return { ...base, ...saved, edge: { ...base.edge, ...(saved.edge ?? {}) } };
    }
  } catch {
    /* storage may be unavailable */
  }
  return PRESETS[0];
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(theme));
  } catch {
    /* ignore */
  }
}

/** Apply the theme to the HTML side as CSS variables. */
export function applyCssVars(theme: Theme, root: HTMLElement = document.documentElement): void {
  const vars: Record<string, string> = {
    "--bg0": theme.background[0], "--bg1": theme.background[1], "--bg2": theme.background[2],
    "--ink": theme.ink, "--muted": theme.muted, "--accent": theme.accent, "--good": theme.good,
    "--machine": theme.machine, "--machine-dark": theme.machineDark, "--tag": theme.tagBg,
    "--edge": theme.edge.color, "--edge-w": `${theme.edge.width}px`,
  };
  for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v);
}

export const ThemeContext = createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({
  theme: PRESETS[0],
  setTheme: () => {},
});
export const useTheme = () => useContext(ThemeContext);
