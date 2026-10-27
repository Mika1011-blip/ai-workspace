import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_sessions import (  # noqa: F401 -- fixtures and fakes shared with the session tests
    SPAWNED,
    STOPPED,
    _reset_fakes,
    create_worker,
    make_app,
    messages_log,
    sessions_db,
    spawn,
    templates_dir,
    workers_dir,
)


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    # Grants are given relative to the repo root; make tmp_path that root.
    monkeypatch.chdir(tmp_path)
    return tmp_path / "projects"


@pytest.fixture
def client(workers_dir, templates_dir, sessions_db, messages_log, projects_dir):
    return TestClient(
        make_app(
            workers_dir, templates_dir, sessions_db, messages_log, projects_dir=projects_dir
        )
    )


def argv_of(res):
    assert res.status_code == 201, res.json()
    argv, _ = SPAWNED[-1]
    return argv


def settings_of(argv):
    return json.loads(argv[argv.index("--settings") + 1])


def add_dirs_of(argv):
    start = argv.index("--add-dir") + 1
    end = next(i for i in range(start, len(argv)) if argv[i].startswith("--"))
    return argv[start:end]


def rule(path):
    # The documented rule form: absolute, and a Windows drive as a lower-case
    # folder (//c/...). Spelled out here on purpose, not imported from the app.
    resolved = path.resolve()
    posix = resolved.as_posix()
    if resolved.drive:
        drive, rest = posix.split(":", 1)
        return "//" + drive.lower() + rest
    return "//" + posix.lstrip("/")


class TestRulePath:
    def test_windows_drive_becomes_a_lower_case_folder(self):
        from pathlib import PureWindowsPath

        from app.main import rule_path

        assert rule_path(PureWindowsPath("C:/ws/workers/_shared")) == "//c/ws/workers/_shared"

    def test_posix_path_keeps_its_root(self):
        from pathlib import PurePosixPath

        from app.main import rule_path

        assert rule_path(PurePosixPath("/srv/ws/workers/_shared")) == "//srv/ws/workers/_shared"

    def test_the_shared_deny_rule_uses_that_form(self, client, workers_dir):
        create_worker(client, "researcher")

        deny = settings_of(argv_of(spawn(client, "researcher")))["permissions"]["deny"]

        shared = (workers_dir / "_shared").resolve()
        assert f"Edit({rule(shared)}/**)" in deny and f"Write({rule(shared)}/**)" in deny
        assert not any("//C:" in d or "//c:" in d for d in deny)


class TestGrantedDirectoriesAreAbsolute:
    def test_relative_configuration_still_grants_absolute_paths(
        self, tmp_path, monkeypatch, sessions_db, messages_log
    ):
        # Production runs with WORKERS_DIR=workers and PROJECTS_DIR=projects,
        # relative to the API's cwd. The spawned session's cwd is the worker's
        # folder, so a relative --add-dir pointed nowhere (seen live).
        monkeypatch.chdir(tmp_path)
        (tmp_path / "projects" / "p" / "artifacts").mkdir(parents=True)
        c = TestClient(make_app("workers", "worker_templates", sessions_db, messages_log, projects_dir="projects"))
        create_worker(c, "researcher")

        res = spawn(c, "researcher", write_to=["projects/p/artifacts"])

        assert res.status_code == 201, res.json()
        argv = SPAWNED[-1][0]
        dirs = add_dirs_of(argv)
        assert len(dirs) == 2
        for d in dirs:
            assert Path(d).is_absolute(), d
            assert Path(d).is_dir(), d
        assert dirs[0] == str((tmp_path / "workers" / "_shared").resolve())
        assert dirs[1] == str((tmp_path / "projects" / "p" / "artifacts").resolve())


class TestVariadicFlagsCannotSwallowThePrompt:
    def test_name_is_the_last_flag_and_prompt_is_last(self, client):
        create_worker(client, "researcher")

        argv = argv_of(spawn(client, "researcher", task="do it"))

        assert argv[-1].endswith("then: do it")
        assert argv[-3:-1] == ["--name", "researcher"]
        # Every variadic flag is followed by another flag before the prompt.
        for flag in ("--add-dir", "--tools"):
            i = argv.index(flag)
            rest = argv[i + 1 : -1]
            assert any(a.startswith("--") for a in rest), flag


