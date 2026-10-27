import { useEffect, useMemo, useState } from "react";
import { ApiError, createWorker, getTemplate, listTemplates, type Template } from "../api";

const starter = (name: string) => `# ${name || "worker-name"}\n\nDescribe what this worker does and how it should work.\n`;

export function buildInstructions(name: string, role: string, body: string | null): string {
  const src = body ?? starter(name);
  const lines = src.split("\n");
  const hasHeading = lines[0].startsWith("# ");
  const rest = (hasHeading ? lines.slice(1).join("\n") : src).replace(/^\n+/, "");
  const roleLine = role ? `\n**Role:** ${role}\n` : "";
  return `# ${name || "worker-name"}\n${roleLine}\n${rest}`.replace(/\n{3,}/g, "\n\n");
}

export default function NewWorkerForm({ onCreated }: { onCreated: (name: string) => void }) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [bodies, setBodies] = useState<Map<string, string>>(new Map());
  const [template, setTemplate] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { listTemplates().then(setTemplates).catch(() => setError("Could not load templates; you can still create a blank worker.")); }, []);
  useEffect(() => {
    if (!template || bodies.has(template)) return;
    getTemplate(template).then((t) => setBodies((b) => new Map(b).set(template, t.content))).catch((e) => setError((e as Error).message));
  }, [template, bodies]);
  const preview = useMemo(() => buildInstructions(name.trim(), role.trim(), template ? (bodies.get(template) ?? null) : null), [name, role, template, bodies]);

  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError("");
    const n = name.trim();
    try { await createWorker(n, preview); onCreated(n); }
    catch (e) {
      const err = e as ApiError;
      setError(err.status === 409 ? "A worker with that name already exists." : err.status === 400 ? "Use lowercase letters, numbers and single dashes (e.g. code-reviewer), up to 40 characters." : err.message);
    }
  };
  return (
    <form className="new-worker" onSubmit={submit}>
      <h2>New worker</h2>
      <p className="muted small">Pick a starting template, name the worker and describe its role. The preview is exactly what gets written to its CLAUDE.md.</p>
      <label>Template
        <select value={template} onChange={(e) => setTemplate(e.target.value)}>
          <option value="">Blank (no template)</option>
          {templates.map((t) => <option key={t.name} value={t.name}>{t.description ? `${t.name} — ${t.description}` : t.name}</option>)}
        </select>
      </label>
      <label>Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="code-reviewer" autoComplete="off" required /></label>
      <label>Role<input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Reviews pull requests for bugs and style" autoComplete="off" /></label>
      <label>Preview: CLAUDE.md<pre className="preview">{preview}</pre></label>
      <p className="error" role="alert">{error}</p>
      <button type="submit">Create worker</button>
    </form>
  );
}
