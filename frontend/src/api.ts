// One thin client for the Python API. Every call goes through `api()` so
// errors carry the status and the API's `detail`, and nothing else in the
// app builds URLs by hand.

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* no body */
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : null;
    throw new ApiError(res.status, detail ?? `HTTP ${res.status}`);
  }
  return data as T;
}

// --- shapes the API returns (kept in step with app/main.py) --------------

export type Status = "idle" | "thinking" | "using_tool" | "waiting" | "error";

export interface Worker { name: string; instructions: string }

export interface WorkerState {
  id: string;
  status: Status;
  current_task: string | null;
  tool: string | null;
  context_used: number;
  updated_at: string;
  session_id: string | null;
  cost_usd: number | null;
  turns: number | null;
  simulated: boolean;
}

export interface StateEvent {
  at: string;
  session_id: string;
  worker: string;
  status: Status;
  tool: string | null;
  context_used: number;
  cost_usd: number | null;
  turns: number;
  text?: string;
  host?: boolean; // added locally for the host's own messages
}

export interface Session { session_id: string; worker: string; status: string; run_id: string | null }
export interface Template { name: string; description: string }
export interface RunRecord {
  run_id: string; worker: string; status: string; trigger: string; started_at: string; ended_at: string | null;
  result?: { summary?: string } | null; error?: string | null;
  metrics?: { turns?: number | null; duration_ms?: number | null; cost_usd?: number | null };
}
export interface ActivityEvent { at: string; event: string; [k: string]: unknown }
export interface CatalogItem { name: string; description: string }
export interface Catalog { tools: CatalogItem[]; mcp_servers: CatalogItem[]; skills: CatalogItem[] }
export interface Toolkit { tools: string[]; mcp_servers: string[]; read_from: string[]; skills: string[] }
export interface Project { slug: string; title: string; status: string; has_final?: boolean; has_preview?: boolean; format?: string; renderer?: string }

export const listWorkers = () => api<Worker[]>("GET", "/workers");
export const workersState = () => api<WorkerState[]>("GET", "/workers/state");
export const createWorker = (name: string, instructions?: string) =>
  api<Worker>("POST", "/workers", instructions === undefined ? { name } : { name, instructions });
export const updateWorker = (name: string, instructions: string) => api<Worker>("PUT", `/workers/${encodeURIComponent(name)}`, { instructions });
export const deleteWorker = (name: string) => api<unknown>("DELETE", `/workers/${encodeURIComponent(name)}`);
export const listTemplates = () => api<Template[]>("GET", "/templates");
export const getTemplate = (name: string) => api<{ content: string }>("GET", `/templates/${encodeURIComponent(name)}`);
export const startSession = (worker: string, task: string, tools: string[] = []) => api<Session>("POST", "/sessions", { worker, task, tools });
export const endSession = (id: string) => api<Session>("POST", `/sessions/${id}/end`);
export const sendMessage = (id: string, text: string) => api<{ accepted: boolean; delivered: boolean }>("POST", `/sessions/${id}/messages`, { text });
export const listRuns = (worker: string) => api<RunRecord[]>("GET", `/runs?worker=${encodeURIComponent(worker)}&full=true&limit=100`);
export const listActivity = (worker: string) => api<ActivityEvent[]>("GET", `/workers/${encodeURIComponent(worker)}/activity?limit=20`);
export const getCatalog = () => api<Catalog>("GET", "/catalog");
export const getToolkit = (worker: string) => api<Toolkit>("GET", `/workers/${encodeURIComponent(worker)}/toolkit`);
export const setToolkit = (worker: string, kit: Toolkit) => api<Toolkit>("PUT", `/workers/${encodeURIComponent(worker)}/toolkit`, kit);
export const removeSkill = (worker: string, skill: string) => api<Toolkit>("DELETE", `/workers/${encodeURIComponent(worker)}/toolkit/skills/${encodeURIComponent(skill)}`);
export const listProjects = () => api<Project[]>("GET", "/projects");
