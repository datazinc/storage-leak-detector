"""Domain models — pure data, no IO, easy to serialize for any UI."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DirEntry:
    """Aggregated stats for a single directory."""

    path: str
    total_bytes: int
    file_count: int
    dir_count: int
    depth: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    id: int | None
    timestamp: _dt.datetime
    root_path: str
    label: str
    entries: Sequence[DirEntry] = field(default_factory=list)
    scan_depth: int | None = None  # max_depth used; None = legacy/unknown


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DirDiff:
    """Change for a single directory between two snapshots."""

    path: str
    bytes_before: int
    bytes_after: int
    growth_bytes: int
    growth_pct: float
    files_before: int
    files_after: int
    files_delta: int
    depth: int


@dataclass(frozen=True, slots=True)
class SnapshotDiff:
    """Full diff between two snapshots."""

    snapshot_old: Snapshot
    snapshot_new: Snapshot
    elapsed_seconds: float
    entries: Sequence[DirDiff]
    total_growth_bytes: int


# ---------------------------------------------------------------------------
# Anomaly
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Anomaly:
    """A detected anomaly — something growing abnormally."""

    path: str
    severity: Severity
    rule: str
    message: str
    growth_bytes: int
    growth_rate_bytes_per_hour: float
    attributed_path: str  # deepest directory responsible
    sldd_db_bytes: int = 0  # when path contains sldd DB, bytes attributed to this tool


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Report:
    generated_at: _dt.datetime
    diff: SnapshotDiff
    anomalies: Sequence[Anomaly]
    top_growers: Sequence[DirDiff]
    top_shrinkers: Sequence[DirDiff] = ()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DetectConfig:
    abs_threshold_bytes: int = 500 * 1024 * 1024   # 500 MB
    growth_rate_threshold_bytes_per_hour: float = 200 * 1024 * 1024  # 200 MB/h
    relative_threshold_pct: float = 100.0  # doubled
    stddev_factor: float = 2.0
    min_snapshots_for_stats: int = 4
    min_size_bytes: int = 10 * 1024 * 1024  # ignore dirs < 10 MB
    attribution_concentration_pct: float = 80.0


@dataclass(slots=True)
class ScanConfig:
    root: str = "/"
    excludes: list[str] = field(default_factory=lambda: [
        "/proc", "/sys", "/dev", "/run",
        "/snap", "/System/Volumes/Data",
    ])
    max_depth: int | None = None
    follow_symlinks: bool = False
    cross_devices: bool = False
    db_path: str = "snapshots.db"
    label: str = ""
    skip_unchanged_minutes: int | None = None


@dataclass(slots=True)
class WatchConfig:
    scan: ScanConfig = field(default_factory=ScanConfig)
    detect: DetectConfig = field(default_factory=DetectConfig)
    interval_seconds: int = 600
    max_snapshots_kept: int = 144  # 24h at 10-min intervals


@dataclass(slots=True)
class AdaptiveConfig:
    """Configuration for adaptive scanning — start shallow, focus on what changes."""

    mode: str = "auto"
    initial_depth: int = 3
    focus_depth: int | None = None
    stability_scans: int = 3
    retain_snapshots: int = 5
    rediscovery_every: int = 10
    auto_compact: bool = True


class PathStatus(str, Enum):
    ACTIVE = "active"
    STABLE = "stable"
    FOCUS = "focus"


@dataclass(frozen=True, slots=True)
class TrackedPath:
    """Tracking state for a single directory path across scans."""

    path: str
    status: PathStatus
    last_bytes: int
    last_file_count: int
    depth: int
    consecutive_stable: int
    last_growth_bytes: int
    updated_at: _dt.datetime


@dataclass(frozen=True, slots=True)
class ScanPlan:
    """What the adaptive engine decided to scan."""

    strategy: str  # "discovery" | "focused" | "full"
    scan_depth: int | None
    focus_paths: Sequence[str]
    skip_paths: Sequence[str]
    scan_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class CompactResult:
    """Result of a compaction run."""

    entries_removed: int
    bytes_saved_estimate: int
    paths_collapsed: int
    snapshots_pruned: int


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DeleteTarget:
    path: str
    exists: bool
    is_dir: bool
    size_bytes: int
    file_count: int
    writable: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DeletePreview:
    targets: Sequence[DeleteTarget]
    total_bytes: int
    total_files: int
    all_writable: bool
    blocked_paths: Sequence[str]


@dataclass(frozen=True, slots=True)
class DeleteResult:
    succeeded: Sequence[str]
    failed: Sequence[tuple[str, str]]  # (path, error)
    bytes_freed: int
    dry_run: bool


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PlaybackFrame:
    frame_index: int
    snapshot_id: int
    timestamp: _dt.datetime
    elapsed_since_start_seconds: float
    top_growers: Sequence[DirDiff]
    anomalies: Sequence[Anomaly]
    total_bytes: int
    total_growth_bytes: int
