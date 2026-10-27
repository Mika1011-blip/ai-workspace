import { useEffect, useState } from "react";
import { listActivity, listRuns, type ActivityEvent, type RunRecord } from "../api";

const money = (v: number | null | undefined) => (v == null ? "–" : `$${Number(v).toFixed(2)}`);
const ICON: Record<string, string> = { success: "✔", running: "💭", failed: "✖", needs_input: "⏸", skipped: "–" };

export default function StatsTab({ worker }: { worker: string }) {
  const [runs, setRuns] = useState<RunRecord[] | null>(null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    Promise.all([listRuns(worker), listActivity(worker)])
      .then(([r, a]) => { if (alive) { setRuns(r); setEvents(a); } })
      .catch((e) => alive && setError((e as Error).message));
    return () => { alive = false; };
  }, [worker]);
  if (error) return <p className="error">{error}</p>;
  if (!runs) return <p className="muted">Loading…</p>;
  const done = runs.filter((r) => r.status !== "running");
  const ok = done.filter((r) => r.status === "success").length;
  const cost = runs.reduce((s, r) => s + (r.metrics?.cost_usd || 0), 0);
  const turns = done.map((r) => r.metrics?.turns).filter((t): t is number => !!t);
  const durs = done.map((r) => r.metrics?.duration_ms).filter((d): d is number => !!d);
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  return (
    <div className="stats">
      <div className="totals">
        <div><strong>{runs.length}</strong>runs</div>
        <div><strong>{done.length ? `${Math.round((100 * ok) / done.length)}%` : "–"}</strong>success</div>
        <div><strong>{money(cost)}</strong>total cost (estimate)</div>
        <div><strong>{avg(turns)?.toFixed(1) ?? "–"}</strong>avg turns</div>
        <div><strong>{avg(durs) != null ? `${Math.round(avg(durs)! / 1000)} s` : "–"}</strong>avg duration</div>
      </div>
      <h3>Recent runs</h3>
      {runs.length === 0 ? <p className="muted">No runs yet.</p> : (
        <table>
          <thead><tr><th>Started</th><th>Status</th><th>Cost</th><th>Turns</th><th>Summary</th></tr></thead>
          <tbody>
            {runs.slice(0, 15).map((r) => (
              <tr key={r.run_id}>
                <td>{new Date(r.started_at).toLocaleString()}</td>
                <td>{ICON[r.status] ?? "•"} {r.status}</td>
                <td>{money(r.metrics?.cost_usd)}</td>
                <td>{r.metrics?.turns ?? "–"}</td>
                <td>{r.result?.summary || r.error || "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3>Activity (last 20)</h3>
      {events.length === 0 ? <p className="muted">No activity yet.</p> : (
        <ul className="activity">
          {events.slice().reverse().map((e, i) => (
            <li key={i}><span className="muted">{new Date(e.at).toLocaleString()}</span> {e.event}{e.outcome ? ` · ${String(e.outcome)}` : ""}{e.status ? ` · ${String(e.status)}` : ""}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
