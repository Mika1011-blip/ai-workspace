"""The 3D floor page (docs/3d-factory.md). The scene only draws
/workers/state, whose contract is tested in tests/test_sdk_wiring.py."""

from tests.test_sessions import (  # noqa: F401 -- fixtures shared with the session tests
    SPAWNED,
    STOPPED,
    _reset_fakes,
    client,
    messages_log,
    sessions_db,
    templates_dir,
    workers_dir,
)


def test_factory_page_is_served(client):
    res = client.get("/factory")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "Factory floor" in res.text
    # Plain Three.js from a pinned CDN build, and the list fallback.
    assert "three@0." in res.text and "list-view" in res.text


def test_state_is_one_entry_per_worker_with_valid_statuses(client, workers_dir):
    client.post("/workers", json={"name": "researcher"})
    client.post("/workers", json={"name": "writer"})

    entries = client.get("/workers/state").json()

    assert [e["id"] for e in entries] == ["researcher", "writer"]
    assert all(e["status"] in {"idle", "thinking", "using_tool", "waiting", "error"} for e in entries)
    assert all(e["simulated"] is False for e in entries)
    assert all({"current_task", "tool", "context_used", "updated_at"} <= set(e) for e in entries)
