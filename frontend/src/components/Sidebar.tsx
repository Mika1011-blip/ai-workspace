import { useRef, useState } from "react";
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
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  // the field stays unfolded while the mouse is over it, while it has focus,
  // and while it holds text; the mouse leaving does not close it mid-typing
  const open = hover || focus || filter.length > 0;
  const shown = workers.filter((w) => w.name.includes(filter.trim().toLowerCase()));
  return (
    <nav className="strip" aria-label="Workers">
      <div className={`search ${open ? "open" : ""}`} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        <button type="button" className="icon" aria-label="Filter workers" onClick={() => { setFocus(true); setTimeout(() => input.current?.focus(), 0); }}>🔍</button>
        <input
          ref={input}
          aria-label="Filter by name"
          placeholder="filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onFocus={() => setFocus(true)}
          onBlur={() => setFocus(false)}
          onKeyDown={(e) => { if (e.key === "Escape") { setFilter(""); input.current?.blur(); } }}
          tabIndex={open ? 0 : -1}
        />
        {filter && <button type="button" className="icon clear" aria-label="Clear filter" onClick={() => { setFilter(""); input.current?.focus(); }}>×</button>}
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
