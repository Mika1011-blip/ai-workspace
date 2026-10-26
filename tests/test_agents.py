import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def agents_dir(tmp_path):
    return tmp_path / "agents"


@pytest.fixture
def client(agents_dir):
    return TestClient(create_app(agents_dir))


def test_list_is_empty_at_first(client):
    res = client.get("/agents")

    assert res.status_code == 200
    assert res.json() == []


def test_create_agent_writes_claude_md(client, agents_dir):
    res = client.post("/agents", json={"name": "researcher"})

    assert res.status_code == 201
    claude_md = agents_dir / "researcher" / "CLAUDE.md"
    assert claude_md.is_file()
    assert claude_md.read_text(encoding="utf-8").startswith("# researcher\n")
    assert res.json() == {"name": "researcher", "instructions": claude_md.read_text(encoding="utf-8")}


def test_list_includes_created_agents(client):
    client.post("/agents", json={"name": "writer"})
    client.post("/agents", json={"name": "researcher"})

    res = client.get("/agents")

    assert res.status_code == 200
    agents = res.json()
    assert [a["name"] for a in agents] == ["researcher", "writer"]
    assert agents[0]["instructions"].startswith("# researcher\n")


def test_duplicate_name_is_refused(client, agents_dir):
    client.post("/agents", json={"name": "researcher"})
    claude_md = agents_dir / "researcher" / "CLAUDE.md"
    claude_md.write_text("# researcher\n\nMy edits.\n", encoding="utf-8")

    res = client.post("/agents", json={"name": "researcher"})

    assert res.status_code == 409
    assert claude_md.read_text(encoding="utf-8") == "# researcher\n\nMy edits.\n"


@pytest.mark.parametrize(
    "name",
    ["../secret", "Bad Name", "UPPER", "", "a" * 65, "-leading", "double--dash", "under_score"],
)
def test_bad_name_is_refused(client, agents_dir, name):
    res = client.post("/agents", json={"name": name})

    assert res.status_code == 422
    assert list(agents_dir.iterdir()) == []
    assert not (agents_dir.parent / "secret").exists()
