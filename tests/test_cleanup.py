import shutil

from fastapi.testclient import TestClient

from app import main as app_main
from tests.test_sessions import (  # noqa: F401 -- fixtures and fakes shared with the session tests
    SPAWNED,
    STOPPED,
    _reset_fakes,
    client,
    create_worker,
    make_app,
    messages_log,
    sessions_db,
    spawn,
    templates_dir,
    workers_dir,
)


class TestDeleteBusyWorker:
    def test_folder_held_by_a_process_is_409_not_500(self, client, workers_dir, monkeypatch):
        create_worker(client, "researcher")

        def busy(path, *args, **kwargs):
            raise PermissionError(32, "The process cannot access the file", str(path))

        monkeypatch.setattr(app_main.shutil, "rmtree", busy)

        res = client.delete("/workers/researcher")

        assert res.status_code == 409
        assert res.json()["detail"].startswith("worker_busy")
        assert (workers_dir / "researcher" / "CLAUDE.md").is_file()

    def test_normal_delete_still_204(self, client, workers_dir):
        create_worker(client, "researcher")

        assert client.delete("/workers/researcher").status_code == 204
        assert not (workers_dir / "researcher").exists()


class TestNoGhostFolders:
    def test_reconciliation_does_not_resurrect_a_deleted_worker(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        first = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log))
        create_worker(first, "researcher")
        spawn(first, "researcher")
        shutil.rmtree(workers_dir / "researcher")  # the user deleted the worker meanwhile

        with TestClient(
            make_app(workers_dir, templates_dir, sessions_db, messages_log, running_ids_fn=lambda: set())
        ):
            pass

        assert not (workers_dir / "researcher").exists()

    def test_ending_a_session_of_a_deleted_worker_does_not_resurrect_it(self, client, workers_dir):
        create_worker(client, "researcher")
        sid = spawn(client, "researcher").json()["session_id"]
        shutil.rmtree(workers_dir / "researcher")

        res = client.post(f"/sessions/{sid}/end")

        assert res.status_code == 200
        assert not (workers_dir / "researcher").exists()
