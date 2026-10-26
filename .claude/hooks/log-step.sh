#!/usr/bin/env bash
# Stop hook: append a timestamped line to BUILD_LOG.md listing every file
# git reports as changed (staged, unstaged or untracked), whoever edited it.
set -euo pipefail

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
LOG_FILE="BUILD_LOG.md"

# Porcelain lines are "XY path" or "XY old -> new" for renames.
# The log itself is skipped so it doesn't show up in every entry.
FILES=$(git -c core.quotepath=false status --porcelain --untracked-files=all \
  | cut -c4- \
  | sed 's/.* -> //' \
  | grep -vx "$LOG_FILE" \
  | paste -sd, - \
  | sed 's/,/, /g' || true)

[ -z "$FILES" ] && exit 0

[ -f "$LOG_FILE" ] || printf '# Build Log\n\n' > "$LOG_FILE"
printf -- '- %s — changed: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$FILES" >> "$LOG_FILE"
