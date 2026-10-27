"""Catalog and per-worker toolkits: what may be attached, what is attached,
and that every spawn applies it."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_grants import add_dirs_of, settings_of
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
def catalog_file(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "mcp_servers": {
            "docs": {"description": "Library docs lookup", "command": "npx", "args": ["-y", "docs-mcp"], "env": {}},
        }
    }), encoding="utf-8")
    return path


@pytest.fixture
def skills_catalog(templates_dir):
    skills = templates_dir / "skills"
    skills.mkdir(parents=True)
    (skills / "social-short.md").write_text(
        "---\nname: social-short\ndescription: Rules of a vertical short.\n---\n\n# social-short\nBody.\n", encoding="utf-8"
    )
    return skills


@pytest.fixture
def client(workers_dir, templates_dir, sessions_db, messages_log, catalog_file, skills_catalog, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # read_from grants are repo-relative
    return TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, catalog_file=catalog_file))


class TestCatalog:
    def test_lists_builtin_tools_vetted_servers_and_skills(self, client):
        res = client.get("/catalog")

        assert res.status_code == 200
        cat = res.json()
        assert [t["name"] for t in cat["tools"]] == ["WebFetch", "WebSearch"]
        assert cat["mcp_servers"] == [{"name": "docs", "description": "Library docs lookup"}]
        assert cat["skills"] == [{"name": "social-short", "description": "Rules of a vertical short."}]

    def test_missing_catalog_file_means_no_servers(self, workers_dir, templates_dir, sessions_db, messages_log, tmp_path):
        c = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, catalog_file=tmp_path / "none.json"))

        cat = c.get("/catalog").json()

        assert cat["mcp_servers"] == [] and len(cat["tools"]) == 2


class TestToolkitEndpoints:
    def test_empty_by_default(self, client):
        create_worker(client, "researcher")

        assert client.get("/workers/researcher/toolkit").json() == {"tools": [], "mcp_servers": [], "read_from": [], "skills": []}

    def test_put_stores_the_toolkit_and_installs_skills(self, client, workers_dir):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        (workers_dir / "writer" / "outputs").mkdir()

        res = client.put("/workers/researcher/toolkit", json={
            "tools": ["WebFetch", "WebFetch"], "mcp_servers": ["docs"], "read_from": ["workers/writer/outputs"], "skills": ["social-short"],
        })

        assert res.status_code == 200, res.json()
        assert res.json() == {"tools": ["WebFetch"], "mcp_servers": ["docs"], "read_from": ["workers/writer/outputs"], "skills": ["social-short"]}
        stored = json.loads((workers_dir / "researcher" / "toolkit.json").read_text(encoding="utf-8"))
        assert stored == {"tools": ["WebFetch"], "mcp_servers": ["docs"], "read_from": ["workers/writer/outputs"]}
        skill = workers_dir / "researcher" / ".claude" / "skills" / "social-short" / "SKILL.md"
        assert skill.is_file() and "Rules of a vertical short" in skill.read_text(encoding="utf-8")
        assert client.get("/workers/researcher/toolkit").json() == res.json()
        events = [json.loads(l)["event"] for l in (workers_dir / "researcher" / "activity.jsonl").read_text().splitlines()]
        assert "toolkit_set" in events

    def test_names_outside_the_catalog_are_400(self, client):
        create_worker(client, "researcher")

        for body, word in [
            ({"tools": ["Bash"]}, "bad_tool"),
            ({"mcp_servers": ["github"]}, "bad_mcp_server"),
            ({"skills": ["nope"]}, "bad_skill"),
            ({"read_from": ["../secret"]}, "bad_dir"),
            ({"read_from": ["workers/ghost"]}, "bad_dir"),
        ]:
            res = client.put("/workers/researcher/toolkit", json=body)
            assert res.status_code == 400, body
            assert res.json()["detail"].startswith(word), (body, res.json())
        assert client.get("/workers/researcher/toolkit").json()["tools"] == []

    def test_unknown_and_invalid_worker(self, client):
        assert client.get("/workers/nope/toolkit").status_code == 404
        assert client.put("/workers/nope/toolkit", json={}).status_code == 404
        assert client.get("/workers/Bad%20Name/toolkit").status_code == 400

    def test_remove_skill_uninstalls_it_and_leaves_hand_written_ones(self, client, workers_dir):
        create_worker(client, "researcher")
        client.put("/workers/researcher/toolkit", json={"skills": ["social-short"]})
        client.post("/workers/researcher/skills", json={"skill_name": "house-style", "content": "# mine"})
        assert client.get("/workers/researcher/toolkit").json()["skills"] == ["house-style", "social-short"]

        res = client.delete("/workers/researcher/toolkit/skills/social-short")

        assert res.status_code == 200
        assert res.json()["skills"] == ["house-style"]
        assert not (workers_dir / "researcher" / ".claude" / "skills" / "social-short").exists()
        assert client.delete("/workers/researcher/toolkit/skills/social-short").status_code == 404
        assert client.delete("/workers/researcher/toolkit/skills/Bad%20Name").status_code == 400


class TestToolkitAppliesOnSpawn:
    def test_tools_servers_and_folders_are_merged_into_the_spawn(self, client, workers_dir):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        (workers_dir / "writer" / "outputs").mkdir()
        client.put("/workers/researcher/toolkit", json={"tools": ["WebFetch"], "mcp_servers": ["docs"], "read_from": ["workers/writer/outputs"]})

        res = spawn(client, "researcher", tools=["WebSearch"])

        assert res.status_code == 201, res.json()
        argv = SPAWNED[-1][0]
        assert argv[argv.index("--tools") + 1] == "Read,Glob,Grep,Edit,Write,WebSearch,WebFetch"
        assert str((workers_dir / "writer" / "outputs").resolve()) in add_dirs_of(argv)
        settings = settings_of(argv)
        assert "mcp__docs__*" in settings["permissions"]["allow"] and "mcp__ai-workspace__*" in settings["permissions"]["allow"]
        mcp = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
        assert mcp["docs"] == {"command": "npx", "args": ["-y", "docs-mcp"], "env": {}}
        assert "ai-workspace" in mcp and "description" not in mcp["docs"]
        spawned = json.loads((workers_dir / "researcher" / "activity.jsonl").read_text().splitlines()[-1])
        assert spawned["event"] == "spawned" and spawned["mcp_servers"] == ["docs"] and spawned["tools"] == ["WebSearch", "WebFetch"]

    def test_a_toolkit_naming_a_server_no_longer_in_the_catalog_blocks_the_spawn(self, client, workers_dir, catalog_file):
        create_worker(client, "researcher")
        client.put("/workers/researcher/toolkit", json={"mcp_servers": ["docs"]})
        catalog_file.write_text(json.dumps({"mcp_servers": {}}), encoding="utf-8")  # the host un-vetted it

        res = spawn(client, "researcher")

        assert res.status_code == 409
        assert res.json()["detail"].startswith("toolkit_not_in_catalog")
        assert SPAWNED == []

    def test_sdk_options_carry_the_extra_server(self, tmp_path):
        from app.main import sdk_options
        from app.runner import SpawnSpec

        spec = SpawnSpec("r", "t", "tok", tmp_path / "r", tmp_path / "_shared", "http://api", ("WebFetch",), (), (),
                         {"docs": {"command": "npx", "args": []}})

        options, _ = sdk_options(spec, "11111111-2222-3333-4444-555555555555")

        assert options.mcp_servers["docs"] == {"command": "npx", "args": []}
        assert "mcp__docs__*" in json.loads(options.settings)["permissions"]["allow"]
