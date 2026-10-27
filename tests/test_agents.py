import pytest
from fastapi.testclient import TestClient

from app.main import create_app

# Names that must always be refused by NAME_PATTERN (^[a-z0-9-]{1,40}$),
# regardless of which endpoint receives them (see .claude/rules/api.md). Safe
# to put in a JSON body. Note: "-leading" and "double--dash" are NOT in this
# list anymore -- under the new pattern they're valid names (see the
# dedicated acceptance tests below).
BODY_INVALID_NAMES = [
    "../secret",       # parent-directory traversal
    "..",               # bare parent-directory segment
    ".",                # bare current-directory segment
    "Bad Name",         # space, mixed case
    "UPPER",            # uppercase
    "",                 # empty string
    "a" * 41,           # over the 40-char limit
    "under_score",      # underscore not allowed
    "name\x00byte",      # embedded null byte
]

# Same list, minus the values that can't be used to test app-level validation
# when placed in a URL path:
# - "." and ".." are normalized away by the HTTP client itself before the
#   request is even sent (RFC 3986);
# - "../secret" as a single path segment normalizes the same way (to
#   "/secret"), landing on an unrelated, unmatched route -- it never reaches
#   NAME_PATTERN validation, so it's exercised as a body value only;
# - "" as a path segment collapses the URL to "/agents" and 307-redirects to
#   the list endpoint, never reaching {name} validation either;
# - a null byte can't be represented in a URL path at all.
# Those all get their own dedicated tests below instead of a generic
# status-code assertion.
PATH_INVALID_NAMES = [
    n for n in BODY_INVALID_NAMES if n not in (".", "..", "../secret", "", "name\x00byte")
]

# Names that match NAME_PATTERN but used to be rejected under the old,
# stricter pattern -- now valid, and must be accepted end-to-end.
NEWLY_VALID_NAMES = ["-leading", "double--dash"]


@pytest.fixture
def agents_dir(tmp_path):
    return tmp_path / "agents"


@pytest.fixture
def client(agents_dir):
    return TestClient(create_app(agents_dir))


def create(client, name):
    return client.post("/agents", json={"name": name})


class TestRootPage:
    def test_serves_the_web_ui(self, client):
        res = client.get("/")

        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Agents" in res.text


class TestListAgents:
    def test_empty_at_first(self, client):
        res = client.get("/agents")

        assert res.status_code == 200
        assert res.json() == []

    def test_includes_created_agents_sorted_by_name(self, client):
        create(client, "writer")
        create(client, "researcher")

        res = client.get("/agents")

        assert res.status_code == 200
        agents = res.json()
        assert [a["name"] for a in agents] == ["researcher", "writer"]
        assert agents[0]["instructions"].startswith("# researcher\n")

    def test_ignores_folders_without_claude_md(self, client, agents_dir):
        create(client, "researcher")
        stray = agents_dir / "not-an-agent"
        stray.mkdir()
        (stray / "notes.txt").write_text("not a CLAUDE.md", encoding="utf-8")

        res = client.get("/agents")

        assert res.status_code == 200
        assert [a["name"] for a in res.json()] == ["researcher"]


class TestCreateAgent:
    def test_writes_claude_md_and_returns_it(self, client, agents_dir):
        res = create(client, "researcher")

        assert res.status_code == 201
        claude_md = agents_dir / "researcher" / "CLAUDE.md"
        assert claude_md.is_file()
        assert claude_md.read_text(encoding="utf-8").startswith("# researcher\n")
        assert res.json() == {"name": "researcher", "instructions": claude_md.read_text(encoding="utf-8")}

    def test_single_char_name_is_accepted(self, client, agents_dir):
        res = create(client, "a")

        assert res.status_code == 201
        assert (agents_dir / "a" / "CLAUDE.md").is_file()

    def test_name_at_max_length_is_accepted(self, client, agents_dir):
        name = "a" * 40

        res = create(client, name)

        assert res.status_code == 201
        assert (agents_dir / name / "CLAUDE.md").is_file()

    def test_name_over_max_length_is_refused(self, client, agents_dir):
        name = "a" * 41

        res = create(client, name)

        assert res.status_code == 400
        assert list(agents_dir.iterdir()) == []

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, agents_dir, name):
        res = create(client, name)

        assert res.status_code == 201
        assert (agents_dir / name / "CLAUDE.md").is_file()

    def test_duplicate_name_is_refused_and_does_not_overwrite(self, client, agents_dir):
        create(client, "researcher")
        claude_md = agents_dir / "researcher" / "CLAUDE.md"
        claude_md.write_text("# researcher\n\nMy edits.\n", encoding="utf-8")

        res = create(client, "researcher")

        assert res.status_code == 409
        assert claude_md.read_text(encoding="utf-8") == "# researcher\n\nMy edits.\n"

    def test_missing_name_field_is_refused(self, client):
        res = client.post("/agents", json={})

        assert res.status_code == 422

    def test_non_string_name_is_refused(self, client):
        res = client.post("/agents", json={"name": 123})

        assert res.status_code == 422

    @pytest.mark.parametrize("name", BODY_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, agents_dir, name):
        res = create(client, name)

        assert res.status_code == 400
        assert list(agents_dir.iterdir()) == []
        assert not (agents_dir.parent / "secret").exists()


