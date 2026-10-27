import { useEffect, useRef, useState } from "react";
import { ApiError, endSession, sendMessage, startSession, type StateEvent, type WorkerState } from "../api";
import { isLive } from "../hooks/useLiveState";
import { STATUS_LABEL } from "./StatusBadge";

export default function ChatTab({ worker, state, events, onChanged }: {
  worker: string; state: WorkerState | undefined; events: StateEvent[]; onChanged: () => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [task, setTask] = useState("");
  const [web, setWeb] = useState(false);
  const [error, setError] = useState("");
  const [local, setLocal] = useState<StateEvent[]>([]); // the host's own messages
  const log = useRef<HTMLDivElement>(null);
  const live = isLive(state) ? state!.session_id : null;
  const lines = [...events, ...local].sort((a, b) => a.at.localeCompare(b.at));

  useEffect(() => { log.current?.scrollTo?.({ top: log.current.scrollHeight }); }, [lines.length]);

  const send = async () => {
    const body = text.trim();
    if (!live || !body) return;
    setError("");
    try {
      const r = await sendMessage(live, body);
      setLocal((l) => [...l, { at: new Date().toISOString(), session_id: live, worker, status: "waiting", tool: null, context_used: 0, cost_usd: null, turns: 0, text: `You: ${body}${r.delivered ? "" : " (logged, not delivered)"}`, host: true }]);
      setText("");
    } catch (e) { setError((e as Error).message); }
  };
  const start = async () => {
    const body = task.trim();
    if (!body) return;
    setError("");
    try {
      await startSession(worker, body, web ? ["WebSearch", "WebFetch"] : []);
      setTask("");
      await onChanged();
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 503 ? "Spawning is disabled on this server (SPAWN_ENABLED=false)." : err.message);
    }
  };
  const end = async () => {
    if (!live || !confirm(`End ${worker}'s session now?`)) return;
    try { await endSession(live); await onChanged(); } catch (e) { setError((e as Error).message); }
  };

  let lastText: string | undefined;
  return (
    <div className="chat">
      <div className="log" ref={log} aria-live="polite">
        {lines.length === 0 && <p className="muted">Nothing yet. Start a session below, or wait for the master to hand this worker a task.</p>}
        {lines.map((e, i) => {
          const showText = e.text && e.text !== lastText;
          if (e.text) lastText = e.text;
          return (
            <div key={i} className={`line ${e.host ? "host" : ""}`}>
              {!e.host && <span className="when">{new Date(e.at).toLocaleTimeString()} {STATUS_LABEL[e.status]}{e.tool ? ` · ${e.tool.replace(/^mcp__[^_]+__/, "")}` : ""}</span>}
              {showText && <p className="text">{e.text}</p>}
            </div>
          );
        })}
      </div>
      <p className="error" role="alert">{error}</p>
      {live ? (
        <div className="composer">
          <textarea aria-label="Message" placeholder="Message this worker (it gets it as its next turn)…" value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); }} />
          <div className="row">
            <button type="button" onClick={send}>Send</button>
            <button type="button" className="danger" onClick={end}>End session</button>
          </div>
        </div>
      ) : (
        <div className="composer">
          <textarea aria-label="Task" placeholder="What should this worker do? It runs in its own folder with only what its toolkit allows." value={task} onChange={(e) => setTask(e.target.value)} />
          <div className="row">
            <button type="button" onClick={start}>Start a session</button>
            <label className="small"><input type="checkbox" checked={web} onChange={(e) => setWeb(e.target.checked)} /> allow web for this run</label>
          </div>
        </div>
      )}
    </div>
  );
}
