"""Filesystem snapshot engine — walks a directory tree and aggregates sizes."""

from __future__ import annotations

import datetime as _dt
import os
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from sldd.models import DirEntry, ScanConfig, Snapshot
from sldd.platform_utils import is_excluded, is_same_device, normalize_path, safe_scandir

ProgressCallback = Callable[[str, int], None]  # (current_path, dirs_scanned)
StopCheck = Callable[[], bool]  # returns True if scan should stop


class ScanStoppedError(Exception):
    """Raised when a scan is stopped via stop_check."""


def take_snapshot(
    config: ScanConfig,
    *,
    progress: ProgressCallback | None = None,
    stop_check: StopCheck | None = None,
    label: str | None = None,
    previous_entries: dict[str, DirEntry] | None = None,
) -> Snapshot:
    """Walk *config.root* and return a Snapshot with aggregated dir entries.

    If *previous_entries* is provided and *config.skip_unchanged_minutes* is set,
    directories whose mtime hasn't changed within the threshold are reused from
    the previous snapshot without recursing into them.
    """
    root = os.path.realpath(config.root)
    excludes = set(config.excludes)
    follow = config.follow_symlinks
    cross = config.cross_devices
    max_depth = config.max_depth
    skip_minutes = config.skip_unchanged_minutes

    dir_bytes: dict[str, int] = defaultdict(int)
    dir_files: dict[str, int] = defaultdict(int)
    dir_dirs: dict[str, int] = defaultdict(int)
    dir_errors: dict[str, str] = {}
    scanned = 0

    now = time.time()
    skip_threshold = skip_minutes * 60 if skip_minutes else None

    stack: list[tuple[str, int]] = [(root, 0)]

    while stack:
        if stop_check and stop_check():
            raise ScanStoppedError()
        dirpath, depth = stack.pop()
        norm = normalize_path(dirpath)

        if is_excluded(norm, excludes):
            continue
        if not cross and not is_same_device(dirpath, root):
            continue
        if max_depth is not None and depth > max_depth:
            continue

        if _try_reuse(norm, dirpath, now, skip_threshold, previous_entries,
                      dir_bytes, dir_files, dir_dirs, root):
            scanned += 1
            continue

        scanned += 1
        if progress and scanned % 200 == 0:
            progress(norm, scanned)
        if stop_check and stop_check():
            raise ScanStoppedError()

        children = safe_scandir(dirpath)
        if not children and scanned > 1:
            try:
                os.listdir(dirpath)
            except PermissionError:
                dir_errors[norm] = "permission denied"
            except OSError as exc:
                dir_errors[norm] = str(exc)

        local_bytes = 0
        local_files = 0
        local_dirs = 0

        for entry in children:
            try:
                if entry.is_symlink() and not follow:
                    continue
                if entry.is_file(follow_symlinks=follow):
                    try:
                        size = entry.stat(follow_symlinks=follow).st_size
                    except OSError:
                        size = 0
                    local_bytes += size
                    local_files += 1
                elif entry.is_dir(follow_symlinks=follow):
                    local_dirs += 1
                    child_path = entry.path
                    stack.append((child_path, depth + 1))
            except OSError:
                continue

        dir_bytes[norm] += local_bytes
        dir_files[norm] += local_files
        dir_dirs[norm] += local_dirs

        _propagate_up(norm, root, local_bytes, local_files, dir_bytes, dir_files)

    norm_root = normalize_path(root)
    child_prefix = norm_root if norm_root.endswith("/") else norm_root + "/"
    entries = [
        DirEntry(
            path=p,
            total_bytes=dir_bytes[p],
            file_count=dir_files[p],
            dir_count=dir_dirs.get(p, 0),
            depth=_depth(p, root),
            error=dir_errors.get(p),
        )
        for p in sorted(dir_bytes)
        if p == norm_root or p.startswith(child_prefix)
    ]

    return Snapshot(
        id=None,
        timestamp=_dt.datetime.now(_dt.timezone.utc),
        root_path=normalize_path(root),
        label=label or config.label,
        entries=entries,
        scan_depth=config.max_depth,
    )


def _try_reuse(
    norm: str,
    dirpath: str,
    now: float,
    skip_threshold: float | None,
    previous_entries: dict[str, DirEntry] | None,
    dir_bytes: dict[str, int],
    dir_files: dict[str, int],
    dir_dirs: dict[str, int],
    root: str,
) -> bool:
    """If the directory's mtime is old enough and we have previous data, reuse it."""
    if skip_threshold is None or previous_entries is None:
        return False
    if norm not in previous_entries:
        return False
    try:
        mtime = os.stat(dirpath, follow_symlinks=False).st_mtime
    except OSError:
        return False
    if (now - mtime) < skip_threshold:
        return False

    prev = previous_entries[norm]
    dir_bytes[norm] += prev.total_bytes
    dir_files[norm] += prev.file_count
    dir_dirs[norm] += prev.dir_count
    _propagate_up(norm, root, prev.total_bytes, prev.file_count, dir_bytes, dir_files)
    return True


def _propagate_up(
    path: str,
    root: str,
    size: int,
    files: int,
    dir_bytes: dict[str, int],
    dir_files: dict[str, int],
) -> None:
    """Propagate byte/file counts from *path* up to *root* (exclusive of *path* itself).

    Only creates entries for directories at or below *root*.
    """
    norm_root = normalize_path(root)
    current = path
    while True:
        parent = normalize_path(str(Path(current).parent))
        if parent == current:
            break
        if not parent.startswith(norm_root) and parent != norm_root:
            break
        dir_bytes[parent] += size
        dir_files[parent] += files
        if parent == norm_root:
            break
        current = parent


def _depth(path: str, root: str) -> int:
    norm_root = normalize_path(root)
    norm_path = normalize_path(path)
    if norm_path == norm_root:
        return 0
    rel = norm_path[len(norm_root):]
    return rel.strip("/").count("/") + 1
