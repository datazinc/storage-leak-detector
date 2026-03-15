"""Cross-platform process I/O collector — which processes have paths open and their I/O stats."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sldd.platform_utils import normalize_path

_log = logging.getLogger("sldd.process_io")


def _safe_utf8(s: str) -> str:
    """Ensure string is valid UTF-8 for SQLite storage. psutil can return names with invalid bytes."""
    return s.encode("utf-8", errors="replace").decode("utf-8")


# Serialize psutil access — concurrent iteration from multiple threads can cause
# race conditions or segfaults (e.g. IOWatchController + request handler).
_psutil_lock = threading.Lock()


@dataclass
class ProcessIOInfo:
    pid: int
    process_name: str
    read_bytes: int
    write_bytes: int
    open_files_under_path: int
    cmdline: str | None = None  # full command line for process analysis
    username: str | None = None  # process owner


@dataclass
class PathIOSample:
    path: str
    pid: int
    process_name: str
    read_bytes: int
    write_bytes: int
    open_files_under_path: int


def get_processes_with_path_open(path: str) -> list[ProcessIOInfo]:
    """Return processes that have files open under path, with their I/O counters."""
    import psutil

    norm_path = normalize_path(path)
    path_prefix = norm_path.rstrip("/") + "/" if norm_path != "/" else "/"
    path_exact = norm_path.rstrip("/")

    result: list[ProcessIOInfo] = []
    seen_pids: set[int] = set()

    with _psutil_lock:
        _collect_processes(path_exact, path_prefix, result, seen_pids)

    return result


def _collect_processes(
    path_exact: str,
    path_prefix: str,
    result: list[ProcessIOInfo],
    seen_pids: set[int],
) -> None:
    import psutil

    for pid in psutil.pids():
        if pid in seen_pids:
            continue
        try:
            proc = psutil.Process(pid)
            open_files = proc.open_files()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        count_under = 0
        for f in open_files:
            try:
                p = normalize_path(f.path)
            except (OSError, ValueError):
                continue
            if p == path_exact or p.startswith(path_prefix):
                count_under += 1

        if count_under == 0:
            continue

        seen_pids.add(pid)
        read_bytes = 0
        write_bytes = 0
        try:
            io = proc.io_counters()
            read_bytes = io.read_bytes
            write_bytes = io.write_bytes
        except (psutil.AccessDenied, AttributeError):
            pass

        cmdline_str: str | None = None
        try:
            cmd = proc.cmdline()
            if cmd:
                cmdline_str = _safe_utf8(" ".join(cmd))[:512]  # truncate for storage
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError, TypeError):
            pass

        username_str: str | None = None
        try:
            username_str = _safe_utf8(proc.username())
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError, TypeError):
            pass

        try:
            name = _safe_utf8(proc.name())
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            name = f"pid:{pid}"

        result.append(
            ProcessIOInfo(
                pid=pid,
                process_name=name,
                read_bytes=read_bytes,
                write_bytes=write_bytes,
                open_files_under_path=count_under,
                cmdline=cmdline_str,
                username=username_str,
            )
        )


def sample_path_io(path: str) -> list[PathIOSample]:
    """One-time snapshot: processes with path open and their I/O stats."""
    infos = get_processes_with_path_open(path)
    return [
        PathIOSample(
            path=path,
            pid=p.pid,
            process_name=p.process_name,
            read_bytes=p.read_bytes,
            write_bytes=p.write_bytes,
            open_files_under_path=p.open_files_under_path,
        )
        for p in infos
    ]
