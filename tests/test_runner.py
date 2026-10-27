from pathlib import Path

from app.runner import CliRunner, SpawnSpec


def spec(tmp_path, **kw):
    base = dict(
        worker="researcher", task="look", token="t", worker_folder=tmp_path / "researcher",
        shared_dir=tmp_path / "_shared", api_url="http://api",
    )
    base.update(kw)
    return SpawnSpec(**base)


class TestCliRunner:
    def make(self, calls):
        return CliRunner(
            argv_fn=lambda s: ["claude", "--name", s.worker, s.task],
            spawn_fn=lambda argv, cwd: calls.append(("spawn", argv, cwd)) or "backgrounded · abc123 · researcher",
            stop_fn=lambda sid: calls.append(("stop", sid)),
            running_ids_fn=lambda: {"abc123"},
            parse_id=lambda out: out.split(" · ")[1],
        )

    def test_start_builds_argv_runs_it_in_the_worker_folder_and_returns_the_id(self, tmp_path):
        calls = []
        runner = self.make(calls)

        sid = runner.start(spec(tmp_path))

        assert sid == "abc123"
        assert calls == [("spawn", ["claude", "--name", "researcher", "look"], tmp_path / "researcher")]

    def test_stop_and_running_ids_delegate(self, tmp_path):
        calls = []
        runner = self.make(calls)

        runner.stop("abc123")

        assert calls == [("stop", "abc123")]
        assert runner.running_ids() == {"abc123"}

    def test_cli_sessions_cannot_be_messaged_and_have_no_live_state(self, tmp_path):
        runner = self.make([])

        assert runner.send("abc123", "hello") is False
        assert runner.state() == []
        assert runner.name == "cli"