class TestGetAgent:
    def test_returns_current_claude_md_content(self, client, agents_dir):
        create(client, "researcher")
        claude_md = agents_dir / "researcher" / "CLAUDE.md"
        claude_md.write_text("# researcher\n\nMy edits.\n", encoding="utf-8")

        res = client.get("/agents/researcher")

        assert res.status_code == 200
        assert res.json() == {"name": "researcher", "instructions": "# researcher\n\nMy edits.\n"}

    def test_reads_live_from_disk_not_a_cache(self, client, agents_dir):
        create(client, "researcher")
        client.get("/agents/researcher")
        (agents_dir / "researcher" / "CLAUDE.md").write_text("# researcher\n\nUpdated.\n", encoding="utf-8")

        res = client.get("/agents/researcher")

        assert res.json()["instructions"] == "# researcher\n\nUpdated.\n"

    def test_missing_agent_is_404(self, client):
        res = client.get("/agents/nope")

        assert res.status_code == 404

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, name):
        create(client, name)

        res = client.get(f"/agents/{name}")

        assert res.status_code == 200
        assert res.json()["name"] == name

    def test_path_with_extra_segments_is_not_found(self, client, agents_dir):
        # A "/" can never reach NAME_PATTERN validation: Starlette's router only
        # matches a single path segment against {name}, so this 404s before the
        # app ever sees the value — nothing outside agents/ is ever touched.
        create(client, "researcher")

        res = client.get("/agents/researcher/../../secret")

        assert res.status_code in (404, 422)
        assert not (agents_dir.parent.parent / "secret").exists()

    def test_dot_dot_segment_never_reaches_the_app(self, client, agents_dir):
        # "/agents/.." is normalized by the HTTP client to "/" (RFC 3986) before
        # the request is sent, so it never arrives as agent name "..". It lands
        # on an unrelated route; either way nothing agent-specific is returned
        # and nothing outside agents/ is touched.
        res = client.get("/agents/..", follow_redirects=False)

        assert "application/json" not in res.headers.get("content-type", "")
        assert not (agents_dir.parent / "secret").exists()

    def test_dot_segment_never_reaches_the_app(self, client, agents_dir):
        # "/agents/." normalizes to "/agents" (the list endpoint), not agent
        # name ".". Confirms it can't be (mis)read as a single-dot agent name.
        res = client.get("/agents/.", follow_redirects=False)

        assert res.status_code in (200, 307)
        if res.status_code == 200:
            assert res.json() == []  # the list endpoint, not a "." agent

    def test_null_byte_in_path_is_refused(self, client):
        # Sent URL-encoded (%00) so it actually reaches the app as a path
        # param, rather than tripping the HTTP client's own URL validation.
        res = client.get("/agents/name%00byte")

        assert res.status_code in (400, 404)

    @pytest.mark.parametrize("name", PATH_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, name):
        res = client.get(f"/agents/{name}")

        assert res.status_code == 400


class TestDeleteAgent:
    def test_removes_folder(self, client, agents_dir):
        create(client, "researcher")

        res = client.delete("/agents/researcher")

        assert res.status_code == 204
        assert not (agents_dir / "researcher").exists()

    def test_removes_from_list(self, client):
        create(client, "writer")
        create(client, "researcher")

        client.delete("/agents/writer")
        res = client.get("/agents")

        assert res.status_code == 200
        assert [a["name"] for a in res.json()] == ["researcher"]

    def test_second_delete_of_same_agent_is_404(self, client):
        create(client, "researcher")
        client.delete("/agents/researcher")

        res = client.delete("/agents/researcher")

        assert res.status_code == 404

    def test_missing_agent_is_404(self, client, agents_dir):
        res = client.delete("/agents/nope")

        assert res.status_code == 404
        assert not (agents_dir / "nope").exists()

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, agents_dir, name):
        create(client, name)

        res = client.delete(f"/agents/{name}")

        assert res.status_code == 204
        assert not (agents_dir / name).exists()

    def test_only_deletes_the_named_agent(self, client, agents_dir):
        create(client, "writer")
        create(client, "researcher")

        client.delete("/agents/writer")

        assert not (agents_dir / "writer").exists()
        assert (agents_dir / "researcher").exists()

    def test_dot_dot_segment_never_reaches_the_app(self, client, agents_dir):
        # Normalized to "/" by the HTTP client before sending; DELETE has no
        # handler there, so this is 405 — confirming it never deletes anything.
        create(client, "researcher")

        res = client.delete("/agents/..", follow_redirects=False)

        assert res.status_code != 204
        assert (agents_dir / "researcher").exists()

    def test_null_byte_in_path_is_refused(self, client, agents_dir):
        create(client, "researcher")

        res = client.delete("/agents/name%00byte")

        assert res.status_code in (400, 404)
        assert (agents_dir / "researcher").exists()

    @pytest.mark.parametrize("name", PATH_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, agents_dir, name):
        res = client.delete(f"/agents/{name}")

        assert res.status_code == 400


