"""Playback engine — builds animation frames from consecutive snapshot diffs."""

from __future__ import annotations

from sldd.detect import detect_anomalies
from sldd.diff import compute_diff
from sldd.models import (
    DetectConfig,
    PlaybackFrame,
)
from sldd.storage import SnapshotStore


def build_frames(
    store: SnapshotStore,
    from_id: int,
    to_id: int,
    *,
    detect_config: DetectConfig | None = None,
    top_n: int = 20,
    path_prefix: str | None = None,
) -> list[PlaybackFrame]:
    """Build an ordered list of PlaybackFrames for the snapshot range [from_id, to_id].

    Each frame represents the diff between two consecutive snapshots.
    """
    snaps = store.list_snapshots(limit=10000)
    snaps.sort(key=lambda s: (s.timestamp, s.id or 0))

    in_range = [
        s for s in snaps
        if s.id is not None and from_id <= s.id <= to_id
    ]

    if len(in_range) < 2:
        return []

    cfg = detect_config or DetectConfig()
    start_time = in_range[0].timestamp
    frames: list[PlaybackFrame] = []

    for i in range(1, len(in_range)):
        old_snap = in_range[i - 1]
        new_snap = in_range[i]
        assert old_snap.id is not None and new_snap.id is not None

        diff = compute_diff(
            store, old_snap, new_snap, path_prefix=path_prefix,
        )
        if diff is None:
            continue  # incompatible scan depths, skip this frame
        anomalies = detect_anomalies(diff, store, cfg)
        top = sorted(
            diff.entries, key=lambda e: e.growth_bytes, reverse=True,
        )[:top_n]

        if path_prefix:
            prefix = path_prefix.rstrip("/") or "/"
            root_entry = store.get_entry(new_snap.id, prefix)
        else:
            root_entry = store.get_entry(new_snap.id, new_snap.root_path)
        # Skip frame when path is out of scope (scoped watch didn't capture this path)
        if root_entry is None:
            continue  # don't show as zero — skip data point

        total_bytes = root_entry.total_bytes
        elapsed = (new_snap.timestamp - start_time).total_seconds()

        frames.append(PlaybackFrame(
            frame_index=len(frames),
            snapshot_id=new_snap.id,
            timestamp=new_snap.timestamp,
            elapsed_since_start_seconds=elapsed,
            top_growers=top,
            anomalies=anomalies,
            total_bytes=total_bytes,
            total_growth_bytes=diff.total_growth_bytes,
        ))

    return frames


def build_path_timeline(
    store: SnapshotStore,
    path: str,
    from_id: int,
    to_id: int,
) -> list[dict[str, object]]:
    """Return time-series data for a single path across a snapshot range."""
    history = store.get_path_history(path, limit=10000)
    history.sort(key=lambda r: r[1])

    return [
        {
            "snapshot_id": r[0],
            "timestamp": r[1],
            "total_bytes": r[2],
            "file_count": r[3],
        }
        for r in history
        if from_id <= r[0] <= to_id
    ]
