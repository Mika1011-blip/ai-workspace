import { useEffect, useState } from "react";
import { ApiError, deleteWorker, getCatalog, getToolkit, removeSkill, setToolkit, updateWorker, type Catalog, type Toolkit, type Worker } from "../api";

export default function SettingsTab({ worker, onDeleted, onUpdated }: { worker: Worker; onDeleted: () => void; onUpdated: (w: Worker) => void }) {
  const [text, setText] = useState(worker.instructions);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [kit, setKit] = useState<Toolkit | null>(null);
  const [picks, setPicks] = useState<Toolkit>({ tools: [], mcp_servers: [], read_from: [], skills: [] });
  const [readFrom, setReadFrom] = useState("");
  const [msg, setMsg] = useState<{ text: string; ok: boolean }>({ text: "", ok: true });

  const load = async () => {
    const [c, k] = await Promise.all([getCatalog(), getToolkit(worker.name)]);
    setCatalog(c); setKit(k); setPicks(k); setReadFrom(k.read_from.join(", "));
  };
  useEffect(() => { setText(worker.instructions); load().catch((e) => setMsg({ text: (e as Error).message, ok: false })); }, [worker.name]);

  const toggle = (kind: "tools" | "mcp_servers" | "skills", name: string, on: boolean) =>
    setPicks((p) => ({ ...p, [kind]: on ? [...p[kind], name] : p[kind].filter((n) => n !== name) }));

  const saveMd = async () => {
    try { const u = await updateWorker(worker.name, text); onUpdated(u); setText(u.instructions); setMsg({ text: "Instructions saved.", ok: true }); }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }); }
  };
  const saveKit = async () => {
    try {
      await setToolkit(worker.name, { ...picks, read_from: readFrom.split(",").map((s) => s.trim()).filter(Boolean) });
      await load();
      setMsg({ text: "Toolkit saved; every new session of this worker gets it.", ok: true });
    } catch (e) { setMsg({ text: (e as Error).message, ok: false }); }
  };
  const drop = async (skill: string) => {
    if (!confirm(`Remove the skill "${skill}" from ${worker.name}?`)) return;
    try { await removeSkill(worker.name, skill); await load(); } catch (e) { setMsg({ text: (e as Error).message, ok: false }); }
  };
  const del = async () => {
    if (!confirm(`Delete worker "${worker.name}" and its folder? This cannot be undone.`)) return;
    try { await deleteWorker(worker.name); onDeleted(); }
    catch (e) {
      const err = e as ApiError;
      setMsg({ text: err.status === 403 ? "This worker is protected and cannot be deleted." : err.status === 409 ? "This worker has a running session; end it first." : err.message, ok: false });
    }
  };

  const group = (kind: "tools" | "mcp_servers" | "skills", title: string, hint: string) => (
    <div className="group">
      <h3>{title}</h3>
      <p className="muted small">{hint}</p>
      {catalog && catalog[kind].length ? catalog[kind].map((item) => (
        <label key={item.name} className="check">
          <input type="checkbox" checked={picks[kind].includes(item.name)} onChange={(e) => toggle(kind, item.name, e.target.checked)} />
          <span>{item.name}</span> <span className="muted small">{item.description}</span>
        </label>
      )) : <p className="muted small">(nothing in the catalog)</p>}
    </div>
  );

  return (
    <div className="settings">
      <h3>Instructions (CLAUDE.md)</h3>
      <textarea aria-label="CLAUDE.md" value={text} onChange={(e) => setText(e.target.value)} rows={10} />
      <div className="row"><button type="button" onClick={saveMd}>Save instructions</button></div>
      <h3>Toolkit</h3>
      <p className="muted small">Nothing is allowed unless it is ticked here. The list is the host's catalog (catalog.json and the skill templates).</p>
      {group("tools", "Built-in tools", "Web access for every run of this worker.")}
      {group("mcp_servers", "MCP servers", "Vetted in catalog.json on this machine.")}
      {group("skills", "Skills", "Installed into the worker's .claude/skills/ from the templates.")}
      <h3>Read-only folders</h3>
      <p className="muted small">Repo-relative, under workers/ or projects/, comma-separated.</p>
      <input aria-label="Read-only folders" value={readFrom} onChange={(e) => setReadFrom(e.target.value)} placeholder="workers/writer/outputs, projects/first-reel/artifacts" />
      <div className="row"><button type="button" onClick={saveKit}>Save toolkit</button></div>
      {kit && kit.skills.length > 0 && (
        <>
          <h3>Installed skills</h3>
          <ul className="skills">{kit.skills.map((s) => <li key={s}>{s} <button type="button" className="secondary" onClick={() => drop(s)}>Remove</button></li>)}</ul>
        </>
      )}
      <p className={msg.ok ? "ok" : "error"} role="status">{msg.text}</p>
      <h3>Danger zone</h3>
      <div className="row"><button type="button" className="danger" onClick={del}>Delete worker</button></div>
    </div>
  );
}
