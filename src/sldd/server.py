"""FastAPI web server — REST endpoints + watch controller + static file serving."""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
import subprocess
import sys
import threading
import traceback
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sldd.api import SLDD
from sldd.snapshot import ScanStoppedError
from sldd.models import ScanConfig

_log = logging.getLogger("sldd.server")

_api: SLDD | None = None
_watcher: _WatchController | None = None
_io_watcher: _IOWatchController | None = None

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


class _IOWatchController:
    """Background thread that samples process I/O for user-watched paths."""

    def __init__(self, api: SLDD) -> None:
        self._api = api
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        import time as _time
        from sldd.process_io import sample_path_io

        while not self._stop.is_set():
            try:
                watches = self._api.path_io_watch_status()
                now = _dt.datetime.now(_dt.timezone.utc)
                for w in watches:
                    path = w["path"]
                    started = _dt.datetime.fromisoformat(w["started_at"])
                    duration_m = w["duration_minutes"]
                    interval_sec = w.get("sample_interval_sec", 60)
                    elapsed_m = (now - started).total_seconds() / 60
                    if elapsed_m >= duration_m:
                        self._api.path_io_watch_stop(path)
                        continue
                    samples = sample_path_io(path)
                    if samples:
                        rows = [
                            (s.path, s.pid, s.process_name, s.read_bytes, s.write_bytes, s.open_files_under_path)
                            for s in samples
                        ]
                        self._api.path_io_store_samples(rows)
            except Exception as exc:
                _log.exception("I/O watch sample failed: %s", exc)
            self._stop.wait(timeout=60)


class _WatchController:
    """Background thread that runs the scan-diff-detect loop for the web UI."""

    def __init__(self, api: SLDD) -> None:
        self._api = api
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._interval = 300
        self._one_shot = False
        self._scanning = False
        self._scan_progress: dict[str, Any] = {}
        self._last_scan_at: _dt.datetime | None = None
        self._last_report: dict[str, Any] | None = None
        self._last_plan: dict[str, Any] | None = None
        self._scans_completed = 0
        self._last_error: str | None = None
        self._events: list[dict[str, Any]] = []
        self._next_scan_at: _dt.datetime | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, interval: int = 300, one_shot: bool = False) -> None:
        if self.running:
            return
        self._interval = max(30, interval)
        self._one_shot = one_shot
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._push_event(
            "watch_started",
            f"One shot" if one_shot else f"Interval: {self._interval}s",
        )

    def stop(self) -> None:
        self._stop.set()
        self._push_event("watch_stopped", f"After {self._scans_completed} scans")

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "running": self.running,
            "interval_seconds": self._interval,
            "scanning": self._scanning,
            "scans_completed": self._scans_completed,
            "last_scan_at": self._last_scan_at.isoformat() if self._last_scan_at else None,
            "next_scan_at": self._next_scan_at.isoformat() if self._next_scan_at else None,
            "last_error": self._last_error,
            "last_plan": self._last_plan,
        }
        if self._scanning:
            result["progress"] = self._scan_progress
        return result

    def events_since(self, after: int = 0) -> list[dict[str, Any]]:
        return [e for e in self._events if e["seq"] > after]

    def last_report(self) -> dict[str, Any] | None:
        return self._last_report

    def _push_event(self, kind: str, detail: str = "") -> None:
        seq = len(self._events) + 1
        evt = {
            "seq": seq,
            "time": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "kind": kind,
            "detail": detail,
        }
        self._events.append(evt)
        if len(self._events) > 200:
            self._events = self._events[-100:]

    def _on_progress(self, current_path: str, dirs_scanned: int) -> None:
        self._scan_progress = {
            "current_path": current_path,
            "dirs_scanned": dirs_scanned,
        }

    def _loop(self) -> None:
        import time as _time

        while not self._stop.is_set():
            self._scanning = True
            self._last_error = None
            self._scan_progress = {"current_path": "starting...", "dirs_scanned": 0}
            scan_start = _time.monotonic()
            try:
                self._api.sync_scan_config_from_settings()
                result = self._api.adaptive_snapshot_and_detect(
                    progress=self._on_progress,
                    stop_check=lambda: self._stop.is_set(),
                )
                report, plan, compact_result = result
                elapsed = _time.monotonic() - scan_start

                self._last_scan_at = _dt.datetime.now(_dt.timezone.utc)
                self._scans_completed += 1
                self._last_plan = _serialize(plan) if plan else None

                dirs_done = self._scan_progress.get("dirs_scanned", 0)

                if report is not None:
                    report_dict = self._api.report_dict(report)
                    self._last_report = report_dict
                    n_anom = len(report_dict.get("anomalies", []))
                    growth = report_dict.get("total_growth_human", "0 B")
                    self._push_event(
                        "scan_complete",
                        f"Scanned {dirs_done:,} dirs in {elapsed:.1f}s — "
                        f"Growth: {growth}, {n_anom} anomalies",
                    )
                    if n_anom > 0:
                        top = report_dict["anomalies"][0]
                        self._push_event(
                            "anomaly_detected",
                            f"[{top['severity']}] {top['path']}: {top['growth_human']}",
                        )
                    # Optional: sample top growers for process I/O attribution
                    if report_dict.get("top_growers"):
                        settings = self._api.get_settings()
                        if settings.get("io.collect_during_scan", "true").lower() not in (
                            "false",
                            "0",
                            "no",
                        ):
                            top_growers = sorted(
                                report_dict["top_growers"],
                                key=lambda k: k.get("growth_bytes", 0),
                                reverse=True,
                            )[:3]
                            from sldd.process_io import sample_path_io

                            for g in top_growers:
                                path = g.get("path")
                                if not path:
                                    continue
                                try:
                                    samples = sample_path_io(path)
                                    if samples:
                                        rows = [
                                            (
                                                s.path,
                                                s.pid,
                                                s.process_name,
                                                s.read_bytes,
                                                s.write_bytes,
                                                s.open_files_under_path,
                                            )
                                            for s in samples
                                        ]
                                        self._api.path_io_store_samples(rows)
                                except Exception as exc:
                                    _log.debug(
                                        "I/O sample during scan failed for %s: %s",
                                        path,
                                        exc,
                                    )
                else:
                    self._push_event(
                        "scan_complete",
                        f"Scanned {dirs_done:,} dirs in {elapsed:.1f}s — "
                        "No diff yet (need 2+ snapshots)",
                    )

                if compact_result and compact_result.entries_removed > 0:
                    self._push_event(
                        "compacted",
                        f"{compact_result.entries_removed} entries removed",
                    )

            except ScanStoppedError:
                _log.info("Watch scan stopped by user")
                break
            except Exception as exc:
                self._last_error = str(exc)
                self._push_event("scan_error", str(exc))
                _log.exception("Watch scan failed")
            finally:
                self._scanning = False
                self._scan_progress = {}

            self._next_scan_at = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(
                seconds=self._interval
            )
            if self._one_shot:
                self._stop.set()
                break
            self._stop.wait(timeout=self._interval)
            self._next_scan_at = None