class TestUpdateAgent:
    def test_replaces_claude_md_and_returns_new_content(self, client, agents_dir):
        create(client, "researcher")
        claude_md = agents_dir / "researcher" / "CLAUDE.md"

        res = client.put("/agents/researcher", json={"instructions": "# researcher\n\nNew instructions.\n"})

        assert res.status_code == 200
        assert claude_md.read_text(encoding="utf-8") == "# researcher\n\nNew instructions.\n"
        assert res.json() == {"name": "researcher", "instructions": "# researcher\n\nNew instructions.\n"}

    def test_missing_agent_is_404_and_creates_nothing(self, client, agents_dir):
        res = client.put("/agents/nope", json={"instructions": "# nope\n\nSomething.\n"})

        assert res.status_code == 404
        assert not (agents_dir / "nope").exists()

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, agents_dir, name):
        create(client, name)

        res = client.put(f"/agents/{name}", json={"instructions": "# updated\n"})

        assert res.status_code == 200
        assert (agents_dir / name / "CLAUDE.md").read_text(encoding="utf-8") == "# updated\n"

    def test_missing_instructions_field_is_refused(self, client, agents_dir):
        create(client, "researcher")
        claude_md = agents_dir / "researcher" / "CLAUDE.md"
        before = claude_md.read_text(encoding="utf-8")

        res = client.put("/agents/researcher", json={})

        assert res.status_code == 422
        assert claude_md.read_text(encoding="utf-8") == before

    def test_unencodable_instructions_is_400_not_500(self, client, agents_dir):
        # A lone UTF-16 surrogate is valid JSON (via a \uXXXX escape) and
        # decodes fine, but can't be written as UTF-8 text to disk. Sent as
        # raw content to bypass httpx's own JSON encoder, which would otherwise
        # reject it client-side before it ever reaches the server.
        create(client, "researcher")
        claude_md = agents_dir / "researcher" / "CLAUDE.md"
        before = claude_md.read_text(encoding="utf-8")

        res = client.put(
            "/agents/researcher",
            content=b'{"instructions": "\\ud800"}',
            headers={"Content-Type": "application/json"},
        )

        assert res.status_code == 400
        assert claude_md.read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("name", PATH_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, agents_dir, name):
        res = client.put(f"/agents/{name}", json={"instructions": "x"})

        assert res.status_code == 400

    def test_null_byte_in_path_is_refused(self, client, agents_dir):
        create(client, "researcher")
        claude_md = agents_dir / "researcher" / "CLAUDE.md"
        before = claude_md.read_text(encoding="utf-8")

        res = client.put("/agents/name%00byte", json={"instructions": "x"})

        assert res.status_code in (400, 404)
        assert claude_md.read_text(encoding="utf-8") == before

    def test_empty_instructions_body_is_accepted_and_clears_content(self, client, agents_dir):
        create(client, "researcher")
        claude_md = agents_dir / "researcher" / "CLAUDE.md"

        res = client.put("/agents/researcher", json={"instructions": ""})

        assert res.status_code == 200
        assert claude_md.read_text(encoding="utf-8") == ""
        assert res.json() == {"name": "researcher", "instructions": ""}

    def test_folder_without_claude_md_is_404_and_stays_without_one(self, client, agents_dir):
        # A folder can exist on disk without a CLAUDE.md (e.g. a stray directory
        # dropped into agents/); the same rule list_agents/get/delete use for
        # "is this actually an agent" should apply here too: no file means 404,
        # and PUT must not create one as a side effect of a failed update.
        folder = agents_dir / "stray"
        folder.mkdir(parents=True)

        res = client.put("/agents/stray", json={"instructions": "x"})

        assert res.status_code == 404
        assert not (folder / "CLAUDE.md").is_file()
