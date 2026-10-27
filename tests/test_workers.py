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
# - "" as a path segment collapses the URL to "/workers" and 307-redirects to
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
def workers_dir(tmp_path):
    return tmp_path / "workers"


@pytest.fixture
def templates_dir(tmp_path):
    return tmp_path / "worker_templates"


@pytest.fixture
def client(workers_dir, templates_dir):
    return TestClient(create_app(workers_dir, templates_dir))


def write_template(templates_dir, name, description, body):
    templates_dir.mkdir(parents=True, exist_ok=True)
    (templates_dir / f"{name}.md").write_text(f"---\ndescription: {description}\n---\n{body}", encoding="utf-8")


def create(client, name):
    return client.post("/workers", json={"name": name})


class TestRootPage:
    def test_serves_the_web_ui(self, client):
        res = client.get("/")

        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Workers" in res.text


class TestListAgents:
    def test_empty_at_first(self, client):
        res = client.get("/workers")

        assert res.status_code == 200
        assert res.json() == []

    def test_includes_created_workers_sorted_by_name(self, client):
        create(client, "writer")
        create(client, "researcher")

        res = client.get("/workers")

        assert res.status_code == 200
        workers = res.json()
        assert [a["name"] for a in workers] == ["researcher", "writer"]
        assert workers[0]["instructions"].startswith("# researcher\n")

    def test_ignores_folders_without_claude_md(self, client, workers_dir):
        create(client, "researcher")
        stray = workers_dir / "not-an-worker"
        stray.mkdir()
        (stray / "notes.txt").write_text("not a CLAUDE.md", encoding="utf-8")

        res = client.get("/workers")

        assert res.status_code == 200
        assert [a["name"] for a in res.json()] == ["researcher"]


class TestCreateWorker:
    def test_writes_claude_md_and_returns_it(self, client, workers_dir):
        res = create(client, "researcher")

        assert res.status_code == 201
        claude_md = workers_dir / "researcher" / "CLAUDE.md"
        assert claude_md.is_file()
        assert claude_md.read_text(encoding="utf-8").startswith("# researcher\n")
        assert res.json() == {"name": "researcher", "instructions": claude_md.read_text(encoding="utf-8")}

    def test_initial_instructions_are_written_in_the_same_call(self, client, workers_dir):
        res = client.post("/workers", json={"name": "researcher", "instructions": "# researcher\n\nMine.\n"})

        assert res.status_code == 201
        assert res.json() == {"name": "researcher", "instructions": "# researcher\n\nMine.\n"}
        assert (workers_dir / "researcher" / "CLAUDE.md").read_text(encoding="utf-8") == "# researcher\n\nMine.\n"

    def test_unencodable_initial_instructions_is_400_and_creates_nothing(self, client, workers_dir):
        res = client.post(
            "/workers",
            content=b'{"name": "researcher", "instructions": "\\ud800"}',
            headers={"Content-Type": "application/json"},
        )

        assert res.status_code == 400
        assert list(workers_dir.iterdir()) == []

    def test_single_char_name_is_accepted(self, client, workers_dir):
        res = create(client, "a")

        assert res.status_code == 201
        assert (workers_dir / "a" / "CLAUDE.md").is_file()

    def test_name_at_max_length_is_accepted(self, client, workers_dir):
        name = "a" * 40

        res = create(client, name)

        assert res.status_code == 201
        assert (workers_dir / name / "CLAUDE.md").is_file()

    def test_name_over_max_length_is_refused(self, client, workers_dir):
        name = "a" * 41

        res = create(client, name)

        assert res.status_code == 400
        assert list(workers_dir.iterdir()) == []

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, workers_dir, name):
        res = create(client, name)

        assert res.status_code == 201
        assert (workers_dir / name / "CLAUDE.md").is_file()

    def test_duplicate_name_is_refused_and_does_not_overwrite(self, client, workers_dir):
        create(client, "researcher")
        claude_md = workers_dir / "researcher" / "CLAUDE.md"
        claude_md.write_text("# researcher\n\nMy edits.\n", encoding="utf-8")

        res = create(client, "researcher")

        assert res.status_code == 409
        assert claude_md.read_text(encoding="utf-8") == "# researcher\n\nMy edits.\n"

    def test_missing_name_field_is_refused(self, client):
        res = client.post("/workers", json={})

        assert res.status_code == 422

    def test_non_string_name_is_refused(self, client):
        res = client.post("/workers", json={"name": 123})

        assert res.status_code == 422

    @pytest.mark.parametrize("name", BODY_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, workers_dir, name):
        res = create(client, name)

        assert res.status_code == 400
        assert list(workers_dir.iterdir()) == []
        assert not (workers_dir.parent / "secret").exists()


