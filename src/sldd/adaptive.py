"""Adaptive scan engine — start shallow, focus on what changes, discard the rest.

Modes:
  auto     Smart default. Shallow discovery → focus on growers → compact stable.
  full     Always scan at max depth (legacy behavior).
  disabled Skip adaptive logic entirely, use raw ScanConfig as-is.

Lifecycle per scan cycle:
  1. plan_scan()       → decide depth, focus paths, skip paths
  2. (caller runs snapshot with the plan)
  3. update_tracking() → analyze diff, update path_status table
  4. compact()         → collapse stable subtrees, prune old snapshots
"""

from __future__ import annotations

import logging
from dataclasses import replace

from sldd.diff import compute_diff
from sldd.models import (
    AdaptiveConfig,
    CompactResult,
    ScanConfig,
    ScanPlan,
    Snapshot,
    SnapshotDiff,
)
from sldd.storage import SnapshotStore

_log = logging.getLogger("sldd.adaptive")


def plan_scan(
    store: SnapshotStore,
    config: AdaptiveConfig,
    scan_config: ScanConfig,
) -> tuple[ScanConfig, ScanPlan]:
    """Decide what to scan based on path tracking history.

    Returns a modified ScanConfig and a ScanPlan describing the strategy.
    """
    if config.mode == "disabled":
        return scan_config, ScanPlan(
            strategy="full",
            scan_depth=scan_config.max_depth,
            focus_paths=[],
            skip_paths=[],
            scan_number=store.get_scan_number(),
            reason="adaptive disabled",
        )

    scan_num = store.get_scan_number()
    is_discovery = (
        scan_num == 0
        or scan_num % config.rediscovery_every == 0
        or config.mode == "full"
    )

    if is_discovery:
        depth = config.initial_depth if config.mode == "auto" else (
            scan_config.max_depth
            if scan_config.max_depth is not None
            else config.initial_depth
        )
        return (
            replace(scan_config, max_depth=depth),
            ScanPlan(
                strategy="discovery",
                scan_depth=depth,
                focus_paths=[],
                skip_paths=[],
                scan_number=scan_num,
                reason=f"discovery scan #{scan_num} at depth {depth}",
            ),
        )

    focus_rows = store.get_path_statuses(status="focus")
    stable_rows = store.get_path_statuses(status="stable")

    focus_paths = [r["path"] for r in focus_rows]
    skip_paths = [r["path"] for r in stable_rows]

    excludes = list(scan_config.excludes) + [
        p for p in skip_paths if p not in scan_config.excludes
    ]

    depth = config.focus_depth

    if not focus_paths:
        depth = config.initial_depth
        reason = f"no focus paths yet, scanning at depth {depth}"
        excludes = list(scan_config.excludes)
    else:
        reason = (
            f"focused scan: {len(focus_paths)} focus paths, "
            f"skipping {len(skip_paths)} stable"
        )

    return (
        replace(scan_config, max_depth=depth, excludes=excludes),
        ScanPlan(
            strategy="focused",
            scan_depth=depth,
            focus_paths=focus_paths,
            skip_paths=skip_paths,
            scan_number=scan_num,
            reason=reason,
        ),
    )


def update_tracking(
    store: SnapshotStore,
    config: AdaptiveConfig,
    diff: SnapshotDiff,
) -> dict[str, int]:
    """After a diff, update path_status: promote growers to focus, increment stable counts.

    Returns summary counts: {"promoted": N, "stabilized": N, "unchanged": N}.
    """
    if config.mode == "disabled":
        return {"promoted": 0, "stabilized": 0, "unchanged": 0}

    existing: dict[str, dict[str, object]] = {}
    for row in store.get_path_statuses():
        existing[str(row["path"])] = row

    updates: list[tuple[str, str, int, int, int, int, int]] = []
    promoted = 0
    stabilized = 0
    unchanged = 0

    for entry in diff.entries:
        prev = existing.get(entry.path)
        prev_consec = int(prev["consecutive_stable"]) if prev else 0

        if entry.growth_bytes > 0:
            updates.append((
                entry.path, "focus",
                entry.bytes_after, entry.files_after, entry.depth,
                0, entry.growth_bytes,
            ))
            promoted += 1
        elif entry.growth_bytes == 0:
            new_consec = prev_consec + 1
            if new_consec >= config.stability_scans:
                updates.append((
                    entry.path, "stable",
                    entry.bytes_after, entry.files_after, entry.depth,
                    new_consec, 0,
                ))
                stabilized += 1
            else:
                updates.append((
                    entry.path, "active",
                    entry.bytes_after, entry.files_after, entry.depth,
                    new_consec, 0,
                ))
                unchanged += 1
        else:
            updates.append((
                entry.path, "focus",
                entry.bytes_after, entry.files_after, entry.depth,
                0, entry.growth_bytes,
            ))
            promoted += 1

    if updates:
        store.bulk_upsert_path_status(updates)

    store.set_scan_number(store.get_scan_number() + 1)

    _log.info(
        "Tracking updated: %d promoted, %d stabilized, %d unchanged",
        promoted, stabilized, unchanged,
    )
    return {"promoted": promoted, "stabilized": stabilized, "unchanged": unchanged}


