"""Tests for the FastAPI server endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sldd.server import create_app


@pytest.fixture()
def client(tmp_path: Path):
    root = tmp_path / "scanroot"
    root.mkdir()
    (root / "file.txt").write_bytes(b"x" * 100)
    sub = root / "subdir"
    sub.mkdir()
    (sub / "data.bin").write_bytes(b"y" * 500)

    db = str(tmp_path / "test.db")
    app = create_app(db_path=db, scan_root=str(root))
    with TestClient(app) as c:
        yield c


class TestSnapshotEndpoints:
    def test_list_empty(self, client: TestClient) -> None:
        r = client.get("/api/snapshots")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_and_list(self, client: TestClient) -> None:
        r = client.post("/api/snapshots", json={"label": "test"})
        assert r.status_code == 200
        snap = r.json()
        assert snap["id"] is not None

        r = client.get("/api/snapshots")
        assert len(r.json()) == 1

    def test_get_snapshot(self, client: TestClient) -> None:
        client.post("/api/snapshots", json={})
        r = client.get("/api/snapshots/1")
        assert r.status_code == 200
        assert r.json()["id"] == 1

    def test_get_nonexistent(self, client: TestClient) -> None:
        r = client.get("/api/snapshots/999")
        assert r.status_code == 404

    def test_delete_snapshot(self, client: TestClient) -> None:
        client.post("/api/snapshots", json={})
        r = client.delete("/api/snapshots/1")
        assert r.status_code == 200
        r = client.get("/api/snapshots/1")
        assert r.status_code == 404

    def test_prune(self, client: TestClient) -> None:
        for _ in range(4):
            client.post("/api/snapshots", json={})
        r = client.post("/api/snapshots/prune", json={"keep": 2})
        assert r.status_code == 200
        assert r.json()["deleted"] == 2


class TestDiffEndpoints:
    def _take_two(self, client: TestClient) -> None:
        client.post("/api/snapshots", json={"label": "before"})
        client.post("/api/snapshots", json={"label": "after"})

    def test_diff(self, client: TestClient) -> None:
        self._take_two(client)
        r = client.get("/api/diff", params={"old": 1, "new": 2})
        assert r.status_code == 200
        assert "entries" in r.json()

    def test_diff_latest(self, client: TestClient) -> None:
        self._take_two(client)
        r = client.get("/api/diff/latest")
        assert r.status_code == 200

    def test_diff_latest_needs_two(self, client: TestClient) -> None:
        client.post("/api/snapshots", json={})
        r = client.get("/api/diff/latest")
        assert r.status_code == 404

    def test_report(self, client: TestClient) -> None:
        self._take_two(client)
        r = client.get("/api/report", params={"old": 1, "new": 2})
        assert r.status_code == 200
        body = r.json()
        assert "anomalies" in body
        assert "top_growers" in body


class TestDrillEndpoints:
    def test_drill(self, client: TestClient) -> None:
        client.post("/api/snapshots", json={})
        snaps = client.get("/api/snapshots").json()
        root_path = snaps[0]["root_path"]
        r = client.get("/api/drill/1", params={"path": root_path})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_top_dirs(self, client: TestClient) -> None:
        client.post("/api/snapshots", json={})
        r = client.get("/api/top/1", params={"limit": 5})
        assert r.status_code == 200
        assert len(r.json()) <= 5


class TestPlaybackEndpoints:
    def test_playback_frames(self, client: TestClient) -> None:
        for _ in range(3):
            client.post("/api/snapshots", json={})
        r = client.get(
            "/api/playback/frames",
            params={"from": 1, "to": 3},
        )
        assert r.status_code == 200
        frames = r.json()
        assert len(frames) == 2

    def test_path_timeline(self, client: TestClient) -> None:
        for _ in range(3):
            client.post("/api/snapshots", json={})
        snaps = client.get("/api/snapshots").json()
        root_path = snaps[0]["root_path"]
        r = client.get(
            "/api/playback/path-timeline",
            params={"path": root_path, "from": 1, "to": 3},
        )
        assert r.status_code == 200


class TestDeletionEndpoints:
    def test_preview(self, client: TestClient, tmp_path: Path) -> None:
        f = tmp_path / "scanroot" / "todelete.txt"
        f.write_bytes(b"d" * 200)
        r = client.post(
            "/api/delete/preview", json={"paths": [str(f)]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total_bytes"] == 200

    def test_execute_needs_confirm(self, client: TestClient) -> None:
        r = client.post(
            "/api/delete/execute",
            json={"paths": ["/tmp/x"], "confirm": False},
        )
        assert r.status_code == 400

    def test_delete_history(self, client: TestClient) -> None:
        r = client.get("/api/delete/history")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestSettingsEndpoints:
    def test_get_empty(self, client: TestClient) -> None:
        r = client.get("/api/settings")
        assert r.status_code == 200
        assert r.json() == {}

    def test_save_and_get(self, client: TestClient) -> None:
        client.put(
            "/api/settings",
            json={"settings": {"scan.root": "/var", "detect.threshold": "500MB"}},
        )
        r = client.get("/api/settings")
        s = r.json()
        assert s["scan.root"] == "/var"
        assert s["detect.threshold"] == "500MB"


class TestDbInfo:
    def test_db_info(self, client: TestClient) -> None:
        r = client.get("/api/db-info")
        assert r.status_code == 200
        body = r.json()
        assert "size_bytes" in body
        assert "snapshot_count" in body

    def test_vacuum(self, client: TestClient) -> None:
        r = client.post("/api/db/vacuum")
        assert r.status_code == 200