def _get_api() -> SLDD:
    if _api is None:
        raise HTTPException(500, "API not initialized")
    return _api


def create_app(
    db_path: str = "snapshots.db",
    scan_root: str = "/",
) -> FastAPI:
    global _api, _watcher

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        global _api, _watcher, _io_watcher
        from sldd.storage import SnapshotStore
        store = SnapshotStore(db_path, check_same_thread=False)
        _api = SLDD(
            db_path=db_path,
            scan_config=ScanConfig(root=scan_root, db_path=db_path),
        )
        _api._store = store
        _api.open()
        _watcher = _WatchController(_api)
        _io_watcher = _IOWatchController(_api)
        _io_watcher.start()
        yield
        if _io_watcher and _io_watcher.running:
            _io_watcher.stop()
        if _watcher and _watcher.running:
            _watcher.stop()
        _api.close()

    app = FastAPI(title="sldd", version="0.1.0", lifespan=lifespan)

    def _stop_watcher_for_db_op() -> None:
        if _watcher is not None and _watcher.running:
            _watcher.stop()

    @app.exception_handler(sqlite3.DatabaseError)
    async def _db_error_handler(request: Request, exc: sqlite3.DatabaseError) -> JSONResponse:
        """On corruption, try auto-recover; otherwise return structured error for frontend."""
        msg = str(exc).lower()
        if "malformed" not in msg:
            _log.error("Database error on %s %s: %s", request.method, request.url.path, exc)
            return JSONResponse(
                status_code=500,
                content={"error": "database_corrupted", "recovered": False, "detail": str(exc)},
            )
        _log.warning("Database corrupted on %s %s, attempting recover: %s", request.method, request.url.path, exc)
        _stop_watcher_for_db_op()
        try:
            _api.recover_db()
            _log.info("Database recovered successfully")
            return JSONResponse(
                status_code=503,
                content={"error": "database_corrupted", "recovered": True, "detail": "Database was corrupted and has been wiped (all data lost). Refresh the page to continue."},
            )
        except Exception as rec:
            _log.exception("Database recover failed")
            return JSONResponse(
                status_code=500,
                content={"error": "database_corrupted", "recovered": False, "detail": str(rec)},
            )

    @app.exception_handler(Exception)
    async def _global_exc_handler(request: Request, exc: Exception) -> JSONResponse:
        _log.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
        _log.debug(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "path": str(request.url.path)},
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_routes(app)

    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="assets",
        )

    return app


class _ScanJob:
    """A background filesystem scan with live progress."""

    def __init__(self, job_id: str, kind: str) -> None:
        self.id = job_id
        self.kind = kind
        self.phase = "starting"
        self._stop_requested = False
        self._pause_requested = False
        self._paused = False
        self._resume_event = threading.Event()
        self._resume_event.set()
        self.current_path = ""
        self.dirs_scanned = 0
        self.files_checked = 0
        self.detail = ""
        self.done = False
        self.error: str | None = None
        self.result: Any = None
        self._started = _dt.datetime.now(_dt.timezone.utc)
        self._thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        elapsed = (
            _dt.datetime.now(_dt.timezone.utc) - self._started
        ).total_seconds()
        return {
            "id": self.id,
            "kind": self.kind,
            "phase": self.phase,
            "paused": self._paused,
            "current_path": self.current_path,
            "dirs_scanned": self.dirs_scanned,
            "files_checked": self.files_checked,
            "detail": self.detail,
            "done": self.done,
            "error": self.error,
            "elapsed_seconds": round(elapsed, 1),
        }


_scan_jobs: dict[str, _ScanJob] = {}
_scan_lock = threading.Lock()


def _start_scan_job(kind: str, target: Any) -> _ScanJob:
    import uuid
    job_id = uuid.uuid4().hex[:12]
    job = _ScanJob(job_id, kind)
    with _scan_lock:
        _scan_jobs[job_id] = job
        # Keep only last 10 completed jobs
        done_ids = [
            k for k, v in _scan_jobs.items() if v.done and k != job_id
        ]
        for old in done_ids[:-10]:
            del _scan_jobs[old]
    t = threading.Thread(target=target, args=(job,), daemon=True)
    job._thread = t
    t.start()
    return job


def _db_excluded_paths(db_path: str) -> set[str]:
    """Return the set of real paths for the DB and its WAL/SHM sidecars."""
    import os
    base = os.path.realpath(db_path)
    return {base, base + "-wal", base + "-shm", base + "-journal"}