def compact(
    store: SnapshotStore,
    config: AdaptiveConfig,
) -> CompactResult:
    """Run compaction: collapse stable subtrees and prune old snapshots.

    This is the key storage saver. For every path marked "stable", we delete
    all its deeper child entries from the DB. The parent aggregate row stays,
    so diffs still work at that level — we just lose the ability to drill into
    the subtree of a path we've confirmed doesn't change.
    """
    if config.mode == "disabled" or not config.auto_compact:
        return CompactResult(
            entries_removed=0, bytes_saved_estimate=0,
            paths_collapsed=0, snapshots_pruned=0,
        )

    stable = store.get_path_statuses(status="stable")
    stable_paths = [str(r["path"]) for r in stable]

    entries_before = store.total_entry_count()
    if stable_paths:
        store.collapse_stable_children(stable_paths)

    baseline_id = store.get_baseline_snapshot_id()
    pruned = store.smart_retain(config.retain_snapshots, baseline_id)

    entries_after = store.total_entry_count()
    removed = entries_before - entries_after
    est_saved = removed * 300

    if removed > 0:
        try:
            store.vacuum()
        except Exception:
            _log.warning("Vacuum failed (non-fatal)")

    _log.info(
        "Compaction: %d entries removed (~%d MB saved), "
        "%d subtrees collapsed, %d snapshots pruned",
        removed, est_saved // (1024 * 1024), len(stable_paths), pruned,
    )
    return CompactResult(
        entries_removed=removed,
        bytes_saved_estimate=est_saved,
        paths_collapsed=len(stable_paths),
        snapshots_pruned=pruned,
    )


def ensure_baseline(store: SnapshotStore, snap: Snapshot) -> None:
    """In smart mode, ensure we always have a baseline snapshot.

    The baseline is the anchor — the first snapshot, or the last snapshot before
    diffs were detected. We never delete it during compaction.
    """
    if store.get_baseline_snapshot_id() is None and snap.id is not None:
        store.set_baseline_snapshot_id(snap.id)
        _log.info("Baseline set to snapshot #%d", snap.id)


def smart_baseline_update(
    store: SnapshotStore,
    diff: SnapshotDiff,
) -> None:
    """If no growth detected, update baseline to latest (quiet mode).

    This ensures we don't accumulate snapshots during quiet periods.
    """
    if diff.total_growth_bytes == 0 and diff.snapshot_new.id is not None:
        store.set_baseline_snapshot_id(diff.snapshot_new.id)


def adaptive_cycle(
    store: SnapshotStore,
    adaptive_config: AdaptiveConfig,
    old_snap: Snapshot,
    new_snap: Snapshot,
) -> tuple[SnapshotDiff, dict[str, int], CompactResult]:
    """Full post-scan adaptive cycle: diff → track → compact.

    Call this after taking a new snapshot.
    Returns (diff, tracking_summary, compact_result).
    """
    diff = compute_diff(store, old_snap, new_snap)
    if diff is None:
        _log.info(
            "Skipping adaptive cycle: incompatible scan depths "
            "(old=%s, new=%s)",
            old_snap.scan_depth,
            new_snap.scan_depth,
        )
        return (
            SnapshotDiff(
                snapshot_old=old_snap,
                snapshot_new=new_snap,
                elapsed_seconds=0.0,
                entries=[],
                total_growth_bytes=0,
            ),
            {"promoted": 0, "stabilized": 0, "unchanged": 0},
            CompactResult(
                entries_removed=0, bytes_saved_estimate=0,
                paths_collapsed=0, snapshots_pruned=0,
            ),
        )

    ensure_baseline(store, old_snap)

    tracking = update_tracking(store, adaptive_config, diff)

    smart_baseline_update(store, diff)

    scan_num = store.get_scan_number()
    should_compact = (
        adaptive_config.auto_compact
        and scan_num > 1
        and scan_num % 3 == 0
    )
    compact_result = CompactResult(
        entries_removed=0, bytes_saved_estimate=0,
        paths_collapsed=0, snapshots_pruned=0,
    )
    if should_compact:
        compact_result = compact(store, adaptive_config)

    return diff, tracking, compact_result


def get_adaptive_stats(store: SnapshotStore) -> dict[str, object]:
    """Return a summary of adaptive scan state for the UI."""
    statuses = store.get_path_statuses()
    by_status: dict[str, int] = {"active": 0, "stable": 0, "focus": 0}
    for row in statuses:
        s = str(row["status"])
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "scan_number": store.get_scan_number(),
        "baseline_snapshot_id": store.get_baseline_snapshot_id(),
        "total_tracked_paths": len(statuses),
        "active_paths": by_status.get("active", 0),
        "stable_paths": by_status.get("stable", 0),
        "focus_paths": by_status.get("focus", 0),
        "total_entries": store.total_entry_count(),
    }
