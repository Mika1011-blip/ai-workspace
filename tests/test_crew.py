import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import crew as crew_mod
from scripts.crew import Crew, CrewError


class FakeRun:
    """Stands in for subprocess.run: records every command, answers like the
    real tools would, and creates the worktree folder like git does."""

    def __init__(self, running_ids=(), merged_branches=()):
        self.calls = []
        self.running_ids = list(running_ids)
        self.merged_branches = list(merged_branches)
        self.stop_fails = False

    def __call__(self, argv, cwd=None, capture_output=True, text=True, check=True):
        self.calls.append((argv, cwd))
        out = ""
        if argv[:3] == ["git", "worktree", "add"]:
            Path(argv[-2]).mkdir(parents=True, exist_ok=True)
        elif argv[:3] == ["git", "worktree", "remove"]:
            Path(argv[-1]).rmdir()
        elif argv[:2] == ["git", "branch"] and "--merged" in argv:
            out = "\n".join(self.merged_branches)
        elif argv[1:2] == ["--bg"]:
            session_uuid = argv[argv.index("--session-id") + 1]
            out = f"backgrounded · {session_uuid[:8]} · {argv[argv.index('--name') + 1]}\n"
        elif argv[1:2] == ["stop"]:
            if self.stop_fails:
                raise subprocess.CalledProcessError(1, argv, stderr="no such session")
            out = f"stopped {argv[2]}\n"
        elif argv[1:3] == ["agents", "--json"]:
            out = json.dumps([{"kind": "background", "id": i} for i in self.running_ids])
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / ".claude" / "crew" / "roles").mkdir(parents=True)
    (tmp_path / ".claude" / "crew" / "roles" / "ping-tester.md").write_text("# ping-tester\n\nFollow COMMS.md.\n", encoding="utf-8")
    (tmp_path / ".claude" / "crew" / "registry.json").write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(crew_mod, "claude_cli", lambda: "claude")
    return tmp_path


def fixed_now():
    return datetime(2026, 10, 28, 8, 0, 3, tzinfo=timezone.utc)


def registry(root):
    return json.loads((root / ".claude" / "crew" / "registry.json").read_text(encoding="utf-8"))


def records(root, role):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / ".claude" / "crew" / "runs" / role).glob("*.json"))]


def activity(root, role):
    path = root / ".claude" / "crew" / "runs" / role / "activity.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


class TestSpawn:
    def test_worktree_branch_session_and_books(self, root):
        run = FakeRun()
        crew = Crew(root, run=run, now=fixed_now)

        out = crew.spawn("ping-tester", "reply pong", tags=["scope:ops"])

        sid = out["session_id"]
        assert len(sid) == 8
        assert out["branch"] == f"work/ping-tester-{sid}"
        assert Path(out["worktree"]) == root / ".claude" / "worktrees" / f"ping-tester-{sid}"
        assert Path(out["worktree"]).is_dir()

        wt_add = next(c for c in run.calls if c[0][:3] == ["git", "worktree", "add"])
        assert wt_add[0] == ["git", "worktree", "add", "-b", out["branch"], out["worktree"], "main"]

        spawn_call = next(c for c in run.calls if c[0][1:2] == ["--bg"])
        argv, cwd = spawn_call
        assert cwd == out["worktree"]
        assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
        assert "--strict-mcp-config" in argv
        assert argv[argv.index("--session-id") + 1].startswith(sid)
        assert argv[argv.index("--name") + 1] == "ping-tester"
        assert ".claude/crew/roles/ping-tester.md" in argv[-1] and "reply pong" in argv[-1]
        assert str(root / ".claude" / "crew" / "registry.json") in argv[-1]

        (entry,) = registry(root)
        assert entry["session_id"] == sid and entry["status"] == "live"
        assert entry["worktree"] == f".claude/worktrees/ping-tester-{sid}" and entry["branch"] == out["branch"]
        assert entry["may_talk_to"] == ["lead"]

        (rec,) = records(root, "ping-tester")
        assert rec["run_id"] == out["run_id"] and rec["session_id"] == sid
        assert rec["status"] == "running" and rec["trigger"] == "manual"
        assert {"worker:ping-tester", "trigger:manual", "env:local", "scope:ops"} <= set(rec["tags"])
        assert activity(root, "ping-tester")[0]["event"] == "spawned"

    def test_missing_brief_refuses_before_touching_git(self, root):
        run = FakeRun()
        crew = Crew(root, run=run)

        with pytest.raises(CrewError, match="roles/nobody.md"):
            crew.spawn("nobody", "task")

        assert run.calls == []
        assert registry(root) == []

    def test_bad_tag_refuses(self, root):
        crew = Crew(root, run=FakeRun())

        with pytest.raises(crew_mod.run_records.BadTag):
            crew.spawn("ping-tester", "task", tags=["mood:happy"])


