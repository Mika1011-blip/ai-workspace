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


def test_list_agent_names_returns_only_names(monkeypatch):
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

    result = ws.list_agent_names()

    assert calls == [f"{ws.API_BASE_URL}/agents"]
    assert result == ["time-teller", "nonsense-generator"]


def test_list_agent_names_propagates_errors(monkeypatch):
    monkeypatch.setattr(ws.httpx, "get", lambda url: FakeResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        ws.list_agent_names()


def test_list_templates_returns_api_payload(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        return FakeResponse(200, [{"name": "basic", "description": "A basic agent."}])

    monkeypatch.setattr(ws.httpx, "get", fake_get)

    result = ws.list_templates()

    assert calls == [f"{ws.API_BASE_URL}/templates"]
    assert result == [{"name": "basic", "description": "A basic agent."}]


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

    assert calls == [(f"{ws.API_BASE_URL}/agents/time-teller", {"instructions": "# time-teller\n"})]
    assert result == {"name": "time-teller", "instructions": "# time-teller\n"}


def test_update_claude_md_raises_on_missing_agent(monkeypatch):
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
            f"{ws.API_BASE_URL}/agents/time-teller/skills",
            {"skill_name": "tz-lookup", "content": "# tz-lookup\n"},
        )
    ]
    assert result == {"ok": True}


def test_write_skill_raises_on_missing_agent(monkeypatch):
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