class TestGetWorker:
    def test_returns_current_claude_md_content(self, client, workers_dir):
        create(client, "researcher")
        claude_md = workers_dir / "researcher" / "CLAUDE.md"
        claude_md.write_text("# researcher\n\nMy edits.\n", encoding="utf-8")

        res = client.get("/workers/researcher")

        assert res.status_code == 200
        assert res.json() == {"name": "researcher", "instructions": "# researcher\n\nMy edits.\n"}

    def test_reads_live_from_disk_not_a_cache(self, client, workers_dir):
        create(client, "researcher")
        client.get("/workers/researcher")
        (workers_dir / "researcher" / "CLAUDE.md").write_text("# researcher\n\nUpdated.\n", encoding="utf-8")

        res = client.get("/workers/researcher")

        assert res.json()["instructions"] == "# researcher\n\nUpdated.\n"

    def test_missing_worker_is_404(self, client):
        res = client.get("/workers/nope")

        assert res.status_code == 404

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, name):
        create(client, name)

        res = client.get(f"/workers/{name}")

        assert res.status_code == 200
        assert res.json()["name"] == name

    def test_path_with_extra_segments_is_not_found(self, client, workers_dir):
        # A "/" can never reach NAME_PATTERN validation: Starlette's router only
        # matches a single path segment against {name}, so this 404s before the
        # app ever sees the value — nothing outside workers/ is ever touched.
        create(client, "researcher")

        res = client.get("/workers/researcher/../../secret")

        assert res.status_code in (404, 422)
        assert not (workers_dir.parent.parent / "secret").exists()

    def test_dot_dot_segment_never_reaches_the_app(self, client, workers_dir):
        # "/workers/.." is normalized by the HTTP client to "/" (RFC 3986) before
        # the request is sent, so it never arrives as worker name "..". It lands
        # on an unrelated route; either way nothing worker-specific is returned
        # and nothing outside workers/ is touched.
        res = client.get("/workers/..", follow_redirects=False)

        assert "application/json" not in res.headers.get("content-type", "")
        assert not (workers_dir.parent / "secret").exists()

    def test_dot_segment_never_reaches_the_app(self, client, workers_dir):
        # "/workers/." normalizes to "/workers" (the list endpoint), not worker
        # name ".". Confirms it can't be (mis)read as a single-dot worker name.
        res = client.get("/workers/.", follow_redirects=False)

        assert res.status_code in (200, 307)
        if res.status_code == 200:
            assert res.json() == []  # the list endpoint, not a "." worker

    def test_null_byte_in_path_is_refused(self, client):
        # Sent URL-encoded (%00) so it actually reaches the app as a path
        # param, rather than tripping the HTTP client's own URL validation.
        res = client.get("/workers/name%00byte")

        assert res.status_code in (400, 404)

    @pytest.mark.parametrize("name", PATH_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, name):
        res = client.get(f"/workers/{name}")

        assert res.status_code == 400


class TestDeleteWorker:
    def test_removes_folder(self, client, workers_dir):
        create(client, "researcher")

        res = client.delete("/workers/researcher")

        assert res.status_code == 204
        assert not (workers_dir / "researcher").exists()

    def test_removes_from_list(self, client):
        create(client, "writer")
        create(client, "researcher")

        client.delete("/workers/writer")
        res = client.get("/workers")

        assert res.status_code == 200
        assert [a["name"] for a in res.json()] == ["researcher"]

    def test_second_delete_of_same_worker_is_404(self, client):
        create(client, "researcher")
        client.delete("/workers/researcher")

        res = client.delete("/workers/researcher")

        assert res.status_code == 404

    def test_missing_worker_is_404(self, client, workers_dir):
        res = client.delete("/workers/nope")

        assert res.status_code == 404
        assert not (workers_dir / "nope").exists()

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, workers_dir, name):
        create(client, name)

        res = client.delete(f"/workers/{name}")

        assert res.status_code == 204
        assert not (workers_dir / name).exists()

    def test_only_deletes_the_named_worker(self, client, workers_dir):
        create(client, "writer")
        create(client, "researcher")

        client.delete("/workers/writer")

        assert not (workers_dir / "writer").exists()
        assert (workers_dir / "researcher").exists()

    def test_dot_dot_segment_never_reaches_the_app(self, client, workers_dir):
        # Normalized to "/" by the HTTP client before sending; DELETE has no
        # handler there, so this is 405 — confirming it never deletes anything.
        create(client, "researcher")

        res = client.delete("/workers/..", follow_redirects=False)

        assert res.status_code != 204
        assert (workers_dir / "researcher").exists()

    def test_null_byte_in_path_is_refused(self, client, workers_dir):
        create(client, "researcher")

        res = client.delete("/workers/name%00byte")

        assert res.status_code in (400, 404)
        assert (workers_dir / "researcher").exists()

    @pytest.mark.parametrize("name", PATH_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, workers_dir, name):
        res = client.delete(f"/workers/{name}")

        assert res.status_code == 400


