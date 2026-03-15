"""Tests for cross-platform utilities."""

from __future__ import annotations

from pathlib import Path

from sldd.platform_utils import (
    default_excludes,
    is_excluded,
    is_same_device,
    normalize_path,
    safe_scandir,
    safe_stat,
)


class TestNormalizePath:
    def test_posix(self) -> None:
        assert normalize_path("/foo/bar") == "/foo/bar"

    def test_trailing_slash(self) -> None:
        result = normalize_path("/foo/bar/")
        assert result == "/foo/bar"

    def test_relative(self) -> None:
        result = normalize_path("foo/bar")
        assert "/" not in result or result.count("/") == 1  # at least normalized


class TestIsExcluded:
    def test_excluded(self) -> None:
        excludes = {"/proc", "/sys"}
        assert is_excluded("/proc/1/fd", excludes)
        assert is_excluded("/sys/class", excludes)

    def test_not_excluded(self) -> None:
        excludes = {"/proc", "/sys"}
        assert not is_excluded("/var/log", excludes)
        assert not is_excluded("/home", excludes)


class TestIsSameDevice:
    def test_same_device(self, tmp_path: Path) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        assert is_same_device(str(subdir), str(tmp_path))

    def test_nonexistent_returns_false(self) -> None:
        assert not is_same_device("/nonexistent_path_xyz", "/")


class TestSafeStat:
    def test_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("hi")
        result = safe_stat(str(f))
        assert result is not None
        assert result.st_size == 2

    def test_nonexistent(self) -> None:
        assert safe_stat("/nonexistent_path_xyz") is None


class TestSafeScandir:
    def test_normal_dir(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        entries = safe_scandir(str(tmp_path))
        names = {e.name for e in entries}
        assert "a.txt" in names
        assert "b.txt" in names

    def test_nonexistent_dir(self) -> None:
        assert safe_scandir("/nonexistent_dir_xyz") == []


class TestDefaultExcludes:
    def test_returns_list(self) -> None:
        result = default_excludes()
        assert isinstance(result, list)
        assert len(result) > 0
