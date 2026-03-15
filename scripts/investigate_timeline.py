#!/usr/bin/env python3
"""Investigate Disk Usage Over Time data for a path.

Queries the snapshot DB to show:
- All snapshots with root_path (to spot mixed/non-full scans)
- Path history for the given path (what the chart uses)
- Entries for that path across snapshots (including missing = would show as gap/zero)

Usage:
  python -m scripts.investigate_timeline [--db snapshots.db] [--path /]
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Investigate timeline data for Disk Usage Over Time chart")
    ap.add_argument("--db", default="snapshots.db", help="Database path")
    ap.add_argument("--path", default="/", help="Path to investigate (e.g. / or /Users/arsene)")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"Database not found: {db}")
        return

    path = args.path.rstrip("/") or "/"
    if path != "/" and not path.startswith("/"):
        path = "/" + path

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    print("=" * 70)
    print("1. ALL SNAPSHOTS (id, timestamp, root_path)")
    print("   Mixed root_path = non-full scans; chart uses path from latest snapshot")
    print("=" * 70)
    rows = conn.execute(
        "SELECT id, timestamp, root_path FROM snapshots ORDER BY timestamp ASC"
    ).fetchall()
    if not rows:
        print("  (no snapshots)")
    else:
        for r in rows:
            print(f"  #{r['id']:4}  {r['timestamp']}  root_path={r['root_path']!r}")

    print()
    print("=" * 70)
    print(f"2. PATH HISTORY for path={path!r} (what get_path_history returns)")
    print("   This is the EXACT data used by the Disk Usage Over Time chart")
    print("=" * 70)
    hist = conn.execute(
        """
        SELECT s.id, s.timestamp, s.root_path, e.total_bytes, e.file_count
        FROM entries e
        JOIN snapshots s ON s.id = e.snapshot_id
        WHERE e.path = ?
        ORDER BY s.timestamp ASC
        LIMIT 200
        """,
        (path,),
    ).fetchall()
    if not hist:
        print(f"  (no entries for path {path!r})")
        print("  -> Chart would be empty. Path may not exist in any snapshot.")
    else:
        prev_bytes = None
        for r in hist:
            delta = ""
            if prev_bytes is not None:
                d = r["total_bytes"] - prev_bytes
                delta = f"  (Δ {d:+,})"
            prev_bytes = r["total_bytes"]
            zero_flag = "  <<< ZERO" if r["total_bytes"] == 0 else ""
            print(f"  #{r['id']:4}  {r['timestamp']}  {r['total_bytes']:>12,} B  root={r['root_path']!r}{delta}{zero_flag}")

    print()
    print("=" * 70)
    print("3. SNAPSHOTS MISSING ENTRY for this path")
    print("   (scoped/non-full scans that didn't capture this path)")
    print("=" * 70)
    all_snap_ids = {r["id"] for r in rows}
    hist_snap_ids = {r["id"] for r in hist}
    missing = sorted(all_snap_ids - hist_snap_ids)
    if not missing:
        print("  (none - all snapshots have data for this path)")
    else:
        for sid in missing:
            r = conn.execute(
                "SELECT id, timestamp, root_path FROM snapshots WHERE id = ?",
                (sid,),
            ).fetchone()
            print(f"  #{r['id']:4}  {r['timestamp']}  root_path={r['root_path']!r}  <- no entry for {path!r}")

    print()
    print("=" * 70)
    print("4. SCAN_DEPTH per snapshot (depth-limited vs full)")
    print("=" * 70)
    depth_rows = conn.execute(
        "SELECT id, timestamp, root_path, scan_depth FROM snapshots ORDER BY id"
    ).fetchall()
    for r in depth_rows:
        d = r["scan_depth"] if r["scan_depth"] is not None else "NULL (full)"
        print(f"  #{r['id']:4}  scan_depth={d}  root={r['root_path']!r}")

    print()
    print("=" * 70)
    print("5. DIAGNOSIS")
    print("=" * 70)
    if not hist:
        print("  Chart is empty: no snapshot has an entry for this path.")
    elif any(r["total_bytes"] == 0 for r in hist):
        zeros = [r for r in hist if r["total_bytes"] == 0]
        print(f"  Found {len(zeros)} data point(s) with total_bytes=0 (causes drop to zero on chart)")
        for r in zeros:
            print(f"    Snapshot #{r['id']} at {r['timestamp']} (root_path={r['root_path']!r})")
    elif missing:
        print(f"  {len(missing)} snapshot(s) have NO entry for this path (different root_path).")
        print("  get_path_history EXCLUDES these - chart should NOT show zeros for them.")
        print("  If chart shows zeros, the frontend may be building timeline differently.")
    else:
        # Check for mixed scan_depth
        depths = {}
        for r in conn.execute("SELECT id, scan_depth FROM snapshots").fetchall():
            d = r["scan_depth"] if r["scan_depth"] is not None else "NULL"
            depths[r["id"]] = d
        unique_depths = set(depths.values())
        if len(unique_depths) > 1:
            print("  MIXED scan_depth: some snapshots are depth-limited, others full.")
            print("  Depth-limited scans show much smaller totals for root path.")
            print("  Fix: pass scan_depth to path_history to filter to comparable snapshots.")
        else:
            print("  All snapshots have data for this path. No obvious cause for zeros.")

    conn.close()


if __name__ == "__main__":
    main()