def _run_largest_scan(
    job: _ScanJob, root: str, limit: int, max_depth: int,
    exclude_paths: set[str] | None = None,
) -> None:
    import gc
    import heapq
    import os

    excluded = exclude_paths or set()

    try:
        gc.disable()  # avoid GC during heavy allocation — can trigger C-extension segfaults
        job.phase = "walking"
        heap: list[tuple[int, str]] = []
        stack: list[tuple[str, int]] = [(root, 0)]

        while stack:
            if job._stop_requested:
                break
            _wait_if_paused(job)
            if job._stop_requested:
                break
            dirpath, depth = stack.pop()
            job.dirs_scanned += 1
            if job.dirs_scanned % 200 == 0:
                job.current_path = dirpath

            try:
                entries = os.scandir(dirpath)
            except (PermissionError, OSError):
                continue

            with entries:
                for entry in entries:
                    if job._stop_requested:
                        break
                    try:
                        if entry.is_file(follow_symlinks=False):
                            if entry.path in excluded:
                                continue
                            size = entry.stat(follow_symlinks=False).st_size
                            job.files_checked += 1
                            if len(heap) < limit:
                                heapq.heappush(heap, (size, entry.path))
                            elif size > heap[0][0]:
                                heapq.heapreplace(heap, (size, entry.path))
                        elif (
                            entry.is_dir(follow_symlinks=False)
                            and depth < max_depth
                        ):
                            stack.append((entry.path, depth + 1))
                    except OSError:
                        continue

        if job._stop_requested:
            job.phase = "stopped"
            job.done = True
            return

        job.phase = "sorting"
        heap.sort(key=lambda x: x[0], reverse=True)
        job.result = [
            {
                "path": fpath,
                "size_bytes": sz,
                "size_human": _fmt_size(sz),
                "directory": os.path.dirname(fpath),
                "name": os.path.basename(fpath),
                "mtime": _safe_mtime(fpath),
            }
            for sz, fpath in heap
        ]
        job.phase = "done"
    except Exception as exc:
        job.error = str(exc)
        job.phase = "error"
        _log.exception("Largest scan failed")
    finally:
        gc.enable()
        job.done = True


def _request_stop(job: _ScanJob) -> None:
    job._stop_requested = True
    job._resume_event.set()  # Wake thread if blocked in _wait_if_paused


def _request_pause(job: _ScanJob) -> None:
    job._pause_requested = True


def _request_resume(job: _ScanJob) -> None:
    job._pause_requested = False
    job._resume_event.set()


def _wait_if_paused(job: _ScanJob) -> None:
    """Block until resumed or stop requested."""
    while job._pause_requested and not job._stop_requested:
        job._paused = True
        job._resume_event.clear()
        job._resume_event.wait()
    job._paused = False


