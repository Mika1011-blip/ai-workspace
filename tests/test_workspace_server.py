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


def test_spawn_session_posts_worker_and_task(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_ID", "caller-1")

    def fake_post(url, json):
        calls.append((url, json))
        return FakeResponse(201, {"session_id": "sess-1", "worker": "researcher", "status": "live"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.spawn_session("researcher", "find today's news")

    assert calls == [
        (
            f"{ws.API_BASE_URL}/sessions",
            {"worker": "researcher", "task": "find today's news", "spawned_by": "caller-1"},
        )
    ]
    assert result == {"session_id": "sess-1", "worker": "researcher", "status": "live"}


def test_spawn_session_raises_on_unknown_worker(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url, json: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.spawn_session("does-not-exist", "task")


def test_list_sessions_gets_with_caller_and_token(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_ID", "caller-1")
    monkeypatch.setattr(ws, "SESSION_TOKEN", "tok-1")

    def fake_get(url, params, headers):
        calls.append((url, params, headers))
        return FakeResponse(200, [{"session_id": "caller-1"}])

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    result = ws.list_sessions()

    assert calls == [
        (f"{ws.API_BASE_URL}/sessions", {"caller": "caller-1"}, {"X-Session-Token": "tok-1"})
    ]
    assert result == [{"session_id": "caller-1"}]


def test_list_sessions_raises_on_unknown_caller(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url, params, headers: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.list_sessions()


def test_list_sessions_raises_on_bad_token(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url, params, headers: FakeResponse(401))

    with pytest.raises(httpx.HTTPStatusError):
        ws.list_sessions()


def test_send_to_session_posts_message_with_token(monkeypatch):
    calls = []
    monkeypatch.setattr(ws, "SESSION_ID", "caller-1")
    monkeypatch.setattr(ws, "SESSION_TOKEN", "tok-1")

    def fake_post(url, json, headers):
        calls.append((url, json, headers))
        return FakeResponse(202, {"accepted": True})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.send_to_session("sess-2", "hi")

    assert calls == [
        (
            f"{ws.API_BASE_URL}/sessions/sess-2/messages",
            {"from": "caller-1", "text": "hi"},
            {"X-Session-Token": "tok-1"},
        )
    ]
    assert result == {"accepted": True}


def test_end_session_posts_to_end_endpoint(monkeypatch):
    calls = []

    def fake_post(url):
        calls.append(url)
        return FakeResponse(200, {"session_id": "sess-2", "status": "ended"})

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.end_session("sess-2")

    assert calls == [f"{ws.API_BASE_URL}/sessions/sess-2/end"]
    assert result == {"session_id": "sess-2", "status": "ended"}


def test_end_session_raises_on_unknown_session(monkeypatch):
    monkeypatch.setattr(ws.httpx, "post", lambda url: FakeResponse(404))

    with pytest.raises(httpx.HTTPStatusError):
        ws.end_session("does-not-exist")


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
