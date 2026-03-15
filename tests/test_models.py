"""Tests for domain models — ensure they're well-behaved data classes."""

from __future__ import annotations

import datetime as _dt

from sldd.models import (
    DetectConfig,
    DirDiff,
    DirEntry,
    ScanConfig,
    Severity,
    Snapshot,
    WatchConfig,
)


class TestDirEntry:
    def test_creation(self) -> None:
        e = DirEntry(path="/foo", total_bytes=1024, file_count=3, dir_count=1, depth=2)
        assert e.path == "/foo"
        assert e.total_bytes == 1024
        assert e.error is None

    def test_frozen(self) -> None:
        e = DirEntry(path="/foo", total_bytes=0, file_count=0, dir_count=0, depth=0)
        try:
            e.path = "/bar"  # type: ignore[misc]
            assert False, "Should not allow mutation"
        except AttributeError:
            pass

    def test_with_error(self) -> None:
        e = DirEntry(path="/foo", total_bytes=0, file_count=0, dir_count=0, depth=0, error="denied")
        assert e.error == "denied"


class TestSnapshot:
    def test_creation_without_entries(self) -> None:
        s = Snapshot(id=1, timestamp=_dt.datetime.now(_dt.timezone.utc), root_path="/", label="")
        assert s.entries == []

    def test_creation_with_entries(self) -> None:
        entries = [DirEntry(path="/a", total_bytes=10, file_count=1, dir_count=0, depth=1)]
        s = Snapshot(id=None, timestamp=_dt.datetime.now(_dt.timezone.utc), root_path="/", label="test", entries=entries)
        assert len(s.entries) == 1


class TestDirDiff:
    def test_growth_calculation(self) -> None:
        d = DirDiff(
            path="/var/log",
            bytes_before=1000, bytes_after=5000,
            growth_bytes=4000, growth_pct=400.0,
            files_before=10, files_after=15, files_delta=5,
            depth=2,
        )
        assert d.growth_bytes == 4000
        assert d.growth_pct == 400.0


class TestSeverity:
    def test_values(self) -> None:
        assert Severity.CRITICAL.value == "critical"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"


class TestConfigs:
    def test_scan_defaults(self) -> None:
        cfg = ScanConfig()
        assert cfg.root == "/"
        assert cfg.follow_symlinks is False
        assert len(cfg.excludes) > 0

    def test_detect_defaults(self) -> None:
        cfg = DetectConfig()
        assert cfg.abs_threshold_bytes == 500 * 1024 * 1024
        assert cfg.stddev_factor == 2.0

    def test_watch_defaults(self) -> None:
        cfg = WatchConfig()
        assert cfg.interval_seconds == 600
        assert cfg.max_snapshots_kept == 144
