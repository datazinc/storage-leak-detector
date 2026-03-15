"""Tests for anomaly detection."""

from __future__ import annotations

import datetime as _dt

from sldd.detect import _attribute_growth, detect_anomalies
from sldd.diff import compute_diff
from sldd.models import (
    DetectConfig,
    DirDiff,
    DirEntry,
    Severity,
    SnapshotDiff,
)
from sldd.storage import SnapshotStore
from tests.conftest import make_snapshot


def _make_diff(store: SnapshotStore, old_entries: list[DirEntry], new_entries: list[DirEntry], hours: float = 1.0) -> SnapshotDiff:
    t1 = _dt.datetime(2024, 1, 1, 10, 0, 0, tzinfo=_dt.timezone.utc)
    t2 = t1 + _dt.timedelta(hours=hours)
    s1 = store.save_snapshot(make_snapshot(old_entries, timestamp=t1))
    s2 = store.save_snapshot(make_snapshot(new_entries, timestamp=t2))
    return compute_diff(store, s1, s2)


class TestAbsoluteThreshold:
    def test_triggers_on_large_growth(self, store: SnapshotStore) -> None:
        old = [DirEntry(path="/root", total_bytes=100_000_000, file_count=10, dir_count=0, depth=0)]
        new = [DirEntry(path="/root", total_bytes=700_000_000, file_count=15, dir_count=0, depth=0)]
        diff = _make_diff(store, old, new)

        cfg = DetectConfig(abs_threshold_bytes=500_000_000, min_size_bytes=0)
        anomalies = detect_anomalies(diff, store, cfg)

        abs_anomalies = [a for a in anomalies if a.rule == "abs_threshold"]
        assert len(abs_anomalies) >= 1
        assert abs_anomalies[0].severity in (Severity.WARNING, Severity.CRITICAL)

    def test_no_trigger_below_threshold(self, store: SnapshotStore) -> None:
        old = [DirEntry(path="/root", total_bytes=100, file_count=1, dir_count=0, depth=0)]
        new = [DirEntry(path="/root", total_bytes=200, file_count=2, dir_count=0, depth=0)]
        diff = _make_diff(store, old, new)

        cfg = DetectConfig(abs_threshold_bytes=500_000_000, min_size_bytes=0)
        anomalies = detect_anomalies(diff, store, cfg)

        abs_anomalies = [a for a in anomalies if a.rule == "abs_threshold"]
        assert len(abs_anomalies) == 0


class TestGrowthRate:
    def test_triggers_on_high_rate(self, store: SnapshotStore) -> None:
        old = [DirEntry(path="/root", total_bytes=0, file_count=0, dir_count=0, depth=0)]
        new = [DirEntry(path="/root", total_bytes=500_000_000, file_count=100, dir_count=0, depth=0)]
        diff = _make_diff(store, old, new, hours=1.0)

        cfg = DetectConfig(
            growth_rate_threshold_bytes_per_hour=200_000_000,
            abs_threshold_bytes=10**18,  # disable abs
            min_size_bytes=0,
        )
        anomalies = detect_anomalies(diff, store, cfg)

        rate_anomalies = [a for a in anomalies if a.rule == "growth_rate"]
        assert len(rate_anomalies) >= 1

    def test_rate_scales_with_time(self, store: SnapshotStore) -> None:
        """Growth of 500MB over 10 hours = 50MB/h, below 200MB/h threshold."""
        old = [DirEntry(path="/root", total_bytes=0, file_count=0, dir_count=0, depth=0)]
        new = [DirEntry(path="/root", total_bytes=500_000_000, file_count=100, dir_count=0, depth=0)]
        diff = _make_diff(store, old, new, hours=10.0)

        cfg = DetectConfig(
            growth_rate_threshold_bytes_per_hour=200_000_000,
            abs_threshold_bytes=10**18,
            min_size_bytes=0,
        )
        anomalies = detect_anomalies(diff, store, cfg)

        rate_anomalies = [a for a in anomalies if a.rule == "growth_rate"]
        assert len(rate_anomalies) == 0