class TestEnd:
    def _spawned(self, root, **fake_kwargs):
        run = FakeRun(**fake_kwargs)
        crew = Crew(root, run=run, now=fixed_now)
        out = crew.spawn("ping-tester", "reply pong")
        run.merged_branches = fake_kwargs.get("merged_branches", []) or run.merged_branches
        return crew, run, out

    def test_merged_branch_is_fully_cleaned_up(self, root):
        crew, run, out = self._spawned(root)
        run.merged_branches = [out["branch"]]

        result = crew.end(out["session_id"], status="success", summary="pong received")

        assert result["stopped"] is True
        assert result["registry"] == "ended"
        assert result["record"] == "success"
        assert result["worktree"] == "removed"
        assert not Path(out["worktree"]).exists()
        assert ["git", "branch", "-d", out["branch"]] in [c[0] for c in run.calls]
        (entry,) = registry(root)
        assert entry["status"] == "ended" and entry["ended_at"] is not None
        (rec,) = records(root, "ping-tester")
        assert rec["status"] == "success" and rec["result"] == {"summary": "pong received"}
        assert rec["ended_at"] is not None and rec["metrics"]["duration_ms"] == 0
        assert activity(root, "ping-tester")[-1]["event"] == "ended"

    def test_unmerged_branch_keeps_the_worktree(self, root):
        crew, run, out = self._spawned(root)

        result = crew.end(out["session_id"], status="failed")

        assert result["worktree"].startswith("kept:")
        assert Path(out["worktree"]).exists()
        assert registry(root)[0]["status"] == "ended"  # the books still close
        assert records(root, "ping-tester")[0]["status"] == "failed"

    def test_force_removes_an_unmerged_worktree(self, root):
        crew, run, out = self._spawned(root)

        result = crew.end(out["session_id"], status="skipped", force=True)

        assert result["worktree"] == "removed"
        assert ["git", "branch", "-D", out["branch"]] in [c[0] for c in run.calls]

    def test_already_gone_session_still_closes_the_books(self, root):
        crew, run, out = self._spawned(root)
        run.stop_fails = True

        result = crew.end(out["session_id"])

        assert result["stopped"] is False
        assert registry(root)[0]["status"] == "ended"

    def test_unknown_id_is_harmless(self, root):
        crew = Crew(root, run=FakeRun(), now=fixed_now)

        result = crew.end("deadbeef")

        assert result == {"session_id": "deadbeef", "stopped": True, "registry": "missing", "record": None, "worktree": "none"}


class TestRebuild:
    def test_closes_what_is_no_longer_running(self, root):
        run = FakeRun()
        crew = Crew(root, run=run, now=fixed_now)
        keep = crew.spawn("ping-tester", "a")["session_id"]
        gone = crew.spawn("ping-tester", "b")["session_id"]
        run.running_ids = [keep]

        result = crew.rebuild()

        assert result == {"closed": [gone], "live": [keep]}
        by_id = {e["session_id"]: e for e in registry(root)}
        assert by_id[keep]["status"] == "live" and by_id[gone]["status"] == "ended"
        gone_rec = next(r for r in records(root, "ping-tester") if r["session_id"] == gone)
        assert gone_rec["status"] == "failed" and gone_rec["error"] == "process gone before reporting a result"
        assert activity(root, "ping-tester")[-1] == {**activity(root, "ping-tester")[-1], "event": "reconciled", "session_id": gone}


def test_cli_reports_errors_on_stderr(root, monkeypatch, capsys):
    monkeypatch.setattr(crew_mod, "ROOT", root)
    monkeypatch.setattr(crew_mod.subprocess, "run", FakeRun())

    code = crew_mod.main(["spawn", "nobody", "task"])

    assert code == 1
    assert "roles/nobody.md" in capsys.readouterr().err
