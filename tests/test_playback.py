"""Tests for the playback engine."""

from __future__ import annotations

import datetime as _dt

from sldd.models import DirEntry
from sldd.playback import build_frames, build_path_timeline
from sldd.storage import SnapshotStore
from tests.conftest import make_snapshot


class TestBuildFrames:
    def _setup(self, store: SnapshotStore) -> list[int]:
        ids = []
        for i in range(5):
            snap = make_snapshot(
                [
                    DirEntry(
                        path="/root", total_bytes=1000 + i * 200,
                        file_count=10 + i, dir_count=2, depth=0,
                    ),
                    DirEntry(
                        path="/root/logs", total_bytes=500 + i * 150,
                        file_count=5 + i, dir_count=0, depth=1,
                    ),
                ],
                timestamp=_dt.datetime(
                    2024, 1, 1, i, 0, 0, tzinfo=_dt.timezone.utc,
                ),
            )
            saved = store.save_snapshot(snap)
            assert saved.id is not None
            ids.append(saved.id)
        return ids

    def test_builds_correct_count(self, store: SnapshotStore) -> None:
        ids = self._setup(store)
        frames = build_frames(store, ids[0], ids[-1])
        assert len(frames) == 4

    def test_frames_ordered(self, store: SnapshotStore) -> None:
        ids = self._setup(store)
        frames = build_frames(store, ids[0], ids[-1])
        for i in range(1, len(frames)):
            assert frames[i].frame_index > frames[i - 1].frame_index

    def test_frame_has_growers(self, store: SnapshotStore) -> None:
        ids = self._setup(store)
        frames = build_frames(store, ids[0], ids[-1])
        assert len(frames[0].top_growers) > 0

    def test_elapsed_increases(self, store: SnapshotStore) -> None:
        ids = self._setup(store)
        frames = build_frames(store, ids[0], ids[-1])
        for i in range(1, len(frames)):
            assert (
                frames[i].elapsed_since_start_seconds
                > frames[i - 1].elapsed_since_start_seconds
            )

    def test_total_growth_positive(self, store: SnapshotStore) -> None:
        ids = self._setup(store)
        frames = build_frames(store, ids[0], ids[-1])
        for frame in frames:
            assert frame.total_growth_bytes > 0

    def test_not_enough_snapshots(self, store: SnapshotStore) -> None:
        snap = make_snapshot(
            [DirEntry(
                path="/root", total_bytes=100,
                file_count=1, dir_count=0, depth=0,
            )],
        )
        saved = store.save_snapshot(snap)
        assert saved.id is not None
        frames = build_frames(store, saved.id, saved.id)
        assert len(frames) == 0

    def test_subset_range(self, store: SnapshotStore) -> None:
        ids = self._setup(store)
        frames = build_frames(store, ids[1], ids[3])
        assert len(frames) == 2


class TestPathTimeline:
    def test_returns_data(self, store: SnapshotStore) -> None:
        for i in range(3):
            snap = make_snapshot(
                [DirEntry(
                    path="/root", total_bytes=100 * (i + 1),
                    file_count=i + 1, dir_count=0, depth=0,
                )],
                timestamp=_dt.datetime(
                    2024, 1, 1 + i, tzinfo=_dt.timezone.utc,
                ),
            )
            store.save_snapshot(snap)

        timeline = build_path_timeline(store, "/root", 1, 3)
        assert len(timeline) == 3
        assert timeline[0]["total_bytes"] == 100
        assert timeline[2]["total_bytes"] == 300
