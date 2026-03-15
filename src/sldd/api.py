"""Public API facade — single entry point for any UI, CLI, or web backend.

Every operation is a method on the SLDD class. A web server, Electron app,
or TUI can instantiate SLDD and call its methods directly.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sldd.adaptive import (
    adaptive_cycle,
    compact,
    get_adaptive_stats,
    plan_scan,
)
from sldd.delete import execute_delete, preview_delete
from sldd.detect import detect_anomalies
from sldd.diff import compute_diff_from_ids, compute_latest_diff
from dataclasses import replace

from sldd.models import (
    AdaptiveConfig,
    Anomaly,
    CompactResult,
    DeletePreview,
    DeleteResult,
    DetectConfig,
    DirDiff,
    DirEntry,
    PlaybackFrame,
    Report,
    ScanConfig,
    ScanPlan,
    Snapshot,
    SnapshotDiff,
)
from sldd.playback import build_frames, build_path_timeline
from sldd.report import print_report, report_to_dict, report_to_json
from sldd.process_io import get_processes_with_path_open, sample_path_io
from sldd.snapshot import ProgressCallback, take_snapshot
from sldd.storage import SnapshotStore


def _select_actionable_growers(
    entries: Sequence[DirDiff], top_n: int,
) -> list[DirDiff]:
    """Pick the most actionable growers: deepest directories that own the growth.

    Parent directories aggregate their children's sizes, so showing "/" at +500 MB
    alongside "/var/log" at +500 MB is redundant. This function walks each parent's
    children — if a single child accounts for >=80% of the parent's growth, the
    parent is dropped in favor of the child. The result is a de-duplicated list
    of the deepest directories that actually explain the growth.
    """
    if not entries:
        return []

    growing = [e for e in entries if e.growth_bytes > 0]
    growing.sort(key=lambda e: e.growth_bytes, reverse=True)

    redundant: set[str] = set()
    for entry in growing:
        if entry.path in redundant:
            continue
        prefix = entry.path.rstrip("/") + "/"
        children = [
            e for e in growing
            if e.path.startswith(prefix)
            and e.depth == entry.depth + 1
            and e.growth_bytes > 0
        ]
        if not children or entry.growth_bytes <= 0:
            continue
        top_child = max(children, key=lambda c: c.growth_bytes)
        share = top_child.growth_bytes / entry.growth_bytes
        if share >= 0.80:
            redundant.add(entry.path)

    result = [e for e in growing if e.path not in redundant]
    return result[:top_n]


def _select_actionable_shrinkers(
    entries: Sequence[DirDiff], top_n: int,
) -> list[DirDiff]:
    """Pick the most actionable shrinkers (negative growth), mirroring growers logic."""
    if not entries:
        return []

    shrinking = [e for e in entries if e.growth_bytes < 0]
    shrinking.sort(key=lambda e: e.growth_bytes)  # most negative first

    redundant: set[str] = set()
    for entry in shrinking:
        if entry.path in redundant:
            continue
        prefix = entry.path.rstrip("/") + "/"
        children = [
            e for e in shrinking
            if e.path.startswith(prefix)
            and e.depth == entry.depth + 1
            and e.growth_bytes < 0
        ]
        if not children or entry.growth_bytes >= 0:
            continue
        top_child = min(children, key=lambda c: c.growth_bytes)
        share = top_child.growth_bytes / entry.growth_bytes
        if share >= 0.80:
            redundant.add(entry.path)

    result = [e for e in shrinking if e.path not in redundant]
    return result[:top_n]


class SLDD:
    """High-level API for storage leak detection."""

    def __init__(
        self,
        db_path: str | Path = "snapshots.db",
        scan_config: ScanConfig | None = None,
        detect_config: DetectConfig | None = None,
        adaptive_config: AdaptiveConfig | None = None,
    ) -> None:
        self._store = SnapshotStore(db_path)
        self.scan_config = scan_config or ScanConfig()
        self.detect_config = detect_config or DetectConfig()
        self.adaptive_config = adaptive_config or AdaptiveConfig()

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        self._store.open()

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> SLDD:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def store(self) -> SnapshotStore:
        return self._store

    # -- snapshots -----------------------------------------------------------

    def take_snapshot(
        self,
        *,
        config: ScanConfig | None = None,
        progress: ProgressCallback | None = None,
        label: str = "",
    ) -> Snapshot:
        """Walk the filesystem and persist a new snapshot."""
        cfg = config or self.scan_config

        previous_entries: dict[str, DirEntry] | None = None
        if cfg.skip_unchanged_minutes is not None:
            latest = self._store.get_latest_snapshot(with_entries=True)
            if latest and latest.entries:
                previous_entries = {e.path: e for e in latest.entries}

        snap = take_snapshot(
            cfg, progress=progress, label=label,
            previous_entries=previous_entries,
        )
        return self._store.save_snapshot(snap)

    def list_snapshots(
        self, limit: int = 50, scan_depth: int | None = None,
    ) -> list[Snapshot]:
        return self._store.list_snapshots(limit=limit, scan_depth=scan_depth)

    def get_snapshot_depths(self) -> list[tuple[int, int]]:
        """Return (scan_depth, count) for each depth with snapshots."""
        return self._store.get_snapshot_depths()

    def get_snapshot(
        self, snapshot_id: int, *, with_entries: bool = False,
    ) -> Snapshot | None:
        return self._store.get_snapshot(
            snapshot_id, with_entries=with_entries,
        )

    def delete_snapshot(self, snapshot_id: int) -> None:
        self._store.delete_snapshot(snapshot_id)

    def prune(self, keep: int = 144) -> int:
        return self._store.prune_old_snapshots(keep)

    # -- diff ----------------------------------------------------------------

    def diff(
        self,
        old_id: int,
        new_id: int,
        *,
        limit: int = 500,
        min_growth_bytes: int = 0,
    ) -> SnapshotDiff | None:
        return compute_diff_from_ids(
            self._store, old_id, new_id,
            limit=limit, min_growth_bytes=min_growth_bytes,
        )

    def diff_latest(
        self, *, limit: int = 500, min_growth_bytes: int = 0,
    ) -> SnapshotDiff | None:
        return compute_latest_diff(
            self._store, limit=limit, min_growth_bytes=min_growth_bytes,
        )

    # -- detect --------------------------------------------------------------

    def detect(
        self,
        diff: SnapshotDiff,
        *,
        config: DetectConfig | None = None,
    ) -> list[Anomaly]:
        return detect_anomalies(
            diff, self._store, config or self.detect_config,
        )

    def diff_and_detect(
        self, old_id: int, new_id: int, *, top_n: int = 20,
    ) -> Report | None:
        d = self.diff(old_id, new_id)
        if d is None:
            return None
        anomalies = self.detect(d)
        top_growers = _select_actionable_growers(d.entries, top_n)
        top_shrinkers = _select_actionable_shrinkers(d.entries, top_n)
        return Report(
            generated_at=_dt.datetime.now(_dt.timezone.utc),
            diff=d, anomalies=anomalies, top_growers=top_growers,
            top_shrinkers=top_shrinkers,
        )

    def snapshot_and_detect(
        self, *, progress: ProgressCallback | None = None,
    ) -> Report | None:
        self.take_snapshot(progress=progress)
        snaps = self.list_snapshots(limit=2)
        if len(snaps) < 2:
            return None
        new, old = snaps[0], snaps[1]
        assert new.id is not None and old.id is not None
        return self.diff_and_detect(old.id, new.id)

    # -- drill down ----------------------------------------------------------

    def drill(self, snapshot_id: int, path: str) -> list[DirEntry]:
        entry = self._store.get_entry(snapshot_id, path)
        if entry is None:
            return []
        return self._store.get_children(snapshot_id, path, entry.depth)

    def path_history(
        self, path: str, limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = self._store.get_path_history(path, limit=limit)
        return [
            {
                "snapshot_id": r[0], "timestamp": r[1],
                "total_bytes": r[2], "file_count": r[3],
            }
            for r in rows
        ]

    def top_dirs(
        self, snapshot_id: int, limit: int = 20,
    ) -> list[DirEntry]:
        return self._store.get_top_dirs(snapshot_id, limit=limit)

    # -- playback ------------------------------------------------------------

    def playback_frames(
        self,
        from_id: int,
        to_id: int,
        *,
        top_n: int = 20,
        path_prefix: str | None = None,
    ) -> list[PlaybackFrame]:
        return build_frames(
            self._store,
            from_id,
            to_id,
            detect_config=self.detect_config,
            top_n=top_n,
            path_prefix=path_prefix,
        )

    def playback_path_timeline(
        self, path: str, from_id: int, to_id: int,
    ) -> list[dict[str, object]]:
        return build_path_timeline(self._store, path, from_id, to_id)

    # -- deletion ------------------------------------------------------------

    def delete_preview(
        self, paths: list[str], *, force: bool = False,
    ) -> DeletePreview:
        return preview_delete(
            paths, scan_root=self.scan_config.root, force=force,
        )

    def delete_execute(
        self, paths: list[str], *, dry_run: bool = False, force: bool = False,
    ) -> DeleteResult:
        return execute_delete(
            paths, self._store,
            scan_root=self.scan_config.root, dry_run=dry_run, force=force,
        )

    def deletion_history(self, limit: int = 100) -> list[dict[str, object]]:
        return self._store.get_deletion_history(limit=limit)

    # -- path I/O (process attribution) --------------------------------------

    def path_io_now(self, path: str) -> list[dict[str, Any]]:
        """On-demand: current processes with path open + I/O stats.
        Sorted by write_bytes descending (primary process first).
        """
        infos = get_processes_with_path_open(path)
        infos = sorted(infos, key=lambda p: p.write_bytes, reverse=True)
        return [
            {
                "pid": p.pid,
                "process_name": p.process_name,
                "read_bytes": p.read_bytes,
                "write_bytes": p.write_bytes,
                "open_files_under_path": p.open_files_under_path,
                "cmdline": p.cmdline,
                "username": p.username,
            }
            for p in infos
        ]

    def path_io_offenders(self, paths: list[str]) -> dict[str, dict[str, Any] | None]:
        """Top process (highest write_bytes) per path. For anomaly analysis."""
        result: dict[str, dict[str, Any] | None] = {}
        for path in paths:
            infos = get_processes_with_path_open(path)
            if not infos:
                result[path] = None
                continue
            top = max(infos, key=lambda p: p.write_bytes)
            result[path] = {
                "pid": top.pid,
                "process_name": top.process_name,
                "write_bytes": top.write_bytes,
                "cmdline": top.cmdline,
                "username": top.username,
            }
        return result

    def path_io_history(
        self, path: str, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Historic samples with deltas for charting (ordered oldest-first)."""
        rows = self._store.get_path_io_history(path, limit=limit)
        rows = list(reversed(rows))
        prev_by_pid: dict[tuple[int, str], tuple[int, int]] = {}
        result: list[dict[str, Any]] = []
        for ts, pid, name, r, w, of in rows:
            key = (pid, name)
            prev = prev_by_pid.get(key, (0, 0))
            r_delta = max(0, r - prev[0])
            w_delta = max(0, w - prev[1])
            prev_by_pid[key] = (r, w)
            result.append({
                "timestamp": ts,
                "pid": pid,
                "process_name": name,
                "read_bytes_delta": r_delta,
                "write_bytes_delta": w_delta,
            })
        return result

    def path_io_watch_start(
        self, path: str, duration_minutes: int, sample_interval_sec: int = 60,
    ) -> None:
        """Register path for I/O watching. Server watcher will pick it up."""
        self._store.path_io_watch_insert(path, duration_minutes, sample_interval_sec)

    def path_io_watch_stop(self, path: str) -> None:
        self._store.path_io_watch_delete(path)

    def path_io_watch_status(self) -> list[dict[str, Any]]:
        rows = self._store.path_io_watch_list()
        return [
            {
                "path": r[0],
                "started_at": r[1],
                "duration_minutes": r[2],
                "sample_interval_sec": r[3],
            }
            for r in rows
        ]

    def path_io_summary(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._store.get_path_io_summary(limit=limit)
        return [
            {"path": r[0], "last_timestamp": r[1], "sample_count": r[2]}
            for r in rows
        ]

    def path_io_store_samples(
        self, samples: list[tuple[str, int, str, int, int, int]],
    ) -> None:
        """Store samples from collector. Used by watcher and watch scan."""
        self._store.insert_path_io_samples(samples)

    # -- settings ------------------------------------------------------------

    def get_settings(self) -> dict[str, str]:
        return self._store.get_settings()

    def sync_scan_config_from_settings(self) -> None:
        """Update scan_config from stored settings. Call before scans to use UI-configured root."""
        settings = self.get_settings()
        root = (settings.get("scan.root") or "/").strip() or "/"
        excludes_str = settings.get("scan.excludes", "")
        excludes = [p.strip() for p in excludes_str.split(",") if p.strip()] if excludes_str else self.scan_config.excludes
        max_d = settings.get("scan.max_depth")
        max_depth = int(max_d) if max_d and str(max_d).strip().isdigit() else None
        self.scan_config = replace(
            self.scan_config,
            root=root,
            excludes=excludes if excludes else self.scan_config.excludes,
            max_depth=max_depth,
        )

    def effective_scan_root(self, override: str | None = None) -> str:
        """Return the root to use for scans: override > settings > scan_config."""
        if override and override.strip():
            return override.strip()
        settings = self.get_settings()
        root = (settings.get("scan.root") or "").strip()
        return root or self.scan_config.root

    def save_settings(self, settings: dict[str, str]) -> None:
        self._store.save_settings(settings)

    def get_db_info(self) -> dict[str, Any]:
        return {
            "path": self._store._db_path,
            "size_bytes": self._store.db_size_bytes(),
            "snapshot_count": self._store.snapshot_count(),
        }

    def vacuum_db(self) -> None:
        self._store.vacuum()

    def reset_db(self) -> None:
        """Drop all tables and recreate schema — complete data wipe."""
        self._store.reset()

    def recover_db(self) -> None:
        """Close store, delete corrupted DB files, reopen with fresh schema.
        Use when database disk image is malformed (corruption).
        """
        import os
        from sldd.storage import SnapshotStore

        check_same_thread = getattr(self._store, "_check_same_thread", True)
        self._store.close()
        db = os.path.realpath(self.scan_config.db_path)
        for path in (db, db + "-wal", db + "-shm", db + "-journal"):
            try:
                os.remove(path)
            except OSError:
                pass
        self._store = SnapshotStore(db, check_same_thread=check_same_thread)
        self._store.open()

    # -- adaptive scanning ---------------------------------------------------

    def adaptive_snapshot_and_detect(
        self,
        *,
        progress: ProgressCallback | None = None,
    ) -> tuple[Report | None, ScanPlan, CompactResult | None]:
        """Full adaptive cycle: plan → scan → diff → track → detect → compact."""
        effective_config, plan = plan_scan(
            self._store, self.adaptive_config, self.scan_config,
        )

        snap = take_snapshot(effective_config, progress=progress)
        snap = self._store.save_snapshot(snap)

        snaps = self.list_snapshots(limit=2)
        if len(snaps) < 2 or snaps[0].id is None or snaps[1].id is None:
            return None, plan, None

        new, old = snaps[0], snaps[1]
        diff, tracking, compact_result = adaptive_cycle(
            self._store, self.adaptive_config, old, new,
        )

        anomalies = self.detect(diff)
        top_growers = _select_actionable_growers(diff.entries, 20)
        top_shrinkers = _select_actionable_shrinkers(diff.entries, 20)
        report = Report(
            generated_at=_dt.datetime.now(_dt.timezone.utc),
            diff=diff, anomalies=anomalies, top_growers=top_growers,
            top_shrinkers=top_shrinkers,
        )
        return report, plan, compact_result

    def plan_next_scan(self) -> ScanPlan:
        _, plan = plan_scan(
            self._store, self.adaptive_config, self.scan_config,
        )
        return plan

    def run_compact(self) -> CompactResult:
        return compact(self._store, self.adaptive_config)

    def adaptive_stats(self) -> dict[str, object]:
        return get_adaptive_stats(self._store)

    def reset_adaptive(self) -> None:
        """Reset all adaptive tracking state."""
        self._store.clear_path_statuses()
        self._store.set_scan_number(0)

    # -- reporting -----------------------------------------------------------

    def report_dict(self, report: Report) -> dict[str, Any]:
        return report_to_dict(report)

    def report_json(self, report: Report) -> str:
        return report_to_json(report)

    def print_report(self, report: Report) -> None:
        print_report(report)
