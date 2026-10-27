import { useState } from "react";
import type { StateEvent, Worker, WorkerState } from "../api";
import { isLive, shortTask, shownStatus } from "../hooks/useLiveState";
import ChatTab from "./ChatTab";
import GalleryTab from "./GalleryTab";
import NewWorkerForm from "./NewWorkerForm";
import SettingsTab from "./SettingsTab";
import StatsTab from "./StatsTab";
import StatusBadge from "./StatusBadge";
import ThemePanel from "./ThemePanel";

export type PanelMode = { kind: "worker"; name: string } | { kind: "new" } | { kind: "gallery" } | { kind: "theme" };
type Tab = "chat" | "stats" | "settings";
const TABS: Tab[] = ["chat", "stats", "settings"];

export default function Panel({ mode, worker, state, events, onClose, onRefresh, onCreated, onDeleted, onUpdated }: {
  mode: PanelMode;
  worker: Worker | undefined;
  state: WorkerState | undefined;
  events: StateEvent[];
  onClose: () => void;
  onRefresh: () => Promise<void>;
  onCreated: (name: string) => void;
  onDeleted: () => void;
  onUpdated: (w: Worker) => void;
}) {
  // each worker remembers its own tab
  const [tabs, setTabs] = useState<Record<string, Tab>>({});
  const tab = mode.kind === "worker" ? (tabs[mode.name] ?? "chat") : "chat";
  const money = (v: number | null | undefined) => (v == null ? "–" : `$${Number(v).toFixed(2)}`);

  return (
    <section className="panel" aria-label={mode.kind === "worker" ? `${mode.name} panel` : mode.kind}>
      <button type="button" className="icon close" aria-label="Close panel" onClick={onClose}>×</button>
      {mode.kind === "worker" && worker && (
        <>
          <header className="panel-head">
            <h2>{worker.name}</h2>
            <StatusBadge status={shownStatus(state)} />
            <span className="gauge" title="Share of the context window in use">
              context <meter min={0} max={1} value={state?.context_used ?? 0} /> {Math.round((state?.context_used ?? 0) * 100)}%
            </span>
            <span className="muted small">cost {money(state?.cost_usd)} · turns {state?.turns ?? "–"}</span>
            {state?.current_task && <p className="muted small task">{isLive(state) ? "Task" : "Last task"}: {shortTask(state.current_task)}</p>}
          </header>
          <div className="tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t} type="button" role="tab" aria-selected={t === tab} onClick={() => setTabs((m) => ({ ...m, [worker.name]: t }))}>
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          <div className="tab-body" role="tabpanel">
            {tab === "chat" && <ChatTab worker={worker.name} state={state} events={events} onChanged={onRefresh} />}
            {tab === "stats" && <StatsTab worker={worker.name} />}
            {tab === "settings" && <SettingsTab worker={worker} onDeleted={onDeleted} onUpdated={onUpdated} />}
          </div>
        </>
      )}
      {mode.kind === "worker" && !worker && <p className="muted">This worker no longer exists.</p>}
      {mode.kind === "new" && <div className="tab-body"><NewWorkerForm onCreated={onCreated} /></div>}
      {mode.kind === "gallery" && <div className="tab-body"><GalleryTab /></div>}
      {mode.kind === "theme" && <div className="tab-body"><ThemePanel /></div>}
    </section>
  );
}
