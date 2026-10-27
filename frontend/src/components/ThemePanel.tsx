import { PRESETS, useTheme } from "../theme";

export default function ThemePanel() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="theme-panel">
      <h2>Theme</h2>
      <p className="muted small">Colour sets for the office and the panes. Edge lines and surface grain are yours to tune.</p>
      <div className="swatches">
        {PRESETS.map((p) => (
          <button key={p.name} type="button" className={`swatch ${p.name === theme.name ? "selected" : ""}`} onClick={() => setTheme({ ...p, edge: { ...theme.edge }, grain: theme.grain })} aria-pressed={p.name === theme.name}>
            <span className="chips" aria-hidden="true">
              <i style={{ background: p.background[0] }} /><i style={{ background: p.slab }} /><i style={{ background: p.machine }} /><i style={{ background: p.accent }} />
            </span>
            {p.name}
          </button>
        ))}
      </div>
      <label>Edge width <output>{theme.edge.width.toFixed(2)} px</output>
        <input type="range" min={0} max={3} step={0.25} value={theme.edge.width} onChange={(e) => setTheme({ ...theme, edge: { ...theme.edge, width: Number(e.target.value) } })} />
      </label>
      <label>Edge colour
        <input type="color" value={theme.edge.color} onChange={(e) => setTheme({ ...theme, edge: { ...theme.edge, color: e.target.value } })} />
      </label>
      <label>Surface grain <output>{Math.round(theme.grain * 100)}%</output>
        <input type="range" min={0} max={1} step={0.05} value={theme.grain} onChange={(e) => setTheme({ ...theme, grain: Number(e.target.value) })} />
      </label>
      <label>Accent
        <input type="color" value={theme.accent} onChange={(e) => setTheme({ ...theme, accent: e.target.value })} />
      </label>
      <button type="button" className="secondary" onClick={() => setTheme(PRESETS[0])}>Reset to Pastel</button>
    </div>
  );
}
