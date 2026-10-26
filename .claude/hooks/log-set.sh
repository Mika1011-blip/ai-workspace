#!/usr/bin/env bash
# Stop hook: append a timestamped line to build_log.md listing the files
# Claude changed (via Edit/Write/MultiEdit/NotebookEdit) during this turn.
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
LOG_FILE="$PROJECT_DIR/build_log.md"

PY=$(command -v python || command -v python3 || true)
[ -z "$PY" ] && exit 0

# Hook input JSON arrives on stdin; the parser prints a comma-separated file list.
FILES=$(PROJECT_DIR="$PROJECT_DIR" "$PY" -c '
import json, os, sys

data = json.load(sys.stdin)
path = data.get("transcript_path")
if not path or not os.path.exists(path):
    sys.exit(0)

entries = []
with open(path, encoding="utf-8") as f:
    for line in f:
        try:
            entries.append(json.loads(line))
        except ValueError:
            pass

def is_user_prompt(e):
    if e.get("type") != "user":
        return False
    content = e.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    return not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content or [])

# The turn starts at the last real user prompt (not a tool result).
start = 0
for i, e in enumerate(entries):
    if is_user_prompt(e):
        start = i

root = os.environ["PROJECT_DIR"]
files = []
for e in entries[start:]:
    if e.get("type") != "assistant":
        continue
    for c in e.get("message", {}).get("content") or []:
        if not isinstance(c, dict) or c.get("type") != "tool_use":
            continue
        if c.get("name") not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            continue
        inp = c.get("input", {})
        p = inp.get("file_path") or inp.get("notebook_path")
        if not p:
            continue
        try:
            p = os.path.relpath(p, root)
        except ValueError:
            pass
        p = p.replace(os.sep, "/")
        if p not in files:
            files.append(p)

print(", ".join(files))
')

[ -z "$FILES" ] && exit 0

[ -f "$LOG_FILE" ] || printf '# Build Log\n\n' > "$LOG_FILE"
printf -- '- %s — %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$FILES" >> "$LOG_FILE"
