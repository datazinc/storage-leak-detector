"""Tests for the diff engine."""

from __future__ import annotations

import datetime as _dt

from sldd.diff import compute_diff, compute_diff_from_ids, compute_latest_diff
from sldd.models import DirEntry, Snapshot
from sldd.storage import SnapshotStore
from tests.conftest import make_snapshot


class TestComputeDiff:
    def _setup(self, store: SnapshotStore) -> tuple[Snapshot, Snapshot]:
        s1 = make_snapshot(
            [
                DirEntry(path="/root", total_bytes=500, file_count=5, dir_count=2, depth=0),
                DirEntry(path="/root/logs", total_bytes=300, file_count=3, dir_count=0, depth=1),
                DirEntry(path="/root/data", total_bytes=200, file_count=2, dir_count=0, depth=1),
            ],
            timestamp=_dt.datetime(2024, 1, 1, 10, 0, 0, tzinfo=_dt.timezone.utc),
        )
        s2 = make_snapshot(
            [
                DirEntry(path="/root", total_bytes=1500, file_count=12, dir_count=2, depth=0),
                DirEntry(path="/root/logs", total_bytes=1200, file_count=10, dir_count=0, depth=1),
                DirEntry(path="/root/data", total_bytes=300, file_count=2, dir_count=0, depth=1),
            ],
            timestamp=_dt.datetime(2024, 1, 1, 11, 0, 0, tzinfo=_dt.timezone.utc),
        )
        saved1 = store.save_snapshot(s1)
        saved2 = store.save_snapshot(s2)
        return saved1, saved2

    def test_basic_diff(self, store: SnapshotStore) -> None:
        s1, s2 = self._setup(store)
        diff = compute_diff(store, s1, s2)

        assert diff.elapsed_seconds == 3600.0  # 1 hour
        assert diff.total_growth_bytes == 1000

        by_path = {e.path: e for e in diff.entries}
        assert by_path["/root/logs"].growth_bytes == 900
        assert by_path["/root/data"].growth_bytes == 100

    def test_growth_pct(self, store: SnapshotStore) -> None:
        s1, s2 = self._setup(store)
        diff = compute_diff(store, s1, s2)

        by_path = {e.path: e for e in diff.entries}
        assert by_path["/root/logs"].growth_pct == 300.0  # 300% increase

    def test_sorted_by_growth(self, store: SnapshotStore) -> None:
        s1, s2 = self._setup(store)
        diff = compute_diff(store, s1, s2)

        growths = [e.growth_bytes for e in diff.entries]
        assert growths == sorted(growths, reverse=True)

    def test_min_growth_filter(self, store: SnapshotStore) -> None:
        s1, s2 = self._setup(store)
        diff = compute_diff(store, s1, s2, min_growth_bytes=200)

        for e in diff.entries:
            assert e.growth_bytes >= 200


class TestConvenienceFunctions:
    def _setup(self, store: SnapshotStore) -> None:
        for i in range(3):
            snap = make_snapshot(
                [DirEntry(path="/root", total_bytes=100 * (i + 1), file_count=i, dir_count=0, depth=0)],
                timestamp=_dt.datetime(2024, 1, 1 + i, tzinfo=_dt.timezone.utc),
            )
            store.save_snapshot(snap)

    def test_diff_from_ids(self, store: SnapshotStore) -> None:
        self._setup(store)
        diff = compute_diff_from_ids(store, 1, 3)
        assert diff is not None
        assert diff.entries[0].growth_bytes == 200

    def test_diff_from_ids_missing(self, store: SnapshotStore) -> None:
        assert compute_diff_from_ids(store, 999, 998) is None

    def test_latest_diff(self, store: SnapshotStore) -> None:
        self._setup(store)
        diff = compute_latest_diff(store)
        assert diff is not None
        assert diff.entries[0].growth_bytes == 100  # 300 - 200

    def test_latest_diff_not_enough_snapshots(self, store: SnapshotStore) -> None:
        snap = make_snapshot(
            [DirEntry(path="/root", total_bytes=100, file_count=1, dir_count=0, depth=0)]
        )
        store.save_snapshot(snap)
        assert compute_latest_diff(store) is None
