"""Diff engine — compare two snapshots and rank directory growth."""

from __future__ import annotations

from sldd.models import DirDiff, Snapshot, SnapshotDiff
from sldd.storage import SnapshotStore


def _scan_depths_compatible(old_snap: Snapshot, new_snap: Snapshot) -> bool:
    """Only compare snapshots with the same scan depth; otherwise growth is meaningless."""
    a, b = old_snap.scan_depth, new_snap.scan_depth
    if a is None and b is None:
        return True  # legacy, allow
    if a is None or b is None:
        return False  # one legacy, one new — skip
    return a == b


def compute_diff(
    store: SnapshotStore,
    old_snap: Snapshot,
    new_snap: Snapshot,
    *,
    limit: int = 500,
    min_growth_bytes: int = 0,
    path_prefix: str | None = None,
) -> SnapshotDiff | None:
    """Compute a diff between two snapshots using the storage layer for efficiency.
    Returns None if scan depths differ (incomparable).
    """
    assert old_snap.id is not None and new_snap.id is not None

    if not _scan_depths_compatible(old_snap, new_snap):
        return None

    elapsed = (new_snap.timestamp - old_snap.timestamp).total_seconds()
    if elapsed <= 0:
        elapsed = 1.0

    raw = store.diff_entries_raw(
        old_snap.id,
        new_snap.id,
        limit=limit,
        min_growth=min_growth_bytes,
        path_prefix=path_prefix,
    )

    entries: list[DirDiff] = []
    total_growth = 0

    for path, old_bytes, new_bytes, growth, old_files, new_files, depth in raw:
        if depth == 0:
            total_growth = growth
        pct = (growth / old_bytes * 100) if old_bytes > 0 else (100.0 if growth > 0 else 0.0)
        entries.append(DirDiff(
            path=path,
            bytes_before=old_bytes,
            bytes_after=new_bytes,
            growth_bytes=growth,
            growth_pct=pct,
            files_before=old_files,
            files_after=new_files,
            files_delta=new_files - old_files,
            depth=depth,
        ))

    if not total_growth and entries:
        total_growth = entries[0].growth_bytes

    return SnapshotDiff(
        snapshot_old=old_snap,
        snapshot_new=new_snap,
        elapsed_seconds=elapsed,
        entries=entries,
        total_growth_bytes=total_growth,
    )


def compute_diff_from_ids(
    store: SnapshotStore,
    old_id: int,
    new_id: int,
    *,
    limit: int = 500,
    min_growth_bytes: int = 0,
    path_prefix: str | None = None,
) -> SnapshotDiff | None:
    """Convenience: load snapshots by id and diff them."""
    old_snap = store.get_snapshot(old_id)
    new_snap = store.get_snapshot(new_id)
    if old_snap is None or new_snap is None:
        return None
    return compute_diff(
        store,
        old_snap,
        new_snap,
        limit=limit,
        min_growth_bytes=min_growth_bytes,
        path_prefix=path_prefix,
    )


def compute_latest_diff(
    store: SnapshotStore,
    *,
    limit: int = 500,
    min_growth_bytes: int = 0,
) -> SnapshotDiff | None:
    """Diff the two most recent snapshots."""
    snaps = store.list_snapshots(limit=2)
    if len(snaps) < 2:
        return None
    new_snap, old_snap = snaps[0], snaps[1]
    return compute_diff(store, old_snap, new_snap, limit=limit, min_growth_bytes=min_growth_bytes)
