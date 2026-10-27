import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { listWorkers, type Worker } from "./api";
import Glass from "./components/Glass";
import Panel, { type PanelMode } from "./components/Panel";
import Sidebar from "./components/Sidebar";
import { shownStatus, useLiveState } from "./hooks/useLiveState";
import Office, { sceneNow } from "./office/Office";
import type { SceneModel, StationModel } from "./office/scene";
import { ThemeContext, applyCssVars, loadTheme, saveTheme, type Theme } from "./theme";

export default function App() {
  const [theme, setThemeState] = useState<Theme>(loadTheme);
  const setTheme = (t: Theme) => { setThemeState(t); saveTheme(t); };
  useEffect(() => { applyCssVars(theme); }, [theme]);

  const [workers, setWorkers] = useState<Worker[]>([]);
  const [mode, setMode] = useState<PanelMode | null>(null);
  const live = useLiveState();
  const born = useRef<Map<string, number>>(new Map());

  const load = useCallback(async () => {
    try { setWorkers(await listWorkers()); } catch { /* the office keeps the last list */ }
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 30_000); return () => clearInterval(id); }, [load]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMode(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const refresh = useCallback(async () => { await Promise.all([load(), live.refresh()]); }, [load, live]);

  // the scene model: one station per worker, from API data only
  const model: SceneModel = useMemo(() => {
    const now = sceneNow();
    const stations: StationModel[] = workers.map((w, i) => {
      if (!born.current.has(w.name)) born.current.set(w.name, now + 0.08 * i);
      const st = live.states.get(w.name);
      return {
        id: w.name,
        status: shownStatus(st),
        tool: st?.tool ?? null,
        context: st?.context_used ?? 0,
        bornAt: born.current.get(w.name)!,
        isMaster: w.name === "app-master",
        role: w.name,
      };
    });
    const cards = [...live.events.values()].flat()
      .filter((e) => e.text?.startsWith("Message from"))
      .slice(-6)
      .map((e) => ({ from: "app-master", to: e.worker, at: sceneNow() - (Date.now() - new Date(e.at).getTime()) / 1000 }));
    return { stations, selected: mode?.kind === "worker" ? mode.name : null, showroomLit: false, cards };
  }, [workers, live.states, live.events, mode]);

  const pick = (id: string | null) => {
    if (id === "__showroom") setMode({ kind: "gallery" });
    else if (id) setMode({ kind: "worker", name: id });
    else setMode(null);
  };
  const selectedWorker = mode?.kind === "worker" ? workers.find((w) => w.name === mode.name) : undefined;

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      <div className="app">
        <Office model={model} onPick={pick} insetLeft={mode ? 64 + 440 + 28 : 64 + 28} />
        <div className={`pane ${mode ? "open" : ""}`}>
          <Glass radius={26} className="pane-glass">
            <div className="pane-inner">
              <Sidebar
                workers={workers}
                states={live.states}
                selected={mode?.kind === "worker" ? mode.name : null}
                mode={mode?.kind ?? null}
                onPick={(name) => setMode({ kind: "worker", name })}
                onAdd={() => setMode({ kind: "new" })}
                onGallery={() => setMode({ kind: "gallery" })}
                onTheme={() => setMode({ kind: "theme" })}
              />
              {mode && (
                <Panel
                  mode={mode}
                  worker={selectedWorker}
                  state={mode.kind === "worker" ? live.states.get(mode.name) : undefined}
                  events={mode.kind === "worker" ? (live.events.get(mode.name) ?? []) : []}
                  onClose={() => setMode(null)}
                  onRefresh={refresh}
                  onCreated={async (name) => { await refresh(); setMode({ kind: "worker", name }); }}
                  onDeleted={async () => { setMode(null); await refresh(); }}
                  onUpdated={(w) => setWorkers((ws) => ws.map((x) => (x.name === w.name ? w : x)))}
                />
              )}
            </div>
          </Glass>
        </div>
        <p className="feed muted small" aria-live="polite">live feed: {live.feed}</p>
      </div>
    </ThemeContext.Provider>
  );
}