def _run_duplicates_scan(
    job: _ScanJob, root: str, min_size: int, max_depth: int,
    exclude_paths: set[str] | None = None,
) -> None:
    """Find duplicate files using a 3-pass approach:
    1. Group by file size (only sizes with 2+ files are candidates)
    2. Partial hash (first 4KB) to narrow candidates
    3. Full hash to confirm duplicates
    """
    import gc
    import hashlib
    import os

    excluded = exclude_paths or set()
    partial_size = 4096

    try:
        gc.disable()  # avoid GC during heavy allocation — can trigger C-extension segfaults
        # --- Pass 1: Group by size ---
        job.phase = "sizing"
        job.detail = "Collecting file sizes..."
        size_map: dict[int, list[str]] = {}
        stack: list[tuple[str, int]] = [(root, 0)]

        while stack and not job._stop_requested:
            _wait_if_paused(job)
            if job._stop_requested:
                break
            dirpath, depth = stack.pop()
            job.dirs_scanned += 1
            if job.dirs_scanned % 200 == 0:
                job.current_path = dirpath

            try:
                entries = os.scandir(dirpath)
            except (PermissionError, OSError):
                continue

            with entries:
                for entry in entries:
                    if job._stop_requested:
                        break
                    try:
                        if entry.is_file(follow_symlinks=False):
                            if entry.path in excluded:
                                continue
                            st = entry.stat(follow_symlinks=False)
                            sz = st.st_size
                            job.files_checked += 1
                            if sz >= min_size:
                                size_map.setdefault(sz, []).append(
                                    entry.path
                                )
                        elif (
                            entry.is_dir(follow_symlinks=False)
                            and depth < max_depth
                        ):
                            stack.append((entry.path, depth + 1))
                    except OSError:
                        continue

        candidates = {
            sz: paths for sz, paths in size_map.items() if len(paths) >= 2
        }
        total_candidates = sum(len(p) for p in candidates.values())
        job.detail = (
            f"{total_candidates:,} candidate files in "
            f"{len(candidates):,} size groups"
        )

        # --- Pass 2: Partial hash ---
        job.phase = "partial_hash"
        checked = 0
        partial_map: dict[str, list[str]] = {}

        for sz, paths in candidates.items():
            if job._stop_requested:
                break
            _wait_if_paused(job)
            if job._stop_requested:
                break
            for p in paths:
                if job._stop_requested:
                    break
                checked += 1
                if checked % 100 == 0:
                    job.current_path = p
                    job.detail = (
                        f"Partial hashing {checked:,}/{total_candidates:,}"
                    )
                try:
                    with open(p, "rb") as f:
                        data = f.read(partial_size)
                    key = f"{sz}:{hashlib.md5(data).hexdigest()}"
                    partial_map.setdefault(key, []).append(p)
                except OSError:
                    continue

        partial_candidates = {
            k: paths for k, paths in partial_map.items() if len(paths) >= 2
        }
        full_total = sum(len(p) for p in partial_candidates.values())
        job.detail = (
            f"{full_total:,} files need full hashing "
            f"({len(partial_candidates):,} groups)"
        )

        # --- Pass 3: Full hash ---
        job.phase = "full_hash"
        checked = 0
        full_map: dict[str, list[str]] = {}

        for _key, paths in partial_candidates.items():
            if job._stop_requested:
                break
            _wait_if_paused(job)
            if job._stop_requested:
                break
            for p in paths:
                if job._stop_requested:
                    break
                checked += 1
                if checked % 20 == 0:
                    job.current_path = p
                    job.detail = (
                        f"Full hashing {checked:,}/{full_total:,}"
                    )
                try:
                    h = hashlib.sha256()
                    with open(p, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            h.update(chunk)
                    full_map.setdefault(h.hexdigest(), []).append(p)
                except OSError:
                    continue

        if job._stop_requested:
            job.phase = "stopped"
            job.done = True
            job.error = "Scan stopped by user"
            return

        # --- Build result groups ---
        job.phase = "building_results"
        groups: list[dict[str, Any]] = []
        for digest, paths in full_map.items():
            if len(paths) < 2:
                continue
            try:
                sz = os.path.getsize(paths[0])
            except OSError:
                sz = 0
            wasted = sz * (len(paths) - 1)
            groups.append({
                "hash": digest[:16],
                "size_bytes": sz,
                "size_human": _fmt_size(sz),
                "count": len(paths),
                "wasted_bytes": wasted,
                "wasted_human": _fmt_size(wasted),
                "files": [
                    {
                        "path": p,
                        "name": os.path.basename(p),
                        "directory": os.path.dirname(p),
                        "mtime": _safe_mtime(p),
                    }
                    for p in sorted(paths)
                ],
            })

        groups.sort(key=lambda g: g["wasted_bytes"], reverse=True)
        job.result = {
            "groups": groups,
            "total_groups": len(groups),
            "total_duplicate_files": sum(g["count"] for g in groups),
            "total_wasted_bytes": sum(g["wasted_bytes"] for g in groups),
            "total_wasted_human": _fmt_size(
                sum(g["wasted_bytes"] for g in groups)
            ),
        }
        job.phase = "done"
        job.detail = (
            f"{len(groups)} duplicate groups, "
            f"{_fmt_size(sum(g['wasted_bytes'] for g in groups))} wasted"
        )

    except Exception as exc:
        job.error = str(exc)
        job.phase = "error"
        _log.exception("Duplicates scan failed")
    finally:
        gc.enable()
        job.done = True


def _fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _safe_mtime(path: str) -> str | None:
    import os
    try:
        return _dt.datetime.fromtimestamp(
            os.lstat(path).st_mtime, tz=_dt.timezone.utc
        ).isoformat()
    except OSError:
        return None


def _serialize(obj: Any) -> Any:
    """Recursively convert dataclasses/datetimes to JSON-safe dicts."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, _dt.datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, tuple):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class PruneRequest(BaseModel):
    keep: int


class DeletePreviewRequest(BaseModel):
    paths: list[str]
    force: bool = False


class DeleteExecuteRequest(BaseModel):
    paths: list[str]
    confirm: bool = False
    dry_run: bool = False
    force: bool = False


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, str]


class SnapshotRequest(BaseModel):
    label: str = ""


class WatchStartRequest(BaseModel):
    interval_seconds: int = 300
    one_shot: bool = False


class PathIOWatchRequest(BaseModel):
    path: str
    duration_minutes: int = 10
    sample_interval_sec: int = 60


class PathIOOffendersRequest(BaseModel):
    paths: list[str]


class PathOpenRequest(BaseModel):
    path: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _register_routes(app: FastAPI) -> None:
    api_router = APIRouter(prefix="/api", tags=["api"])

    # -- Snapshots -----------------------------------------------------------

    @api_router.get("/snapshots")
    def list_snapshots(
        limit: int = Query(50, ge=1, le=1000),
        depth: int | None = Query(None, description="Filter by scan_depth"),
    ):
        api = _get_api()
        snaps = api.list_snapshots(limit=limit, scan_depth=depth)
        return [_serialize(s) for s in snaps]

    @api_router.get("/snapshots/depths")
    def snapshot_depths():
        """Return available scan depths and snapshot counts: [{depth, count}, ...]."""
        api = _get_api()
        rows = api.get_snapshot_depths()
        return [{"depth": d, "count": c} for d, c in rows]

    @api_router.post("/snapshots")
    def create_snapshot(req: SnapshotRequest):
        api = _get_api()
        api.sync_scan_config_from_settings()
        try:
            snap = api.take_snapshot(label=req.label)
        except Exception as exc:
            _log.exception("Snapshot creation failed")
            raise HTTPException(500, f"Snapshot failed: {exc}") from exc
        return _serialize(snap)

    @api_router.get("/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: int):
        api = _get_api()
        snap = api.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        return _serialize(snap)

    @api_router.delete("/snapshots/{snapshot_id}")
    def delete_snapshot(snapshot_id: int):
        api = _get_api()
        api.delete_snapshot(snapshot_id)
        return {"ok": True}

    @api_router.post("/snapshots/prune")
    def prune_snapshots(req: PruneRequest):
        api = _get_api()
        deleted = api.prune(keep=req.keep)
        return {"deleted": deleted}

    # -- Diff & Detection ----------------------------------------------------

    @api_router.get("/diff")
    def compute_diff(
        old: int = Query(...), new: int = Query(...),
    ):
        api = _get_api()
        old_snap = api.get_snapshot(old)
        new_snap = api.get_snapshot(new)
        if old_snap is None or new_snap is None:
            raise HTTPException(404, "Snapshots not found")
        d = api.diff(old, new)
        if d is None:
            raise HTTPException(
                400,
                "Snapshots are incomparable (different scan roots or depths)",
            )
        return _serialize(d)

    @api_router.get("/diff/latest")
    def diff_latest():
        api = _get_api()
        snaps = api.list_snapshots(limit=2)
        if len(snaps) < 2:
            raise HTTPException(404, "Need at least 2 snapshots")
        d = api.diff_latest()
        if d is None:
            raise HTTPException(
                400,
                "Latest snapshots are incomparable (different scan roots or depths)",
            )
        return _serialize(d)

    @api_router.get("/report")
    def get_report(
        old: int | None = Query(None, description="Old snapshot ID"),
        new: int | None = Query(None, description="New snapshot ID"),
        depth: int | None = Query(None, description="Use latest 2 snapshots at this depth"),
        top_n: int = Query(20, ge=1, le=100),
    ):
        api = _get_api()
        if depth is not None:
            # Use same root_path as most recent snapshot (same watch scope)
            latest = api.list_snapshots(limit=1)
            root = latest[0].root_path if latest else None
            snaps = api.list_snapshots(limit=2, scan_depth=depth, root_path=root)
            if len(snaps) < 2:
                raise HTTPException(
                    400,
                    f"Need at least 2 snapshots at depth {depth} (found {len(snaps)})",
                )
            new_snap, old_snap = snaps[0], snaps[1]
            old_id = old_snap.id
            new_id = new_snap.id
            if old_id is None or new_id is None:
                raise HTTPException(500, "Snapshot IDs missing")
        else:
            if old is None or new is None:
                raise HTTPException(400, "Provide old and new snapshot IDs, or depth")
            old_snap = api.get_snapshot(old)
            new_snap = api.get_snapshot(new)
            if old_snap is None or new_snap is None:
                raise HTTPException(404, "Snapshots not found")
            old_id, new_id = old, new
        try:
            report = api.diff_and_detect(old_id, new_id, top_n=top_n)
        except Exception as exc:
            _log.exception("Report generation failed")
            raise HTTPException(500, f"Report failed: {exc}") from exc
        if report is None:
            _log.debug(
                "Report failed: incompatible old=%s (root=%s depth=%s) new=%s (root=%s depth=%s)",
                old_id, getattr(old_snap, "root_path", "?"), getattr(old_snap, "scan_depth", None),
                new_id, getattr(new_snap, "root_path", "?"), getattr(new_snap, "scan_depth", None),
            )
            raise HTTPException(
                400,
                "Snapshots are incomparable (different scan roots or depths) — compare snapshots from the same watch",
            )
        result = api.report_dict(report)
        if depth is not None:
            root = new_snap.root_path if new_snap else None
            result["_meta"] = {
                "depth": depth,
                "matching_snapshots": len(api.list_snapshots(limit=1000, scan_depth=depth, root_path=root)),
            }
        return result

    # -- Drill-Down ----------------------------------------------------------

    @api_router.get("/drill/{snapshot_id}")
    def drill(snapshot_id: int, path: str = Query(...)):
        api = _get_api()
        children = api.drill(snapshot_id, path)
        return [_serialize(c) for c in children]

    @api_router.get("/history")
    def path_history(
        path: str = Query(...),
        limit: int = Query(50, ge=1),
        scan_depth: str | None = Query(
            None,
            description="Only snapshots with this depth; use 'null' for legacy/full scans",
        ),
    ):
        api = _get_api()
        # Parse scan_depth: "null"/"legacy" = only full scans (scan_depth IS NULL), number = that depth
        depth_val: int | None | str = None
        if scan_depth is not None:
            if str(scan_depth).lower() in ("null", "legacy"):
                depth_val = "legacy"
            else:
                try:
                    depth_val = int(scan_depth)
                except ValueError:
                    depth_val = None
        return api.path_history(path, limit=limit, scan_depth=depth_val)

    @api_router.get("/path/io")
    def path_io_now(path: str = Query(...)):
        api = _get_api()
        return api.path_io_now(path)

    @api_router.post("/path/io/offenders")
    def path_io_offenders(req: PathIOOffendersRequest):
        api = _get_api()
        return api.path_io_offenders(req.paths)

    @api_router.get("/path/io/history")
    def path_io_history(
        path: str = Query(...), limit: int = Query(100, ge=1, le=500),
    ):
        api = _get_api()
        return api.path_io_history(path, limit=limit)

    @api_router.post("/path/io/watch")
    def path_io_watch_start(req: PathIOWatchRequest):
        api = _get_api()
        api.path_io_watch_start(
            req.path, req.duration_minutes, req.sample_interval_sec
        )
        return {"ok": True}

    @api_router.delete("/path/io/watch")
    def path_io_watch_stop(path: str = Query(...)):
        api = _get_api()
        api.path_io_watch_stop(path)
        return {"ok": True}

    @api_router.get("/path/io/watch")
    def path_io_watch_status():
        api = _get_api()
        return api.path_io_watch_status()

    @api_router.get("/path/io/summary")
    def path_io_summary(limit: int = Query(50, ge=1, le=200)):
        api = _get_api()
        return api.path_io_summary(limit=limit)

    @api_router.post("/path/open")
    def path_open_in_finder(req: PathOpenRequest):
        """Open path in system file manager (Finder on macOS, Explorer on Windows)."""
        p = Path(req.path).resolve()
        if not p.exists():
            raise HTTPException(404, f"Path does not exist: {req.path}")
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", str(p)], check=True, timeout=5)
            elif sys.platform == "win32":
                path_str = str(p).replace('"', "")
                select_arg = f'/select,"{path_str}"'
                subprocess.run(
                    ["explorer", select_arg],
                    check=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            else:
                # Linux: try xdg-open on parent dir
                subprocess.run(["xdg-open", str(p.parent)], check=True, timeout=5)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise HTTPException(500, f"Failed to open: {e}") from e
        return {"ok": True}

    @api_router.get("/top/{snapshot_id}")
    def top_dirs(
        snapshot_id: int, limit: int = Query(20, ge=1, le=200),
    ):
        api = _get_api()
        dirs = api.top_dirs(snapshot_id, limit=limit)
        return [_serialize(d) for d in dirs]

    # -- Scan Jobs (largest files, duplicates) --------------------------------

    @api_router.post("/scan/largest")
    def start_largest_scan(
        root: str = Query(None),
        limit: int = Query(100, ge=1, le=5000),
        max_depth: int = Query(6, ge=1, le=20),
    ):
        api = _get_api()
        scan_root = api.effective_scan_root(root)
        excl = _db_excluded_paths(api.scan_config.db_path)
        job = _start_scan_job(
            "largest",
            lambda j: _run_largest_scan(
                j, scan_root, limit, max_depth, exclude_paths=excl
            ),
        )
        return job.status()

    @api_router.post("/scan/duplicates")
    def start_duplicates_scan(
        root: str = Query(None),
        min_size: int = Query(1024, ge=0),
        max_depth: int = Query(6, ge=1, le=20),
    ):
        api = _get_api()
        scan_root = api.effective_scan_root(root)
        excl = _db_excluded_paths(api.scan_config.db_path)
        job = _start_scan_job(
            "duplicates",
            lambda j: _run_duplicates_scan(
                j, scan_root, min_size, max_depth, exclude_paths=excl
            ),
        )
        return job.status()

    @api_router.get("/scan/{job_id}/status")
    def scan_job_status(job_id: str):
        job = _scan_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job.status()

    @api_router.post("/scan/{job_id}/stop")
    def scan_job_stop(job_id: str):
        job = _scan_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        _request_stop(job)
        return job.status()

    @api_router.post("/scan/{job_id}/pause")
    def scan_job_pause(job_id: str):
        job = _scan_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if job.done:
            raise HTTPException(400, "Scan already finished")
        _request_pause(job)
        return job.status()

    @api_router.post("/scan/{job_id}/resume")
    def scan_job_resume(job_id: str):
        job = _scan_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if job.done:
            raise HTTPException(400, "Scan already finished")
        _request_resume(job)
        return job.status()

    @api_router.get("/scan/{job_id}/result")
    def scan_job_result(job_id: str):
        job = _scan_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if not job.done:
            raise HTTPException(202, "Scan still running")
        if job.error:
            raise HTTPException(500, job.error)
        return job.result

    @api_router.get("/files/largest")
    def largest_files_sync(
        root: str = Query(None),
        limit: int = Query(50, ge=1, le=5000),
        max_depth: int = Query(6, ge=1, le=20),
    ):
        api = _get_api()
        scan_root = api.effective_scan_root(root)
        excl = _db_excluded_paths(api.scan_config.db_path)
        job = _ScanJob("sync", "largest")
        _run_largest_scan(job, scan_root, limit, max_depth, exclude_paths=excl)
        if job.error:
            raise HTTPException(500, job.error)
        return job.result

    # -- Playback ------------------------------------------------------------

    @api_router.get("/playback/frames")
    def playback_frames(
        from_id: int = Query(..., alias="from"),
        to_id: int = Query(..., alias="to"),
        top_n: int = Query(20, ge=1, le=100),
        path: str | None = Query(None, description="Filter to paths under this prefix"),
    ):
        api = _get_api()
        path_prefix = path
        if not path_prefix:
            settings = api.get_settings()
            path_prefix = settings.get("replay.focus_path") or None
            if path_prefix:
                path_prefix = path_prefix.strip() or None
        try:
            frames = api.playback_frames(
                from_id, to_id, top_n=top_n, path_prefix=path_prefix,
            )
        except Exception as exc:
            _log.exception("Playback frame generation failed")
            raise HTTPException(500, f"Playback failed: {exc}") from exc
        return [_serialize(f) for f in frames]

    @api_router.get("/playback/path-timeline")
    def playback_path_timeline(
        path: str = Query(...),
        from_id: int = Query(..., alias="from"),
        to_id: int = Query(..., alias="to"),
    ):
        api = _get_api()
        return api.playback_path_timeline(path, from_id, to_id)

    # -- Deletion ------------------------------------------------------------

    @api_router.post("/delete/preview")
    def delete_preview(req: DeletePreviewRequest):
        api = _get_api()
        preview = api.delete_preview(req.paths, force=req.force)
        return _serialize(preview)

    @api_router.post("/delete/execute")
    def delete_execute(req: DeleteExecuteRequest):
        api = _get_api()
        if not req.confirm:
            raise HTTPException(400, "Must set confirm=true")
        result = api.delete_execute(
            req.paths, dry_run=req.dry_run, force=req.force,
        )
        return _serialize(result)

    @api_router.get("/delete/history")
    def deletion_history(limit: int = Query(100, ge=1)):
        api = _get_api()
        return api.deletion_history(limit=limit)

    # -- Settings ------------------------------------------------------------

    @api_router.get("/settings")
    def get_settings():
        api = _get_api()
        return api.get_settings()

    @api_router.put("/settings")
    def update_settings(req: SettingsUpdateRequest):
        api = _get_api()
        api.save_settings(req.settings)
        return {"ok": True}

    @api_router.get("/running-as-root")
    def running_as_root():
        """Return whether the server process is running with root/admin privileges."""
        import os
        if sys.platform == "win32":
            try:
                import ctypes
                return {"running_as_root": ctypes.windll.shell32.IsUserAnAdmin() != 0}  # type: ignore[attr-defined]
            except Exception:
                return {"running_as_root": False}
        return {"running_as_root": os.geteuid() == 0}

    @api_router.get("/can-restart-as-regular-user")
    def can_restart_as_regular_user():
        """Check if we can restart as the original (non-root) user."""
        import os
        if sys.platform == "win32":
            return {"can_restart": False, "reason": "Windows"}
        if os.geteuid() != 0:
            return {"can_restart": False, "reason": "Already running as regular user"}
        sudo_user = os.environ.get("SUDO_USER")
        if not sudo_user:
            return {"can_restart": False, "reason": "No SUDO_USER (not started via sudo)"}
        return {"can_restart": True, "sudo_user": sudo_user}

    @api_router.get("/can-restart-as-administrator")
    def can_restart_as_administrator():
        """Check if we can offer to restart with admin/root privileges (when not elevated)."""
        import os
        if sys.platform == "win32":
            try:
                import ctypes
                if ctypes.windll.shell32.IsUserAnAdmin() != 0:  # type: ignore[attr-defined]
                    return {"can_restart": False, "reason": "Already running as administrator"}
            except Exception:
                return {"can_restart": False, "reason": "Cannot detect admin status"}
            return {"can_restart": True}
        if os.geteuid() == 0:
            return {"can_restart": False, "reason": "Already running as root"}
        if sys.platform == "darwin":
            return {"can_restart": True}
        if sys.platform == "linux":
            import shutil
            if shutil.which("pkexec"):
                return {"can_restart": True}
            return {"can_restart": False, "reason": "pkexec not found (install polkit)"}
        return {"can_restart": False, "reason": "Unsupported platform"}

    def _find_available_port(host: str, start: int, max_tries: int = 20) -> int:
        import socket
        for i in range(max_tries):
            p = start + i
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind((host, p))
                    return p
                except OSError:
                    continue
        return start

    @api_router.post("/restart-as-regular-user")
    def restart_as_regular_user(request: Request):
        """Fix permissions on db/dist, then restart server as regular user."""
        import os
        import shutil
        if sys.platform == "win32":
            raise HTTPException(400, "Not supported on Windows")
        if os.geteuid() != 0:
            raise HTTPException(400, "Already running as regular user")
        sudo_user = os.environ.get("SUDO_USER")
        sudo_uid = os.environ.get("SUDO_UID")
        sudo_gid = os.environ.get("SUDO_GID")
        if not sudo_user or not sudo_uid:
            raise HTTPException(400, "No SUDO_USER (start with sudo sldd web)")
        api = _get_api()
        db_path = os.path.realpath(api.scan_config.db_path)
        scan_root = api.scan_config.root
        host = str(request.url.hostname or "127.0.0.1")
        preferred_port = request.url.port or 8080
        port = _find_available_port(host, preferred_port)
        project_root = Path(__file__).resolve().parent.parent.parent
        frontend_dist = project_root / "frontend" / "dist"
        uid, gid = int(sudo_uid), int(sudo_gid) if sudo_gid else int(sudo_uid)
        try:
            for p in [db_path, db_path + "-wal", db_path + "-shm"]:
                if os.path.exists(p):
                    os.chown(p, uid, gid)
            if frontend_dist.is_dir():
                subprocess.run(
                    ["chown", "-R", f"{uid}:{gid}", str(frontend_dist)],
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
        except OSError as e:
            _log.warning("chown failed: %s", e)
        import shlex
        sldd_path = shutil.which("sldd")
        if sldd_path:
            cmd = [sldd_path, "web"]
        else:
            cmd = [sys.executable, "-m", "sldd.cli", "web"]
        cmd += ["--no-auto-restart", "--no-open", "-p", str(port)]
        env_str = " ".join(
            f"{k}={shlex.quote(str(v))}"
            for k, v in [
                ("SLDD_DB_PATH", db_path),
                ("SLDD_SCAN_ROOT", scan_root),
                ("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python"),
            ]
        )
        cmd_str = " ".join(shlex.quote(c) for c in cmd)
        full_cmd = f"sleep 3 && exec sudo -u {shlex.quote(sudo_user)} env {env_str} {cmd_str}"
        subprocess.Popen(
            ["sh", "-c", full_cmd],
            start_new_session=True,
        )
        import threading
        def _exit_later():
            import time
            time.sleep(1)
            os._exit(0)
        threading.Thread(target=_exit_later, daemon=True).start()
        url = f"http://{host}:{port}"
        return {
            "ok": True,
            "message": "Restarting as regular user in 3 seconds…",
            "port": port,
            "url": url,
        }

    @api_router.post("/restart-as-administrator")
    def restart_as_administrator(request: Request):
        """Restart the server with admin/root privileges (when not elevated)."""
        import os
        import shutil
        import shlex

        api = _get_api()
        db_path = os.path.realpath(api.scan_config.db_path)
        scan_root = api.scan_config.root
        host = str(request.url.hostname or "127.0.0.1")
        preferred_port = request.url.port or 8080
        port = _find_available_port(host, preferred_port)
        url = f"http://{host}:{port}"

        sldd_path = shutil.which("sldd")
        if sldd_path:
            cmd = [sldd_path, "web"]
        else:
            cmd = [sys.executable, "-m", "sldd.cli", "web"]
        cmd += ["--no-auto-restart", "--no-open", "-p", str(port)]
        env_vars = [
            ("SLDD_DB_PATH", db_path),
            ("SLDD_SCAN_ROOT", scan_root),
            ("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python"),
        ]

        if sys.platform == "win32":
            try:
                import ctypes
                import tempfile
                if ctypes.windll.shell32.IsUserAnAdmin() != 0:  # type: ignore[attr-defined]
                    raise HTTPException(400, "Already running as administrator")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(400, "Cannot detect admin status")
            env_lines = "\n".join(f'$env:{k} = "{str(v).replace(chr(34), "")}"' for k, v in env_vars)
            cmd_invoke = " ".join(f'"{str(c).replace(chr(34), "`"")}"' for c in cmd)
            ps_content = f"{env_lines}\n& {cmd_invoke}\n"
            with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8") as f:
                f.write(ps_content)
                ps_path = f.name
            ps_path_safe = str(ps_path).replace('"', "")
            subprocess.Popen(
                [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", f'Start-Process powershell -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","{ps_path_safe}" -Verb RunAs'
                ],
                start_new_session=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        elif sys.platform == "darwin":
            if os.geteuid() == 0:
                raise HTTPException(400, "Already running as root")
            env_str = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env_vars)
            cmd_str = " ".join(shlex.quote(c) for c in cmd)
            script = f"{env_str} {cmd_str}"
            subprocess.Popen(
                ["osascript", "-e", f'do shell script {shlex.quote(script)} with administrator privileges'],
                start_new_session=True,
            )
        elif sys.platform == "linux":
            if os.geteuid() == 0:
                raise HTTPException(400, "Already running as root")
            if not shutil.which("pkexec"):
                raise HTTPException(400, "pkexec not found (install polkit)")
            env_str = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env_vars)
            cmd_str = " ".join(shlex.quote(c) for c in cmd)
            full_cmd = f"{env_str} {cmd_str}"
            subprocess.Popen(
                ["pkexec", "sh", "-c", full_cmd],
                start_new_session=True,
            )
        else:
            raise HTTPException(400, "Unsupported platform")

        import threading
        def _exit_later():
            import time
            time.sleep(1)
            os._exit(0)
        threading.Thread(target=_exit_later, daemon=True).start()
        return {"ok": True, "message": "Restarting with administrator privileges…", "port": port, "url": url}

    @api_router.get("/db-info")
    def db_info():
        api = _get_api()
        return api.get_db_info()

    @api_router.post("/db/vacuum")
    def vacuum_db():
        api = _get_api()
        api.vacuum_db()
        return {"ok": True}

    @api_router.get("/db/size")
    def db_size_live():
        """Lightweight endpoint for polling DB size in the sidebar."""
        import contextlib
        import os
        api = _get_api()
        db = os.path.realpath(api.scan_config.db_path)
        total = 0
        for ext in ("", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                total += os.path.getsize(db + ext)
        return {
            "total_bytes": total,
            "total_human": _fmt_size(total),
        }

    def _stop_watcher_for_db_op() -> None:
        if _watcher is not None and _watcher.running:
            _watcher.stop()

    @api_router.post("/db/reset")
    def reset_db():
        """Drop all data and recreate the schema."""
        api = _get_api()
        try:
            api.reset_db()
        except sqlite3.DatabaseError as exc:
            if "malformed" in str(exc).lower():
                _log.warning("DB corrupted, falling back to recover: %s", exc)
                _stop_watcher_for_db_op()
                try:
                    api.recover_db()
                except Exception as rec:
                    _log.exception("DB recover failed")
                    raise HTTPException(500, f"Recover failed: {rec}") from rec
            else:
                raise HTTPException(500, f"Reset failed: {exc}") from exc
        except Exception as exc:
            _log.exception("DB reset failed")
            raise HTTPException(500, f"Reset failed: {exc}") from exc
        return {"ok": True}

    @api_router.post("/db/recover")
    def recover_db_endpoint():
        """Delete corrupted DB files and reopen with fresh schema."""
        api = _get_api()
        _stop_watcher_for_db_op()
        try:
            api.recover_db()
        except Exception as exc:
            _log.exception("DB recover failed")
            raise HTTPException(500, f"Recover failed: {exc}") from exc
        return {"ok": True}

    # -- Adaptive Scanning ---------------------------------------------------

    @api_router.get("/adaptive/stats")
    def adaptive_stats():
        api = _get_api()
        return api.adaptive_stats()

    @api_router.get("/adaptive/plan")
    def adaptive_plan():
        api = _get_api()
        plan = api.plan_next_scan()
        return _serialize(plan)

    @api_router.post("/adaptive/compact")
    def adaptive_compact():
        api = _get_api()
        try:
            result = api.run_compact()
        except Exception as exc:
            _log.exception("Compaction failed")
            raise HTTPException(500, f"Compact failed: {exc}") from exc
        return _serialize(result)

    @api_router.post("/adaptive/reset")
    def adaptive_reset():
        api = _get_api()
        api.reset_adaptive()
        return {"ok": True}

    @api_router.get("/adaptive/paths")
    def adaptive_paths(
        status: str | None = Query(None),
        limit: int = Query(200, ge=1, le=5000),
    ):
        api = _get_api()
        rows = api.store.get_path_statuses(status=status)
        return rows[:limit]

    # -- Watch Mode ----------------------------------------------------------

    @api_router.get("/watch/status")
    def watch_status():
        if _watcher is None:
            return {"running": False, "error": "Watch controller not initialized"}
        return _watcher.status()

    @api_router.post("/watch/start")
    def watch_start(req: WatchStartRequest):
        if _watcher is None:
            raise HTTPException(500, "Watch controller not initialized")
        _watcher.start(interval=req.interval_seconds, one_shot=req.one_shot)
        return _watcher.status()

    @api_router.post("/watch/stop")
    def watch_stop():
        if _watcher is None:
            raise HTTPException(500, "Watch controller not initialized")
        _watcher.stop()
        return _watcher.status()

    @api_router.get("/watch/events")
    def watch_events(after: int = Query(0, ge=0)):
        if _watcher is None:
            return []
        return _watcher.events_since(after)

    @api_router.get("/watch/report")
    def watch_last_report():
        if _watcher is None or _watcher.last_report() is None:
            raise HTTPException(404, "No watch report yet")
        return _watcher.last_report()

    app.include_router(api_router)

    # -- SPA fallback (must be last; never matches /api/*) --------------------

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "Not found")
        if FRONTEND_DIR.is_dir():
            # Serve actual static files (JS, CSS, images) if they exist on disk
            static_file = FRONTEND_DIR / full_path
            if (
                full_path
                and static_file.is_file()
                and FRONTEND_DIR in static_file.resolve().parents
            ):
                return FileResponse(str(static_file))
            index = FRONTEND_DIR / "index.html"
            if index.is_file():
                return FileResponse(str(index))
        raise HTTPException(404, "Frontend not built")


def app_factory() -> FastAPI:
    """Factory for uvicorn --factory mode, reads config from env vars."""
    import os
    return create_app(
        db_path=os.environ.get("SLDD_DB_PATH", "snapshots.db"),
        scan_root=os.environ.get("SLDD_SCAN_ROOT", "/"),
    )
