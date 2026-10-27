"""Crew worker lifecycle, done deterministically instead of by hand.

    python scripts/crew.py spawn <role> "<task>" [--tag scope:code ...]
    python scripts/crew.py end <id> [--status success|failed|skipped] [--summary "..."] [--force]
    python scripts/crew.py rebuild

Each crew worker runs in its own git worktree (.claude/worktrees/<role>-<id>,
branch work/<role>-<id>) so it can't trample the lead's checkout; `end`
removes the worktree only once its branch is merged into main. The lead is
the only writer of .claude/crew/registry.json; records and activity follow
docs/run-record.md under .claude/crew/runs/<role>/.
"""

import argparse
import json
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import run_records  # noqa: E402

# Must match the lead's session, or Claude Code holds every message between
# them and a background worker can never approve the hold.
LEAD_PERMISSION_MODE = "bypassPermissions"


class CrewError(Exception):
    pass


def claude_cli() -> str:
    path = shutil.which("claude")
    if path is None:
        raise CrewError("claude CLI not found on PATH")
    return path


def parse_spawned_id(stdout: str) -> str:
    parts = [p.strip() for p in stdout.strip().split("·")]
    if len(parts) < 2 or not parts[1]:
        raise CrewError(f"could not parse a session id from: {stdout!r}")
    return parts[1]


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Crew:
    def __init__(self, root: Path, run=subprocess.run, now=None):
        self.root = Path(root)
        self.run = run
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.crew = self.root / ".claude" / "crew"
        self.registry_path = self.crew / "registry.json"
        self.roles = self.crew / "roles"
        self.runs = self.crew / "runs"
        self.worktrees = self.root / ".claude" / "worktrees"

    # -- helpers -------------------------------------------------------------

    def sh(self, argv: list[str], cwd: Path | None = None, check: bool = True) -> str:
        result = self.run(
            argv, cwd=str(cwd or self.root), capture_output=True,
            encoding="utf-8", errors="replace", check=check,
        )
        return result.stdout

    def load_registry(self) -> list[dict]:
        if not self.registry_path.is_file():
            return []
        return json.loads(self.registry_path.read_text(encoding="utf-8") or "[]")

    def save_registry(self, entries: list[dict]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")

    def activity(self, role: str, event: str, fields: dict) -> None:
        path = self.runs / role / "activity.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": stamp(self.now()), "event": event, **fields}) + "\n")

    def record_for(self, session_id: str) -> tuple[Path, dict] | None:
        for path in sorted(self.runs.glob("*/*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("session_id") == session_id:
                return path, record
        return None

    # -- commands ------------------------------------------------------------

    def spawn(self, role: str, task: str, tags: list[str] | None = None) -> dict:
        brief = self.roles / f"{role}.md"
        if not brief.is_file():
            raise CrewError(f"no brief at {brief.relative_to(self.root).as_posix()} -- ask the lead for it first")
        # The worktree must exist before the session starts in it, but Claude
        # Code assigns the session id itself (it ignores --session-id), so the
        # branch and folder carry a short random tag instead; the id is
        # recorded next to it once known.
        tag = secrets.token_hex(3)
        branch = f"work/{role}-{tag}"
        worktree = self.worktrees / f"{role}-{tag}"
        self.worktrees.mkdir(parents=True, exist_ok=True)
        self.sh(["git", "worktree", "add", "-b", branch, str(worktree), "main"])

        prompt = (
            f"Read .claude/crew/roles/{role}.md and .claude/crew/COMMS.md, then: {task}\n"
            f"You are on branch {branch} in worktree {worktree}. "
            f"The crew registry is {self.registry_path} (read it right before every send). "
            "When done, open a PR from your branch and message the lead."
        )
        sid = parse_spawned_id(
            self.sh(
                [
                    claude_cli(),
                    "--bg",
                    "--permission-mode", LEAD_PERMISSION_MODE,
                    "--strict-mcp-config",  # no .mcp.json servers -> no approval prompt to hang on
                    "--name", role,
                    prompt,
                ],
                cwd=worktree,
            )
        )

        started = self.now()
        entries = self.load_registry()
        entries.append(
            {
                "session_id": sid,
                "role": role,
                "folder": None,
                "worktree": str(worktree.relative_to(self.root)).replace("\\", "/"),
                "branch": branch,
                "status": "live",
                "spawned_by": "lead",
                "started_at": stamp(started),
                "ended_at": None,
                "may_talk_to": ["lead"],
            }
        )
        self.save_registry(entries)

        record = run_records.new_record(
            role, sid, "manual", list(tags or []), started, brief.read_text(encoding="utf-8")
        )
        record_path = self.runs / role / f"{record['run_id']}.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        self.activity(role, "spawned", {"session_id": sid, "run_id": record["run_id"], "trigger": "manual", "task": task})
        return {"session_id": sid, "role": role, "branch": branch, "worktree": str(worktree), "run_id": record["run_id"]}

    def end(self, sid: str, status: str = "success", summary: str | None = None, force: bool = False) -> dict:
        if status not in run_records.REPORTABLE_STATUSES:
            raise CrewError(f"status must be one of {sorted(run_records.REPORTABLE_STATUSES)}")
        out: dict = {"session_id": sid, "stopped": False, "registry": "missing", "record": None, "worktree": "none"}
        try:
            self.sh([claude_cli(), "stop", sid])
            out["stopped"] = True
        except subprocess.CalledProcessError:
            out["stopped"] = False  # already gone; still close the books

        now = self.now()
        entries = self.load_registry()
        entry = next((e for e in entries if e["session_id"] == sid), None)
        if entry is not None:
            entry["status"] = "ended"
            entry["ended_at"] = stamp(now)
            self.save_registry(entries)
            out["registry"] = "ended"

        found = self.record_for(sid)
        if found is not None:
            path, record = found
            run_records.finish(record, now, status, None if status == "success" else f"ended by lead as {status}")
            if summary:
                record["result"] = {"summary": summary}
            path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            out["record"] = record["status"]
            self.activity(record["worker"], "ended", {"session_id": sid, "run_id": record["run_id"], "status": record["status"]})

        if entry and entry.get("worktree"):
            worktree = self.root / entry["worktree"]
            branch = entry.get("branch")
            if worktree.exists():
                merged = branch is not None and branch in self.sh(
                    ["git", "branch", "--merged", "main", "--format=%(refname:short)"]
                ).split()
                if merged or force:
                    self.sh(["git", "worktree", "remove", "--force", str(worktree)])
                    if branch:
                        self.sh(["git", "branch", "-D" if force else "-d", branch])
                    out["worktree"] = "removed"
                else:
                    out["worktree"] = f"kept: {branch} is not merged into main (use --force to drop it)"
        return out

    def rebuild(self) -> dict:
        listing = json.loads(self.sh([claude_cli(), "agents", "--json"]) or "[]")
        running = {e.get("id") or str(e.get("sessionId", ""))[:8] for e in listing}
        now = self.now()
        closed = []
        entries = self.load_registry()
        for entry in entries:
            if entry["status"] == "live" and entry["session_id"] not in running:
                entry["status"] = "ended"
                entry["ended_at"] = stamp(now)
                closed.append(entry["session_id"])
                found = self.record_for(entry["session_id"])
                if found is not None:
                    path, record = found
                    run_records.finish(record, now, "failed", "process gone before reporting a result")
                    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
                self.activity(entry["role"], "reconciled", {"session_id": entry["session_id"], "reason": "process gone"})
        self.save_registry(entries)
        live = [e["session_id"] for e in entries if e["status"] == "live"]
        return {"closed": closed, "live": live}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crew", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("spawn")
    p.add_argument("role")
    p.add_argument("task")
    p.add_argument("--tag", action="append", default=[], help="extra key:value tag (scope:, topic:)")
    p = sub.add_parser("end")
    p.add_argument("session_id")
    p.add_argument("--status", default="success", choices=sorted(run_records.REPORTABLE_STATUSES))
    p.add_argument("--summary")
    p.add_argument("--force", action="store_true", help="remove the worktree even if its branch isn't merged")
    sub.add_parser("rebuild")
    args = parser.parse_args(argv)

    crew = Crew(ROOT)
    try:
        if args.cmd == "spawn":
            result = crew.spawn(args.role, args.task, args.tag)
        elif args.cmd == "end":
            result = crew.end(args.session_id, args.status, args.summary, args.force)
        else:
            result = crew.rebuild()
    except (CrewError, run_records.BadTag, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        print(f"error: {detail}".strip(), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
