"""Tests for the new MCP tools in mcp_server/workspace_server.py.

These tools are thin HTTP wrappers, so the tests fake `httpx.get/post/put`
rather than running the real FastAPI app: each test checks the tool calls
the right method/URL/body and propagates the API's response (or failure).
"""

import httpx
import pytest

from mcp_server import workspace_server as ws


class FakeResponse:
    def __init__(self, status_code: int, payload=None, content: bytes = b"body"):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.request = httpx.Request("GET", "http://test")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=self.request, response=self
            )


def test_list_worker_names_returns_only_names(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        return FakeResponse(
            200,
            [
                {"name": "time-teller", "instructions": "# time-teller\n...\n"},
                {"name": "nonsense-generator", "instructions": "# nonsense-generator\n...\n"},
            ],
        )

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    result = ws.list_worker_names()

    assert calls == [f"{ws.API_BASE_URL}/workers"]
    assert result == ["time-teller", "nonsense-generator"]


def test_list_worker_names_propagates_errors(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url: FakeResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        ws.list_worker_names()


def test_create_worker_is_a_single_post(monkeypatch):
    calls = []

    def fake_post(url, json):
        calls.append((url, json))
        return FakeResponse(201, {"name": "researcher", "instructions": json["instructions"]})

    def no_put(*args, **kwargs):
        raise AssertionError("create_worker must not follow up with a PUT")

    monkeypatch.setattr(ws.httpx, "post", fake_post)
    monkeypatch.setattr(ws.httpx, "put", no_put)

    result = ws.create_worker("researcher", "# researcher\n")

    assert calls == [(f"{ws.API_BASE_URL}/workers", {"name": "researcher", "instructions": "# researcher\n"})]
    assert result == {"name": "researcher", "instructions": "# researcher\n"}


def test_create_worker_raises_on_duplicate_name(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json: FakeResponse(409))

    with pytest.raises(httpx.HTTPStatusError):
        ws.create_worker("researcher", "# researcher\n")


def test_list_templates_returns_api_payload(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        return FakeResponse(200, [{"name": "basic", "description": "A basic worker."}])

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    result = ws.list_templates()

    assert calls == [f"{ws.API_BASE_URL}/templates"]
    assert result == [{"name": "basic", "description": "A basic worker."}]


def test_list_templates_propagates_errors(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url: FakeResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        ws.list_templates()


def test_list_templates_propagates_client_errors(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url: FakeResponse(400))

    with pytest.raises(httpx.HTTPStatusError):
        ws.list_templates()


def test_get_template_returns_content(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        return FakeResponse(200, {"content": "# basic\n"})

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    result = ws.get_template("basic")

    assert calls == [f"{ws.API_BASE_URL}/templates/basic"]
    assert result == {"content": "# basic\n"}


def test_get_template_raises_on_missing_template(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.get_template("does-not-exist")


def test_get_template_raises_on_invalid_name(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url: FakeResponse(400))

    with pytest.raises(httpx.HTTPStatusError):
        ws.get_template("Bad Name")


def test_update_claude_md_puts_instructions(monkeypatch):
    calls = []

    def fake_put(url, json):
        calls.append((url, json))
        return FakeResponse(200, {"name": "time-teller", "instructions": json["instructions"]})

    monkeypatch.setattr(ws.httpx, "put", fake_put)

    result = ws.update_claude_md("time-teller", "# time-teller\n")

    assert calls == [(f"{ws.API_BASE_URL}/workers/time-teller", {"instructions": "# time-teller\n"})]
    assert result == {"name": "time-teller", "instructions": "# time-teller\n"}


def test_update_claude_md_raises_on_missing_worker(monkeypatch):
    monkeypatch.setattr(ws.httpx, "put", lambda url, json: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.update_claude_md("does-not-exist", "# nope\n")


def test_update_claude_md_raises_on_invalid_name(monkeypatch):
    monkeypatch.setattr(ws.httpx, "put", lambda url, json: FakeResponse(400))

    with pytest.raises(httpx.HTTPStatusError):
        ws.update_claude_md("Bad Name", "# nope\n")


def test_write_skill_posts_skill_body(monkeypatch):
    calls = []

    def fake_post(url, json):
        calls.append((url, json))
        return FakeResponse(201, {"ok": True})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.write_skill("time-teller", "tz-lookup", "# tz-lookup\n")

    assert calls == [
        (
            f"{ws.API_BASE_URL}/workers/time-teller/skills",
            {"skill_name": "tz-lookup", "content": "# tz-lookup\n"},
        )
    ]
    assert result == {"ok": True}


def test_write_skill_raises_on_missing_worker(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.write_skill("does-not-exist", "tz-lookup", "# tz-lookup\n")


def test_write_skill_raises_on_invalid_name(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json: FakeResponse(400))

    with pytest.raises(httpx.HTTPStatusError):
        ws.write_skill("time-teller", "Bad Skill", "# nope\n")


def test_write_skill_handles_empty_response_body(monkeypatch):
    monkeypatch.setattr(
        ws.httpx, "post", lambda url, json: FakeResponse(201, content=b"")
    )

    result = ws.write_skill("time-teller", "tz-lookup", "# tz-lookup\n")

    assert result == {"status_code": 201}


def test_delete_worker_calls_delete_endpoint(monkeypatch):
    calls = []

    def fake_delete(url):
        calls.append(url)
        return FakeResponse(204, content=b"")

    monkeypatch.setattr(ws.httpx, "delete", fake_delete)

    result = ws.delete_worker("time-teller")

    assert calls == [f"{ws.API_BASE_URL}/workers/time-teller"]
    assert result == {"deleted": "time-teller"}


def test_delete_worker_raises_on_missing_worker(monkeypatch):
    monkeypatch.setattr(ws.httpx, "delete", lambda url: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.delete_worker("does-not-exist")


def test_delete_worker_raises_on_invalid_name(monkeypatch):
    monkeypatch.setattr(ws.httpx, "delete", lambda url: FakeResponse(400))

    with pytest.raises(httpx.HTTPStatusError):
        ws.delete_worker("Bad Name")


def test_spawn_session_posts_worker_and_task_with_token(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_TOKEN", "tok-1")

    def fake_post(url, json, headers):
        calls.append((url, json, headers))
        return FakeResponse(201, {"session_id": "sess-1", "worker": "researcher", "status": "live"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.spawn_session("researcher", "find today's news")

    assert calls == [
        (
            f"{ws.API_BASE_URL}/sessions",
            {"worker": "researcher", "task": "find today's news"},
            {"X-Session-Token": "tok-1"},
        )
    ]
    assert result == {"session_id": "sess-1", "worker": "researcher", "status": "live"}


def test_spawn_session_raises_on_unknown_worker(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json, headers: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.spawn_session("does-not-exist", "task")


def test_list_sessions_gets_with_token_only(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_TOKEN", "tok-1")

    def fake_get(url, headers):
        calls.append((url, headers))
        return FakeResponse(200, [{"session_id": "caller-1"}])

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    result = ws.list_sessions()

    assert calls == [(f"{ws.API_BASE_URL}/sessions", {"X-Session-Token": "tok-1"})]
    assert result == [{"session_id": "caller-1"}]


def test_list_sessions_raises_on_bad_token(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url, headers: FakeResponse(401))

    with pytest.raises(httpx.HTTPStatusError):
        ws.list_sessions()


def test_send_to_session_posts_text_with_token(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_TOKEN", "tok-1")

    def fake_post(url, json, headers):
        calls.append((url, json, headers))
        return FakeResponse(202, {"accepted": True})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.send_to_session("sess-2", "hi")

    assert calls == [
        (f"{ws.API_BASE_URL}/sessions/sess-2/messages", {"text": "hi"}, {"X-Session-Token": "tok-1"})
    ]
    assert result == {"accepted": True}


def test_report_result_posts_as_me_with_token(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_TOKEN", "tok-1")

    def fake_post(url, json, headers):
        calls.append((url, json, headers))
        return FakeResponse(200, {"run_id": "researcher-x", "status": "success"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.report_result("success", summary="done", tags=["scope:research"], metrics={"turns": 3})

    assert calls == [
        (
            f"{ws.API_BASE_URL}/sessions/me/result",
            {
                "status": "success",
                "summary": "done",
                "tags": ["scope:research"],
                "metrics": {"turns": 3},
                "error": None,
            },
            {"X-Session-Token": "tok-1"},
        )
    ]
    assert result == {"run_id": "researcher-x", "status": "success"}


def test_report_result_raises_on_bad_status(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json, headers: FakeResponse(400))

    with pytest.raises(httpx.HTTPStatusError):
        ws.report_result("done")


def test_end_session_posts_to_end_endpoint(monkeypatch):
    calls = []

    def fake_post(url, headers=None):
        calls.append((url, headers))
        return FakeResponse(200, {"session_id": "sess-2", "status": "ended"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)
    monkeypatch.setattr(ws, "SESSION_TOKEN", "")

    result = ws.end_session("sess-2")

    # No token = the host is calling; the header is left out entirely.
    assert calls == [(f"{ws.API_BASE_URL}/sessions/sess-2/end", {})]
    assert result == {"session_id": "sess-2", "status": "ended"}


def test_end_session_raises_on_unknown_session(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, headers=None: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.end_session("does-not-exist")


# --- dispatching -----------------------------------------------------------------


def test_assign_task_posts_to_the_project_with_token(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_TOKEN", "tok-1")

    def fake_post(url, json, headers):
        calls.append((url, json, headers))
        return FakeResponse(201, {"session_id": "s1", "run_id": "scriptwriter-x"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.assign_task("first-reel", "scriptwriter", "write it", tools=["WebFetch"])

    assert calls == [(
        f"{ws.API_BASE_URL}/projects/first-reel/tasks",
        {"worker": "scriptwriter", "task": "write it", "tools": ["WebFetch"], "read_from": []},
        {"X-Session-Token": "tok-1"},
    )]
    assert result["run_id"] == "scriptwriter-x"


def test_render_project_posts_with_a_long_timeout(monkeypatch):
    calls = []

    def fake_post(url, headers, timeout):
        calls.append((url, headers, timeout))
        return FakeResponse(200, {"slug": "first-reel", "status": "published"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.render_project("first-reel")

    assert calls == [(f"{ws.API_BASE_URL}/projects/first-reel/render", {}, 900)]
    assert result["status"] == "published"


def test_wait_for_run_long_polls(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse(200, {"run_id": "scriptwriter-x", "status": "success"})

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    result = ws.wait_for_run("scriptwriter-x", timeout_s=120)

    assert calls == [(f"{ws.API_BASE_URL}/runs/scriptwriter-x", {"wait": 120}, 150)]
    assert result["status"] == "success"


def test_get_run_and_list_runs(monkeypatch):
    calls = []

    def fake_get(url, params=None):
        calls.append((url, params))
        return FakeResponse(200, [] if url.endswith("/runs") else {"run_id": "x"})

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    assert ws.get_run("x") == {"run_id": "x"}
    assert ws.list_runs(worker="scriptwriter", tag="project:first-reel") == []
    assert calls == [
        (f"{ws.API_BASE_URL}/runs/x", None),
        (f"{ws.API_BASE_URL}/runs", {"worker": "scriptwriter", "tag": "project:first-reel"}),
    ]


# --- studio projects -----------------------------------------------------------


def test_create_project_posts_all_fields(monkeypatch):
    calls = []

    def fake_post(url, json):
        calls.append((url, json))
        return FakeResponse(201, {"slug": "first-reel", "status": "created"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.create_project("first-reel", "First reel", "social-short")

    assert calls == [(
        f"{ws.API_BASE_URL}/projects",
        {"slug": "first-reel", "title": "First reel", "format": "social-short", "renderer": "ffmpeg", "mode": "guided"},
    )]
    assert result == {"slug": "first-reel", "status": "created"}


def test_create_project_raises_on_duplicate(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json: FakeResponse(409))

    with pytest.raises(httpx.HTTPStatusError):
        ws.create_project("first-reel", "x", "social-short")


def test_list_and_get_project(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        return FakeResponse(200, {"slug": "first-reel"} if url.endswith("/first-reel") else [{"slug": "first-reel"}])

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    assert ws.list_projects() == [{"slug": "first-reel"}]
    assert ws.get_project("first-reel") == {"slug": "first-reel"}
    assert calls == [f"{ws.API_BASE_URL}/projects", f"{ws.API_BASE_URL}/projects/first-reel"]


def test_start_pipeline_posts(monkeypatch):
    calls = []

    def fake_post(url):
        calls.append(url)
        return FakeResponse(200, {"status": "running", "stage": "script"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    assert ws.start_pipeline("first-reel") == {"status": "running", "stage": "script"}
    assert calls == [f"{ws.API_BASE_URL}/projects/first-reel/start"]


def test_decide_posts_with_token_and_producer_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_TOKEN", "tok-1")

    def fake_post(url, json, headers):
        calls.append((url, json, headers))
        return FakeResponse(200, {"status": "running"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    ws.decide("first-reel", "revise", "make the hook a question")

    assert calls == [(
        f"{ws.API_BASE_URL}/projects/first-reel/decision",
        {"decision": "revise", "notes": "make the hook a question", "by": "producer"},
        {"X-Session-Token": "tok-1"},
    )]


def test_decide_raises_when_nothing_to_decide(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json, headers: FakeResponse(409))

    with pytest.raises(httpx.HTTPStatusError):
        ws.decide("first-reel", "approve")


def test_export_project_posts_dest(monkeypatch):
    calls = []

    def fake_post(url, json):
        calls.append((url, json))
        return FakeResponse(200, {"exported_to": "C:/Videos/first-reel"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    assert ws.export_project("first-reel", "C:/Videos") == {"exported_to": "C:/Videos/first-reel"}
    assert calls == [(f"{ws.API_BASE_URL}/projects/first-reel/export", {"dest_dir": "C:/Videos"})]


def test_delete_project_refuses_without_confirm(monkeypatch):
    def no_delete(*args, **kwargs):
        raise AssertionError("must not call the API without confirm")

    monkeypatch.setattr(ws.httpx, "delete", no_delete)

    with pytest.raises(ValueError, match="confirm=True"):
        ws.delete_project("first-reel")


def test_delete_project_with_confirm(monkeypatch):
    calls = []

    def fake_delete(url):
        calls.append(url)
        return FakeResponse(204, content=b"")

    monkeypatch.setattr(ws.httpx, "delete", fake_delete)

    assert ws.delete_project("first-reel", confirm=True) == {"deleted": "first-reel"}
    assert calls == [f"{ws.API_BASE_URL}/projects/first-reel"]


def test_send_to_session_raises_on_unknown_session(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json, headers: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.send_to_session("does-not-exist", "hi")


def test_send_to_session_raises_when_not_allowed(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json, headers: FakeResponse(403))

    with pytest.raises(httpx.HTTPStatusError):
        ws.send_to_session("sess-2", "hi")


def test_send_to_session_raises_on_bad_token(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json, headers: FakeResponse(401))

    with pytest.raises(httpx.HTTPStatusError):
        ws.send_to_session("sess-2", "hi")


# --- toolkits ---------------------------------------------------------------------


def test_get_catalog_and_toolkit_are_plain_gets(monkeypatch):
    calls = []
    monkeypatch.setattr(ws.httpx, "get", lambda url, **kw: calls.append(url) or FakeResponse(200, {"tools": []}))

    assert ws.get_catalog() == {"tools": []}
    assert ws.get_toolkit("researcher") == {"tools": []}
    assert calls == [f"{ws.API_BASE_URL}/catalog", f"{ws.API_BASE_URL}/workers/researcher/toolkit"]


def test_set_toolkit_puts_every_list_defaulting_to_empty(monkeypatch):
    calls = []

    def fake_put(url, json):
        calls.append((url, json))
        return FakeResponse(200, {"tools": ["WebFetch"], "mcp_servers": [], "read_from": [], "skills": ["social-short"]})

    monkeypatch.setattr(ws.httpx, "put", fake_put)

    result = ws.set_toolkit("researcher", tools=["WebFetch"], skills=["social-short"])

    assert calls == [(f"{ws.API_BASE_URL}/workers/researcher/toolkit",
                      {"tools": ["WebFetch"], "mcp_servers": [], "read_from": [], "skills": ["social-short"]})]
    assert result["skills"] == ["social-short"]


def test_set_toolkit_raises_on_a_name_outside_the_catalog(monkeypatch):
    monkeypatch.setattr(ws.httpx, "put", lambda url, json: FakeResponse(400))

    with pytest.raises(httpx.HTTPStatusError):
        ws.set_toolkit("researcher", tools=["Bash"])


def test_remove_skill_deletes_and_returns_the_toolkit(monkeypatch):
    calls = []
    monkeypatch.setattr(ws.httpx, "delete", lambda url: calls.append(url) or FakeResponse(200, {"skills": []}))

    assert ws.remove_skill("researcher", "social-short") == {"skills": []}
    assert calls == [f"{ws.API_BASE_URL}/workers/researcher/toolkit/skills/social-short"]