class TestRelativeGrowth:
    def test_triggers_on_doubling(self, store: SnapshotStore) -> None:
        old = [DirEntry(path="/root", total_bytes=100_000_000, file_count=5, dir_count=0, depth=0)]
        new = [DirEntry(path="/root", total_bytes=250_000_000, file_count=10, dir_count=0, depth=0)]
        diff = _make_diff(store, old, new)

        cfg = DetectConfig(
            relative_threshold_pct=100.0,
            abs_threshold_bytes=10**18,
            growth_rate_threshold_bytes_per_hour=10**18,
            min_size_bytes=0,
        )
        anomalies = detect_anomalies(diff, store, cfg)

        rel_anomalies = [a for a in anomalies if a.rule == "relative_growth"]
        assert len(rel_anomalies) >= 1


class TestAttribution:
    def test_drills_down_to_child(self) -> None:
        entries = [
            DirDiff(path="/root", bytes_before=100, bytes_after=1100, growth_bytes=1000, growth_pct=1000, files_before=0, files_after=0, files_delta=0, depth=0),
            DirDiff(path="/root/logs", bytes_before=50, bytes_after=1000, growth_bytes=950, growth_pct=1900, files_before=0, files_after=0, files_delta=0, depth=1),
            DirDiff(path="/root/data", bytes_before=50, bytes_after=100, growth_bytes=50, growth_pct=100, files_before=0, files_after=0, files_delta=0, depth=1),
        ]
        diff = SnapshotDiff(
            snapshot_old=make_snapshot([]),
            snapshot_new=make_snapshot([]),
            elapsed_seconds=3600,
            entries=entries,
            total_growth_bytes=1000,
        )

        attributed = _attribute_growth(diff, entries[0])
        assert attributed == "/root/logs"

    def test_no_drill_when_spread(self) -> None:
        entries = [
            DirDiff(path="/root", bytes_before=0, bytes_after=1000, growth_bytes=1000, growth_pct=100, files_before=0, files_after=0, files_delta=0, depth=0),
            DirDiff(path="/root/a", bytes_before=0, bytes_after=500, growth_bytes=500, growth_pct=100, files_before=0, files_after=0, files_delta=0, depth=1),
            DirDiff(path="/root/b", bytes_before=0, bytes_after=500, growth_bytes=500, growth_pct=100, files_before=0, files_after=0, files_delta=0, depth=1),
        ]
        diff = SnapshotDiff(
            snapshot_old=make_snapshot([]),
            snapshot_new=make_snapshot([]),
            elapsed_seconds=3600,
            entries=entries,
            total_growth_bytes=1000,
        )

        attributed = _attribute_growth(diff, entries[0])
        assert attributed == "/root"  # can't attribute to one child


class TestStatisticalDetection:
    def test_triggers_on_spike(self, store: SnapshotStore) -> None:
        """Build history of steady growth, then spike."""
        base_time = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc)

        # 6 snapshots with steady ~10 byte growth
        for i in range(6):
            snap = make_snapshot(
                [DirEntry(path="/root", total_bytes=1000 + i * 10, file_count=1, dir_count=0, depth=0)],
                timestamp=base_time + _dt.timedelta(hours=i),
            )
            store.save_snapshot(snap)

        # 7th snapshot with massive spike
        old_entries = [DirEntry(path="/root", total_bytes=1050, file_count=1, dir_count=0, depth=0)]
        new_entries = [DirEntry(path="/root", total_bytes=2000, file_count=50, dir_count=0, depth=0)]
        diff = _make_diff(store, old_entries, new_entries)

        cfg = DetectConfig(
            min_snapshots_for_stats=4,
            stddev_factor=2.0,
            abs_threshold_bytes=10**18,
            growth_rate_threshold_bytes_per_hour=10**18,
            relative_threshold_pct=10000,
            min_size_bytes=0,
        )
        anomalies = detect_anomalies(diff, store, cfg)

        stat_anomalies = [a for a in anomalies if a.rule == "statistical"]
        assert len(stat_anomalies) >= 1
