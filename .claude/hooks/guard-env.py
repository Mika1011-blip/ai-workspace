#!/usr/bin/env python3
"""PreToolUse hook: block Read/Edit/Write/Bash calls that touch a .env file."""

import json
import re
import sys

# Matches ".env" or ".env.<anything>" as a path segment, e.g.:
#   .env, .env.local, .env.production, some/dir/.env.bak
# but not things like "environment.txt" or "foo.envelope".
ENV_FILE_RE = re.compile(r"(^|[\\/])\.env(\.[^\\/]*)?$")

# Looser version for scanning free-form shell commands, where the match
# doesn't have to be the whole path segment (e.g. "cat .env | grep KEY").
ENV_IN_COMMAND_RE = re.compile(r"(^|[\s\"'\\/])\.env(\.[^\s\"'\\/]*)?($|[\s\"'\\/])")


def touches_env_file(path: str) -> bool:
    return bool(ENV_FILE_RE.search(path.replace("\\", "/")))


def command_touches_env_file(command: str) -> bool:
    return bool(ENV_IN_COMMAND_RE.search(command))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool_name in ("Read", "Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        if file_path and touches_env_file(file_path):
            print(
                f"Blocked: {tool_name} on {file_path!r} — .env files are off-limits "
                "to tool calls (they hold secrets). Ask the user to share the "
                "specific value you need instead.",
                file=sys.stderr,
            )
            return 2

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if command and command_touches_env_file(command):
            print(
                f"Blocked: Bash command references a .env file — .env files are "
                f"off-limits to tool calls (they hold secrets).\nCommand: {command}",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
