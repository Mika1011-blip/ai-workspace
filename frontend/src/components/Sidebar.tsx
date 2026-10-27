import { useState } from "react";
import type { Worker, WorkerState } from "../api";
import { shownStatus } from "../hooks/useLiveState";
import { STATUS_LABEL } from "./StatusBadge";

/** The collapsed strip: filter on top, avatars in the middle, add / gallery /
 * theme pinned at the bottom. Pure presentation; the parent owns the state. */
export default function Sidebar({ workers, states, selected, onPick, onAdd, onGallery, onTheme, mode }: {
  workers: Worker[];
  states: Map<string, WorkerState>;
  selected: string | null;
  onPick: (name: string) => void;
  onAdd: () => void;
  onGallery: () => void;
  onTheme: () => void;
  mode: string | null;
}) {
  const [filter, setFilter] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const shown = workers.filter((w) => w.name.includes(filter.trim().toLowerCase()));
  return (
    <nav className="strip" aria-label="Workers">
      <div className={`search ${searchOpen || filter ? "open" : ""}`} onMouseEnter={() => setSearchOpen(true)} onMouseLeave={() => setSearchOpen(false)}>
        <button type="button" className="icon" aria-label="Filter workers" onClick={() => setSearchOpen((o) => !o)}>🔍</button>
        <input aria-label="Filter by name" placeholder="filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <ul className="avatars">
        {shown.map((w) => {
          const st = shownStatus(states.get(w.name));
          const live = ["thinking", "using_tool", "waiting"].includes(st);
          return (
            <li key={w.name}>
              <button
                type="button"
                className={`avatar ${w.name === selected ? "selected" : ""} ${live ? "live" : ""} ${st === "error" ? "error" : ""}`}
                onClick={() => onPick(w.name)}
                aria-label={`${w.name}: ${STATUS_LABEL[st]}`}
                aria-pressed={w.name === selected}
                title={`${w.name} · ${STATUS_LABEL[st]}`}
              >
                <span aria-hidden="true">{initials(w.name)}</span>
                <i className={`dot dot-${st}`} aria-hidden="true" />
              </button>
            </li>
          );
        })}
        {shown.length === 0 && <li className="muted small">no match</li>}
      </ul>
      <div className="pinned">
        <button type="button" className={`icon ${mode === "new" ? "selected" : ""}`} aria-label="Add a worker" data-tip="Add a worker" onClick={onAdd}>＋</button>
        <button type="button" className={`icon ${mode === "gallery" ? "selected" : ""}`} aria-label="Gallery" data-tip="Gallery" onClick={onGallery}>🎬</button>
        <button type="button" className={`icon ${mode === "theme" ? "selected" : ""}`} aria-label="Theme" data-tip="Theme" onClick={onTheme}>🎨</button>
      </div>
    </nav>
  );
}

export function initials(name: string): string {
  const parts = name.split("-").filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
}
