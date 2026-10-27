// Status is never colour alone: an icon and the word, always.
export const STATUS_LABEL: Record<string, string> = {
  idle: "○ idle",
  thinking: "💭 thinking",
  using_tool: "🔧 using tool",
  waiting: "⏸ waiting",
  error: "✖ error",
  stale: "? stale",
};

export default function StatusBadge({ status }: { status: string }) {
  const live = ["thinking", "using_tool", "waiting"].includes(status);
  return (
    <span className={`badge${status === "error" ? " badge-error" : ""}${live ? " badge-live" : ""}`} role="status">
      {STATUS_LABEL[status] ?? `• ${status}`}
    </span>
  );
}
