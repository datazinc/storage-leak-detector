"""Safe deletion service with preview, execute, audit, and blocklist."""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

from sldd.models import DeletePreview, DeleteResult, DeleteTarget
from sldd.storage import SnapshotStore

_BLOCKLIST: set[str] = {
    "/", "/bin", "/sbin", "/usr", "/etc", "/var", "/tmp",
    "/lib", "/lib64", "/boot", "/opt", "/root",
    "/home", "/Users",
    "/System", "/Applications", "/Library",
    "/private", "/private/var", "/private/etc",
    "C:\\", "C:\\Windows", "C:\\Program Files",
    "C:\\Program Files (x86)", "C:\\Users",
}

_HOME_PREFIXES = ("/Users", "/home", "C:\\Users")


def _is_blocked(path: str) -> bool:
    resolved = os.path.realpath(path)
    normalized = Path(resolved).as_posix()
    literal = Path(path).as_posix()

    for check in (normalized, literal):
        if check in _BLOCKLIST:
            return True

    for prefix in _HOME_PREFIXES:
        norm_prefix = Path(prefix).as_posix()
        for check in (normalized, literal):
            if check == norm_prefix:
                return True
            if check.startswith(norm_prefix + "/"):
                parts = check[len(norm_prefix) + 1:].split("/")
                if len(parts) <= 1:
                    return True
    return False


def _stat_target(path: str) -> DeleteTarget:
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        return DeleteTarget(
            path=path, exists=False, is_dir=False,
            size_bytes=0, file_count=0, writable=False,
            error=str(exc),
        )

    is_dir = os.path.isdir(path)
    size = 0
    file_count = 0

    if is_dir:
        for root, _dirs, files in os.walk(path, followlinks=False):
            for f in files:
                fp = os.path.join(root, f)
                with contextlib.suppress(OSError):
                    size += os.path.getsize(fp)
                file_count += 1
    else:
        size = st.st_size
        file_count = 1

    writable = os.access(path, os.W_OK)
    return DeleteTarget(
        path=path, exists=True, is_dir=is_dir,
        size_bytes=size, file_count=file_count,
        writable=writable,
    )


def preview_delete(
    paths: list[str],
    *,
    scan_root: str | None = None,
    force: bool = False,
) -> DeletePreview:
    blocked: list[str] = []
    targets: list[DeleteTarget] = []

    for p in paths:
        real = os.path.realpath(p)
        if not force:
            if _is_blocked(real):
                blocked.append(p)
                continue
            if scan_root:
                real_root = os.path.realpath(scan_root)
                if real == real_root:
                    blocked.append(p)
                    continue
                prefix = real_root if real_root.endswith(os.sep) else real_root + os.sep
                if not real.startswith(prefix):
                    blocked.append(p)
                    continue
        targets.append(_stat_target(p))

    return DeletePreview(
        targets=targets,
        total_bytes=sum(t.size_bytes for t in targets),
        total_files=sum(t.file_count for t in targets),
        all_writable=all(t.writable for t in targets if t.exists),
        blocked_paths=blocked,
    )


def execute_delete(
    paths: list[str],
    store: SnapshotStore,
    *,
    scan_root: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> DeleteResult:
    preview = preview_delete(paths, scan_root=scan_root, force=force)

    if preview.blocked_paths:
        return DeleteResult(
            succeeded=[],
            failed=[(p, "blocked by safety rules") for p in preview.blocked_paths],
            bytes_freed=0,
            dry_run=dry_run,
        )

    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []
    freed = 0

    for target in preview.targets:
        if not target.exists:
            failed.append((target.path, "does not exist"))
            continue
        if not target.writable:
            failed.append((target.path, "not writable"))
            store.log_deletion(
                target.path, 0, was_dir=target.is_dir,
                success=False, error="not writable",
            )
            continue

        if dry_run:
            succeeded.append(target.path)
            freed += target.size_bytes
            continue

        try:
            if target.is_dir:
                shutil.rmtree(target.path)
            else:
                os.remove(target.path)
            succeeded.append(target.path)
            freed += target.size_bytes
            store.log_deletion(
                target.path, target.size_bytes,
                was_dir=target.is_dir, success=True,
            )
        except OSError as exc:
            failed.append((target.path, str(exc)))
            store.log_deletion(
                target.path, 0, was_dir=target.is_dir,
                success=False, error=str(exc),
            )

    return DeleteResult(
        succeeded=succeeded,
        failed=failed,
        bytes_freed=freed,
        dry_run=dry_run,
    )
