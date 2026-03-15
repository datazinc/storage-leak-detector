"""Tests for the filesystem snapshot engine."""

from __future__ import annotations

from pathlib import Path

from sldd.models import ScanConfig
from sldd.platform_utils import normalize_path
from sldd.snapshot import take_snapshot


class TestTakeSnapshot:
    def test_basic_walk(self, tmp_dir: Path) -> None:
        config = ScanConfig(root=str(tmp_dir), excludes=[], max_depth=None)
        snap = take_snapshot(config)

        assert snap.id is None  # not persisted yet
        assert len(snap.entries) > 0
        assert snap.root_path == normalize_path(str(tmp_dir))

    def test_root_aggregates_all(self, tmp_dir: Path) -> None:
        config = ScanConfig(root=str(tmp_dir), excludes=[])
        snap = take_snapshot(config)

        root_entry = next(e for e in snap.entries if e.depth == 0)
        assert root_entry.total_bytes == 10 + 100 + 200 + 50  # 360

    def test_subtree_sizes(self, tmp_dir: Path) -> None:
        config = ScanConfig(root=str(tmp_dir), excludes=[])
        snap = take_snapshot(config)

        by_path = {e.path: e for e in snap.entries}
        a_path = normalize_path(str(tmp_dir / "a"))
        b_path = normalize_path(str(tmp_dir / "a" / "b"))
        c_path = normalize_path(str(tmp_dir / "c"))

        assert by_path[a_path].total_bytes == 300  # 100 + 200
        assert by_path[b_path].total_bytes == 200
        assert by_path[c_path].total_bytes == 50

    def test_file_counts(self, tmp_dir: Path) -> None:
        config = ScanConfig(root=str(tmp_dir), excludes=[])
        snap = take_snapshot(config)

        root_entry = next(e for e in snap.entries if e.depth == 0)
        assert root_entry.file_count == 4  # file0 + file1 + file2 + file3

    def test_max_depth(self, tmp_dir: Path) -> None:
        config = ScanConfig(root=str(tmp_dir), excludes=[], max_depth=1)
        snap = take_snapshot(config)

        depths = {e.depth for e in snap.entries}
        assert max(depths) <= 1

    def test_exclude(self, tmp_dir: Path) -> None:
        a_path = str(tmp_dir / "a")
        config = ScanConfig(root=str(tmp_dir), excludes=[a_path])
        snap = take_snapshot(config)

        paths = {e.path for e in snap.entries}
        norm_a = normalize_path(a_path)
        assert norm_a not in paths

    def test_progress_callback(self, tmp_dir: Path) -> None:
        calls: list[tuple[str, int]] = []

        def progress(path: str, count: int) -> None:
            calls.append((path, count))

        config = ScanConfig(root=str(tmp_dir), excludes=[])
        take_snapshot(config, progress=progress)
        # small tree — may or may not trigger (threshold is 500 dirs)
        # just ensure it doesn't crash

    def test_label(self, tmp_dir: Path) -> None:
        config = ScanConfig(root=str(tmp_dir), excludes=[])
        snap = take_snapshot(config, label="my-label")
        assert snap.label == "my-label"

    def test_symlinks_not_followed_by_default(self, tmp_dir: Path) -> None:
        target = tmp_dir / "a" / "file1.txt"
        link = tmp_dir / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            return  # symlinks not supported (Windows without privileges)

        config = ScanConfig(root=str(tmp_dir), excludes=[], follow_symlinks=False)
        snap = take_snapshot(config)

        root_entry = next(e for e in snap.entries if e.depth == 0)
        assert root_entry.total_bytes == 360  # symlink not counted

    def test_empty_dir(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        config = ScanConfig(root=str(empty), excludes=[])
        snap = take_snapshot(config)
        assert len(snap.entries) == 1
        assert snap.entries[0].total_bytes == 0
