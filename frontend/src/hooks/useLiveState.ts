import { useEffect, useRef, useState } from "react";
import { type StateEvent, type WorkerState, workersState } from "../api";

export interface LiveState {
  states: Map<string, WorkerState>;
  events: Map<string, StateEvent[]>; // per worker, oldest first
  feed: "connecting" | "connected" | "reconnecting";
  refresh: () => Promise<void>;
}

/** Live state of every worker: a snapshot from /workers/state, then every
 * change from the /events stream, re-polled every 30 s as a safety net. */
export function useLiveState(): LiveState {
  const [states, setStates] = useState<Map<string, WorkerState>>(new Map());
  const [feed, setFeed] = useState<LiveState["feed"]>("connecting");
  const events = useRef<Map<string, StateEvent[]>>(new Map());
  const [, bump] = useState(0);

  const refresh = async () => {
    try {
      const list = await workersState();
      setStates(new Map(list.map((s) => [s.id, s])));
    } catch {
      /* keep the last known state */
    }
  };

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30_000);
    const source = new EventSource("/events?replay=200");
    source.addEventListener("state", (msg) => {
      const e = JSON.parse((msg as MessageEvent).data) as StateEvent;
      setStates((prev) => {
        const next = new Map(prev);
        const old = next.get(e.worker);
        next.set(e.worker, {
          id: e.worker,
          simulated: false,
          current_task: old?.current_task ?? null,
          ...old,
          status: e.status,
          tool: e.tool,
          context_used: e.context_used,
          cost_usd: e.cost_usd,
          turns: e.turns,
          updated_at: e.at,
          session_id: e.session_id,
        });
        return next;
      });
      const list = events.current.get(e.worker) ?? [];
      const last = list[list.length - 1];
      if (!last || last.at !== e.at || last.status !== e.status) list.push(e);
      if (list.length > 500) list.shift();
      events.current.set(e.worker, list);
      bump((n) => n + 1);
    });
    source.onopen = () => setFeed("connected");
    source.onerror = () => setFeed("reconnecting");
    return () => {
      clearInterval(timer);
      source.close();
    };
  }, []);

  return { states, events: events.current, feed, refresh };
}

/** What a station should show: a live status with no news for 60 s is stale. */
export function shownStatus(s: WorkerState | undefined): Status | "stale" {
  if (!s) return "idle";
  if (["idle", "error"].includes(s.status) || !s.updated_at) return s.status;
  return Date.now() - new Date(s.updated_at).getTime() > 60_000 ? "stale" : s.status;
}

export const isLive = (s: WorkerState | undefined) => !!s && ["thinking", "using_tool", "waiting"].includes(s.status);

/** A dispatched task carries a long preamble; the master's own words follow "Task from the master:". */
export function shortTask(task: string | null | undefined): string {
  if (!task) return "";
  const marker = "Task from the master:";
  const i = task.indexOf(marker);
  return (i >= 0 ? task.slice(i + marker.length) : task).split("\n")[0].trim();
}

type Status = WorkerState["status"];