class TestToolGrants:
    def test_default_is_the_base_set_only(self, client):
        create_worker(client, "researcher")

        argv = argv_of(spawn(client, "researcher"))

        assert argv[argv.index("--tools") + 1] == "Read,Glob,Grep,Edit,Write"
        allow = settings_of(argv)["permissions"]["allow"]
        assert "WebSearch" not in allow and "WebFetch" not in allow

    def test_web_tools_are_granted_on_request(self, client):
        create_worker(client, "news")

        argv = argv_of(spawn(client, "news", tools=["WebSearch", "WebFetch"]))

        assert argv[argv.index("--tools") + 1] == "Read,Glob,Grep,Edit,Write,WebSearch,WebFetch"
        allow = settings_of(argv)["permissions"]["allow"]
        assert "WebSearch" in allow and "WebFetch" in allow

    def test_ungrantable_tool_is_400_and_spawns_nothing(self, client):
        create_worker(client, "researcher")

        for tool in ("Bash", "SendMessage", "Task", "Edit"):
            res = spawn(client, "researcher", tools=[tool])
            assert res.status_code == 400, tool
            assert res.json()["detail"].startswith("bad_tool")
        assert SPAWNED == []


class TestDirectoryGrants:
    def test_read_from_adds_the_dir_read_only(self, client, workers_dir):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        (workers_dir / "writer" / "outputs").mkdir()

        argv = argv_of(spawn(client, "researcher", read_from=["workers/writer/outputs"]))

        granted = (workers_dir / "writer" / "outputs").resolve()
        assert str(granted) in add_dirs_of(argv)
        deny = settings_of(argv)["permissions"]["deny"]
        assert f"Edit({rule(granted)}/**)" in deny and f"Write({rule(granted)}/**)" in deny

    def test_write_to_adds_the_dir_writable(self, client, projects_dir):
        create_worker(client, "scriptwriter")
        (projects_dir / "first-reel" / "artifacts").mkdir(parents=True)

        argv = argv_of(spawn(client, "scriptwriter", write_to=["projects/first-reel/artifacts"]))

        granted = (projects_dir / "first-reel" / "artifacts").resolve()
        assert str(granted) in add_dirs_of(argv)
        deny = settings_of(argv)["permissions"]["deny"]
        assert not any(rule(granted) in d for d in deny)
        # _shared is still read-only regardless.
        assert any("_shared" in d and d.startswith("Write(") for d in deny)

    def test_shared_is_always_the_first_add_dir(self, client, workers_dir, projects_dir):
        create_worker(client, "researcher")
        (projects_dir / "p").mkdir(parents=True)

        argv = argv_of(spawn(client, "researcher", write_to=["projects/p"]))

        assert add_dirs_of(argv)[0] == str(workers_dir / "_shared")

    @pytest.mark.parametrize(
        "bad",
        [
            "data",                     # outside workers/ and projects/
            "../secret",                # traversal
            "workers/../data",          # traversal in the middle
            "workers/nope/outputs",     # does not exist
        ],
    )
    def test_bad_dir_is_400_and_spawns_nothing(self, client, bad):
        create_worker(client, "researcher")

        res = spawn(client, "researcher", read_from=[bad])

        assert res.status_code == 400, bad
        assert res.json()["detail"].startswith("bad_dir")
        assert SPAWNED == []

    def test_absolute_paths_are_refused(self, client, workers_dir):
        create_worker(client, "researcher")

        res = spawn(client, "researcher", write_to=[str(workers_dir / "researcher")])

        assert res.status_code == 400
        assert SPAWNED == []

    def test_grants_are_in_the_activity_log(self, client, workers_dir, projects_dir):
        create_worker(client, "researcher")
        (projects_dir / "p").mkdir(parents=True)

        spawn(client, "researcher", tools=["WebFetch"], write_to=["projects/p"])

        line = (workers_dir / "researcher" / "activity.jsonl").read_text(encoding="utf-8").splitlines()[0]
        event = json.loads(line)
        # Logged as the resolved directory the session was actually granted.
        assert event["tools"] == ["WebFetch"]
        assert event["write_to"] == [str((projects_dir / "p").resolve())]
        assert event["read_from"] == []