class TestUpdateWorker:
    def test_replaces_claude_md_and_returns_new_content(self, client, workers_dir):
        create(client, "researcher")
        claude_md = workers_dir / "researcher" / "CLAUDE.md"

        res = client.put("/workers/researcher", json={"instructions": "# researcher\n\nNew instructions.\n"})

        assert res.status_code == 200
        assert claude_md.read_text(encoding="utf-8") == "# researcher\n\nNew instructions.\n"
        assert res.json() == {"name": "researcher", "instructions": "# researcher\n\nNew instructions.\n"}

    def test_missing_worker_is_404_and_creates_nothing(self, client, workers_dir):
        res = client.put("/workers/nope", json={"instructions": "# nope\n\nSomething.\n"})

        assert res.status_code == 404
        assert not (workers_dir / "nope").exists()

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, workers_dir, name):
        create(client, name)

        res = client.put(f"/workers/{name}", json={"instructions": "# updated\n"})

        assert res.status_code == 200
        assert (workers_dir / name / "CLAUDE.md").read_text(encoding="utf-8") == "# updated\n"

    def test_missing_instructions_field_is_refused(self, client, workers_dir):
        create(client, "researcher")
        claude_md = workers_dir / "researcher" / "CLAUDE.md"
        before = claude_md.read_text(encoding="utf-8")

        res = client.put("/workers/researcher", json={})

        assert res.status_code == 422
        assert claude_md.read_text(encoding="utf-8") == before

    def test_unencodable_instructions_is_400_not_500(self, client, workers_dir):
        # A lone UTF-16 surrogate is valid JSON (via a \uXXXX escape) and
        # decodes fine, but can't be written as UTF-8 text to disk. Sent as
        # raw content to bypass httpx's own JSON encoder, which would otherwise
        # reject it client-side before it ever reaches the server.
        create(client, "researcher")
        claude_md = workers_dir / "researcher" / "CLAUDE.md"
        before = claude_md.read_text(encoding="utf-8")

        res = client.put(
            "/workers/researcher",
            content=b'{"instructions": "\\ud800"}',
            headers={"Content-Type": "application/json"},
        )

        assert res.status_code == 400
        assert claude_md.read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("name", PATH_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, workers_dir, name):
        res = client.put(f"/workers/{name}", json={"instructions": "x"})

        assert res.status_code == 400

    def test_null_byte_in_path_is_refused(self, client, workers_dir):
        create(client, "researcher")
        claude_md = workers_dir / "researcher" / "CLAUDE.md"
        before = claude_md.read_text(encoding="utf-8")

        res = client.put("/workers/name%00byte", json={"instructions": "x"})

        assert res.status_code in (400, 404)
        assert claude_md.read_text(encoding="utf-8") == before

    def test_empty_instructions_body_is_accepted_and_clears_content(self, client, workers_dir):
        create(client, "researcher")
        claude_md = workers_dir / "researcher" / "CLAUDE.md"

        res = client.put("/workers/researcher", json={"instructions": ""})

        assert res.status_code == 200
        assert claude_md.read_text(encoding="utf-8") == ""
        assert res.json() == {"name": "researcher", "instructions": ""}

    def test_folder_without_claude_md_is_404_and_stays_without_one(self, client, workers_dir):
        # A folder can exist on disk without a CLAUDE.md (e.g. a stray directory
        # dropped into workers/); the same rule list_workers/get/delete use for
        # "is this actually a worker" should apply here too: no file means 404,
        # and PUT must not create one as a side effect of a failed update.
        folder = workers_dir / "stray"
        folder.mkdir(parents=True)

        res = client.put("/workers/stray", json={"instructions": "x"})

        assert res.status_code == 404
        assert not (folder / "CLAUDE.md").is_file()


