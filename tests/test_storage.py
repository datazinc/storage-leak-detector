"""Tests for the SQLite storage layer."""

from __future__ import annotations

import datetime as _dt

import pytest

from sldd.models import DirEntry
from sldd.storage import SnapshotStore, StorageError
from tests.conftest import make_snapshot


class TestSnapshotStoreLifecycle:
    def test_context_manager(self, db_path: str) -> None:
        with SnapshotStore(db_path) as store:
            snaps = store.list_snapshots()
            assert snaps == []

    def test_not_opened_raises(self, db_path: str) -> None:
        store = SnapshotStore(db_path)
        with pytest.raises(StorageError, match="not open"):
            store.list_snapshots()


class TestSaveAndLoad:
    def test_save_and_retrieve(self, store: SnapshotStore) -> None:
        entries = [
            DirEntry(path="/test", total_bytes=1000, file_count=5, dir_count=2, depth=0),
            DirEntry(path="/test/a", total_bytes=600, file_count=3, dir_count=0, depth=1),
            DirEntry(path="/test/b", total_bytes=400, file_count=2, dir_count=0, depth=1),
        ]
        snap = make_snapshot(entries, root="/test")
        saved = store.save_snapshot(snap)

        assert saved.id is not None
        assert saved.id > 0

        loaded = store.get_snapshot(saved.id, with_entries=True)
        assert loaded is not None
        assert loaded.id == saved.id
        assert len(loaded.entries) == 3
        assert loaded.entries[0].total_bytes == 1000

    def test_save_multiple(self, store: SnapshotStore) -> None:
        for i in range(3):
            snap = make_snapshot(
                [DirEntry(path="/test", total_bytes=i * 100, file_count=i, dir_count=0, depth=0)],
                timestamp=_dt.datetime(2024, 1, 1 + i, tzinfo=_dt.timezone.utc),
            )
            store.save_snapshot(snap)

        snaps = store.list_snapshots()
        assert len(snaps) == 3
        assert snaps[0].timestamp > snaps[1].timestamp  # newest first


class TestDelete:
    def test_delete_snapshot(self, store: SnapshotStore) -> None:
        snap = make_snapshot(
            [DirEntry(path="/test", total_bytes=100, file_count=1, dir_count=0, depth=0)],
        )
        saved = store.save_snapshot(snap)
        assert saved.id is not None
        store.delete_snapshot(saved.id)
        assert store.get_snapshot(saved.id) is None

    def test_prune(self, store: SnapshotStore) -> None:
        for i in range(5):
            snap = make_snapshot(
                [DirEntry(path="/test", total_bytes=i, file_count=0, dir_count=0, depth=0)],
                timestamp=_dt.datetime(2024, 1, 1 + i, tzinfo=_dt.timezone.utc),
            )
            store.save_snapshot(snap)

        deleted = store.prune_old_snapshots(keep=2)
        assert deleted == 3
        remaining = store.list_snapshots()
        assert len(remaining) == 2


class TestQueries:
    def _setup_two_snapshots(self, store: SnapshotStore) -> tuple[int, int]:
        s1 = make_snapshot(
            [
                DirEntry(path="/root", total_bytes=500, file_count=5, dir_count=2, depth=0),
                DirEntry(path="/root/a", total_bytes=300, file_count=3, dir_count=0, depth=1),
                DirEntry(path="/root/b", total_bytes=200, file_count=2, dir_count=0, depth=1),
            ],
            timestamp=_dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc),
        )
        s2 = make_snapshot(
            [
                DirEntry(path="/root", total_bytes=900, file_count=8, dir_count=2, depth=0),
                DirEntry(path="/root/a", total_bytes=700, file_count=6, dir_count=0, depth=1),
                DirEntry(path="/root/b", total_bytes=200, file_count=2, dir_count=0, depth=1),
            ],
            timestamp=_dt.datetime(2024, 1, 2, tzinfo=_dt.timezone.utc),
        )
        id1 = store.save_snapshot(s1).id
        id2 = store.save_snapshot(s2).id
        assert id1 is not None and id2 is not None
        return id1, id2

    def test_latest_snapshot(self, store: SnapshotStore) -> None:
        id1, id2 = self._setup_two_snapshots(store)
        latest = store.get_latest_snapshot()
        assert latest is not None
        assert latest.id == id2

    def test_get_entry(self, store: SnapshotStore) -> None:
        id1, _ = self._setup_two_snapshots(store)
        entry = store.get_entry(id1, "/root/a")
        assert entry is not None
        assert entry.total_bytes == 300

    def test_get_children(self, store: SnapshotStore) -> None:
        id1, _ = self._setup_two_snapshots(store)
        children = store.get_children(id1, "/root", 0)
        assert len(children) == 2

    def test_top_dirs(self, store: SnapshotStore) -> None:
        id1, _ = self._setup_two_snapshots(store)
        top = store.get_top_dirs(id1, limit=2)
        assert len(top) == 2
        assert top[0].total_bytes >= top[1].total_bytes

    def test_diff_entries_raw(self, store: SnapshotStore) -> None:
        id1, id2 = self._setup_two_snapshots(store)
        raw = store.diff_entries_raw(id1, id2, limit=10)
        assert len(raw) > 0
        paths = [r[0] for r in raw]
        assert "/root/a" in paths

        a_row = next(r for r in raw if r[0] == "/root/a")
        assert a_row[3] == 400  # growth: 700 - 300

    def test_path_history(self, store: SnapshotStore) -> None:
        self._setup_two_snapshots(store)
        history = store.get_path_history("/root/a")
        assert len(history) == 2
