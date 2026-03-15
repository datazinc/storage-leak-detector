"""Tests for the deletion service — safety is paramount."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sldd.delete import _is_blocked, execute_delete, preview_delete
from sldd.models import ScanConfig
from sldd.storage import SnapshotStore


class TestBlocklist:
    @pytest.mark.parametrize("path", [
        "/", "/bin", "/usr", "/etc", "/sbin", "/var",
        "/System", "/Applications", "/Library",
    ])
    def test_system_paths_blocked(self, path: str) -> None:
        assert _is_blocked(path)

    def test_home_root_blocked(self) -> None:
        assert _is_blocked("/Users")
        assert _is_blocked("/home")

    def test_user_home_blocked(self) -> None:
        assert _is_blocked("/Users/alice")
        assert _is_blocked("/home/bob")

    def test_deep_user_path_not_blocked(self) -> None:
        assert not _is_blocked("/Users/alice/Downloads/junk")
        assert not _is_blocked("/home/bob/.cache/old")

    def test_normal_path_not_blocked(self) -> None:
        assert not _is_blocked("/tmp/test/foo")
        assert not _is_blocked("/opt/myapp/logs")


class TestPreview:
    def test_preview_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_bytes(b"x" * 100)
        preview = preview_delete([str(f)])
        assert len(preview.targets) == 1
        assert preview.targets[0].exists
        assert preview.targets[0].size_bytes == 100
        assert preview.total_bytes == 100
        assert preview.all_writable

    def test_preview_existing_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "a.txt").write_bytes(b"a" * 50)
        (d / "b.txt").write_bytes(b"b" * 75)
        preview = preview_delete([str(d)])
        assert preview.targets[0].is_dir
        assert preview.targets[0].file_count == 2
        assert preview.total_bytes == 125

    def test_preview_nonexistent(self) -> None:
        preview = preview_delete(["/nonexistent_xyz_12345"])
        assert len(preview.targets) == 1
        assert not preview.targets[0].exists

    def test_preview_blocked_path(self) -> None:
        preview = preview_delete(["/usr"])
        assert len(preview.targets) == 0
        assert "/usr" in preview.blocked_paths

    def test_preview_outside_scan_root(self, tmp_path: Path) -> None:
        other = tmp_path / "other"
        other.mkdir()
        scan_root = tmp_path / "root"
        scan_root.mkdir()
        preview = preview_delete([str(other)], scan_root=str(scan_root))
        assert str(other) in preview.blocked_paths

    def test_preview_scan_root_itself_blocked(self, tmp_path: Path) -> None:
        preview = preview_delete([str(tmp_path)], scan_root=str(tmp_path))
        assert str(tmp_path) in preview.blocked_paths


class TestExecute:
    def test_delete_file(self, tmp_path: Path, store: SnapshotStore) -> None:
        f = tmp_path / "todelete.txt"
        f.write_bytes(b"x" * 200)
        result = execute_delete([str(f)], store)
        assert len(result.succeeded) == 1
        assert result.bytes_freed == 200
        assert not f.exists()

    def test_delete_directory(self, tmp_path: Path, store: SnapshotStore) -> None:
        d = tmp_path / "todelete"
        d.mkdir()
        (d / "inner.txt").write_bytes(b"y" * 300)
        result = execute_delete([str(d)], store)
        assert len(result.succeeded) == 1
        assert result.bytes_freed == 300
        assert not d.exists()

    def test_delete_blocked_path_refused(self, store: SnapshotStore) -> None:
        result = execute_delete(["/usr"], store)
        assert len(result.succeeded) == 0
        assert len(result.failed) == 1
        assert "blocked" in result.failed[0][1]

    def test_dry_run_does_not_delete(
        self, tmp_path: Path, store: SnapshotStore,
    ) -> None:
        f = tmp_path / "keep.txt"
        f.write_bytes(b"z" * 100)
        result = execute_delete([str(f)], store, dry_run=True)
        assert len(result.succeeded) == 1
        assert result.dry_run
        assert f.exists()

    def test_audit_log_written(
        self, tmp_path: Path, store: SnapshotStore,
    ) -> None:
        f = tmp_path / "logged.txt"
        f.write_bytes(b"w" * 50)
        execute_delete([str(f)], store)
        history = store.get_deletion_history()
        assert len(history) == 1
        assert history[0]["path"] == str(f)
        assert history[0]["bytes_freed"] == 50
        assert history[0]["success"]