class TestListTemplates:
    def test_empty_when_no_templates_dir(self, client):
        res = client.get("/templates")

        assert res.status_code == 200
        assert res.json() == []

    def test_lists_templates_sorted_by_name_with_description(self, client, templates_dir):
        write_template(templates_dir, "writer", "Writes prose", "# writer\n")
        write_template(templates_dir, "researcher", "Does research", "# researcher\n")

        res = client.get("/templates")

        assert res.status_code == 200
        assert res.json() == [
            {"name": "researcher", "description": "Does research"},
            {"name": "writer", "description": "Writes prose"},
        ]

    def test_ignores_non_markdown_files(self, client, templates_dir):
        write_template(templates_dir, "researcher", "Does research", "# researcher\n")
        templates_dir.mkdir(parents=True, exist_ok=True)
        (templates_dir / "notes.txt").write_text("not a template", encoding="utf-8")

        res = client.get("/templates")

        assert res.status_code == 200
        assert [t["name"] for t in res.json()] == ["researcher"]

    def test_missing_frontmatter_falls_back_to_empty_description(self, client, templates_dir):
        templates_dir.mkdir(parents=True, exist_ok=True)
        (templates_dir / "plain.md").write_text("# plain\n\nNo frontmatter here.\n", encoding="utf-8")

        res = client.get("/templates")

        assert res.status_code == 200
        assert res.json() == [{"name": "plain", "description": ""}]

    def test_non_utf8_file_is_skipped_not_500(self, client, templates_dir):
        write_template(templates_dir, "researcher", "Does research", "# researcher\n")
        templates_dir.mkdir(parents=True, exist_ok=True)
        (templates_dir / "broken.md").write_bytes(b"\xff\xfe not valid utf-8")

        res = client.get("/templates")

        assert res.status_code == 200
        assert [t["name"] for t in res.json()] == ["researcher"]


class TestGetTemplate:
    def test_returns_body_without_frontmatter(self, client, templates_dir):
        write_template(templates_dir, "researcher", "Does research", "# researcher\n\nBody text.\n")

        res = client.get("/templates/researcher")

        assert res.status_code == 200
        assert res.json() == {"content": "# researcher\n\nBody text.\n"}

    def test_missing_template_is_404(self, client):
        res = client.get("/templates/nope")

        assert res.status_code == 404

    def test_non_utf8_file_is_404_not_500(self, client, templates_dir):
        templates_dir.mkdir(parents=True, exist_ok=True)
        (templates_dir / "broken.md").write_bytes(b"\xff\xfe not valid utf-8")

        res = client.get("/templates/broken")

        assert res.status_code == 404

    @pytest.mark.parametrize("name", PATH_INVALID_NAMES)
    def test_bad_name_is_refused(self, client, name):
        res = client.get(f"/templates/{name}")

        assert res.status_code == 400

    @pytest.mark.parametrize("name", NEWLY_VALID_NAMES)
    def test_leading_or_double_dash_name_is_accepted(self, client, templates_dir, name):
        write_template(templates_dir, name, "d", "body\n")

        res = client.get(f"/templates/{name}")

        assert res.status_code == 200
        assert res.json() == {"content": "body\n"}

    def test_path_traversal_name_cannot_escape_templates_dir(self, client, templates_dir, tmp_path):
        templates_dir.mkdir(parents=True, exist_ok=True)
        secret = tmp_path / "secret.md"
        secret.write_text("top secret", encoding="utf-8")

        res = client.get("/templates/..%2Fsecret")

        assert res.status_code in (400, 404)


class TestWriteSkill:
    def test_writes_skill_md_under_worker(self, client, workers_dir):
        create(client, "researcher")

        res = client.post(
            "/workers/researcher/skills",
            json={"skill_name": "web-search", "content": "# web-search\n\nHow to search.\n"},
        )

        assert res.status_code == 201
        skill_md = workers_dir / "researcher" / ".claude" / "skills" / "web-search" / "SKILL.md"
        assert skill_md.is_file()
        assert skill_md.read_text(encoding="utf-8") == "# web-search\n\nHow to search.\n"
        assert res.json() == {"name": "web-search", "content": "# web-search\n\nHow to search.\n"}

    def test_missing_worker_is_404(self, client, workers_dir):
        res = client.post("/workers/nope/skills", json={"skill_name": "web-search", "content": "x"})

        assert res.status_code == 404
        assert not (workers_dir / "nope").exists()

    @pytest.mark.parametrize("name", PATH_INVALID_NAMES)
    def test_bad_worker_name_is_refused(self, client, name):
        res = client.post(f"/workers/{name}/skills", json={"skill_name": "web-search", "content": "x"})

        assert res.status_code == 400

    @pytest.mark.parametrize("skill_name", BODY_INVALID_NAMES)
    def test_bad_skill_name_is_refused(self, client, workers_dir, skill_name):
        create(client, "researcher")

        res = client.post("/workers/researcher/skills", json={"skill_name": skill_name, "content": "x"})

        assert res.status_code == 400
        assert not (workers_dir / "researcher" / ".claude" / "skills").exists()

    def test_missing_skill_name_field_is_refused(self, client, workers_dir):
        create(client, "researcher")

        res = client.post("/workers/researcher/skills", json={"content": "x"})

        assert res.status_code == 422

    def test_creates_parent_dirs(self, client, workers_dir):
        create(client, "researcher")
        assert not (workers_dir / "researcher" / ".claude").exists()

        res = client.post("/workers/researcher/skills", json={"skill_name": "web-search", "content": "x"})

        assert res.status_code == 201
        assert (workers_dir / "researcher" / ".claude" / "skills" / "web-search" / "SKILL.md").is_file()
