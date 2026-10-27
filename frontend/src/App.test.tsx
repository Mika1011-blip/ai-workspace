import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { FakeEventSource } from "./test/setup";

// The glass needs SVG filters and layout; in jsdom it is just a box.
vi.mock("liquid-glass-react", () => ({ default: ({ children }: { children: React.ReactNode }) => <div data-testid="glass">{children}</div> }));
// The office draws on a canvas; jsdom has no 2D context, so the scene is a no-op here.
vi.mock("./office/Office", () => ({
  default: ({ onPick }: { onPick: (id: string | null) => void }) => <canvas data-testid="office" onClick={() => onPick("renderer")} />,
  sceneNow: () => 0,
}));

const now = () => new Date().toISOString();
const idle = (id: string) => ({ id, status: "idle", current_task: null, tool: null, context_used: 0, updated_at: now(), session_id: null, cost_usd: null, turns: null, simulated: false });

function mockFetch(routes: Record<string, unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    const key = `${init?.method ?? "GET"} ${path}`;
    const body = routes[key] ?? routes[path];
    return new Response(JSON.stringify(body ?? { detail: "unknown" }), { status: body === undefined ? 404 : 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => { FakeEventSource.instances.length = 0; localStorage.clear(); });

test("the strip lists every worker as an avatar with its status, and filters by name", async () => {
  mockFetch({
    "/workers": [{ name: "scriptwriter", instructions: "# s" }, { name: "renderer", instructions: "# r" }],
    "/workers/state": [{ ...idle("scriptwriter"), status: "using_tool", tool: "Write", session_id: "s1", current_task: "x" }, idle("renderer")],
  });
  render(<App />);

  expect(await screen.findByRole("button", { name: "scriptwriter: 🔧 using tool" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "renderer: ○ idle" })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Filter by name"), { target: { value: "rend" } });

  expect(screen.queryByRole("button", { name: /scriptwriter/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /renderer/ })).toBeInTheDocument();
});

test("clicking an avatar opens that worker's panel on the Chat tab; another worker keeps its own tab", async () => {
  mockFetch({
    "/workers": [{ name: "scriptwriter", instructions: "# s" }, { name: "renderer", instructions: "# r" }],
    "/workers/state": [idle("scriptwriter"), idle("renderer")],
    "/runs": [], "/workers/renderer/activity": [], "/workers/scriptwriter/activity": [],
  });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: /^renderer:/ }));

  expect(screen.getByRole("heading", { name: "renderer" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("Task")).toBeInTheDocument(); // no live session → start one

  fireEvent.click(screen.getByRole("tab", { name: "Stats" }));
  expect(await screen.findByText("No runs yet.")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /^scriptwriter:/ }));
  expect(screen.getByRole("heading", { name: "scriptwriter" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");

  fireEvent.click(screen.getByRole("button", { name: /^renderer:/ }));
  expect(screen.getByRole("tab", { name: "Stats" })).toHaveAttribute("aria-selected", "true"); // remembered
});

test("a live state event turns the avatar live, and the add button opens the new-worker form", async () => {
  mockFetch({ "/workers": [{ name: "renderer", instructions: "# r" }], "/workers/state": [idle("renderer")], "/templates": [] });
  render(<App />);
  await screen.findByRole("button", { name: "renderer: ○ idle" });

  act(() => { FakeEventSource.instances[0].emit("state", { at: now(), session_id: "s9", worker: "renderer", status: "thinking", tool: null, context_used: 0.3, cost_usd: 0.05, turns: 1 }); });
  expect(await screen.findByRole("button", { name: "renderer: 💭 thinking" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Add a worker" }));
  expect(await screen.findByRole("heading", { name: "New worker" })).toBeInTheDocument();
  expect(screen.getByText(/Describe what this worker does/)).toBeInTheDocument(); // the preview

  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("heading", { name: "New worker" })).not.toBeInTheDocument();
});

test("clicking a station on the office opens its panel", async () => {
  mockFetch({ "/workers": [{ name: "renderer", instructions: "# r" }], "/workers/state": [idle("renderer")] });
  render(<App />);
  await screen.findByRole("button", { name: /^renderer:/ });

  fireEvent.click(screen.getByTestId("office"));

  expect(screen.getByRole("heading", { name: "renderer" })).toBeInTheDocument();
});
