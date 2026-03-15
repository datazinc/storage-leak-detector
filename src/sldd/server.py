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

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sldd.api import SLDD
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

    # -- Snapshots -----------------------------------------------------------

    @app.get("/api/snapshots")
    def list_snapshots(
        limit: int = Query(50, ge=1, le=1000),
        depth: int | None = Query(None, description="Filter by scan_depth"),
    ):
        api = _get_api()
        snaps = api.list_snapshots(limit=limit, scan_depth=depth)
        return [_serialize(s) for s in snaps]

    @app.get("/api/snapshots/depths")
    def snapshot_depths():
        """Return available scan depths and snapshot counts: [{depth, count}, ...]."""
        api = _get_api()
        rows = api.get_snapshot_depths()
        return [{"depth": d, "count": c} for d, c in rows]

    @app.post("/api/snapshots")
    def create_snapshot(req: SnapshotRequest):
        api = _get_api()
        api.sync_scan_config_from_settings()
        try:
            snap = api.take_snapshot(label=req.label)
        except Exception as exc:
            _log.exception("Snapshot creation failed")
            raise HTTPException(500, f"Snapshot failed: {exc}") from exc
        return _serialize(snap)

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: int):
        api = _get_api()
        snap = api.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        return _serialize(snap)

    @app.delete("/api/snapshots/{snapshot_id}")
    def delete_snapshot(snapshot_id: int):
        api = _get_api()
        api.delete_snapshot(snapshot_id)
        return {"ok": True}

    @app.post("/api/snapshots/prune")
    def prune_snapshots(req: PruneRequest):
        api = _get_api()
        deleted = api.prune(keep=req.keep)
        return {"deleted": deleted}

    # -- Diff & Detection ----------------------------------------------------

    @app.get("/api/diff")
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
                "Snapshots have incompatible scan depths — only compare scans at the same depth",
            )
        return _serialize(d)

    @app.get("/api/diff/latest")
    def diff_latest():
        api = _get_api()
        snaps = api.list_snapshots(limit=2)
        if len(snaps) < 2:
            raise HTTPException(404, "Need at least 2 snapshots")
        d = api.diff_latest()
        if d is None:
            raise HTTPException(
                400,
                "Latest snapshots have incompatible scan depths — only compare scans at the same depth",
            )
        return _serialize(d)

    @app.get("/api/report")
    def get_report(
        old: int | None = Query(None, description="Old snapshot ID"),
        new: int | None = Query(None, description="New snapshot ID"),
        depth: int | None = Query(None, description="Use latest 2 snapshots at this depth"),
        top_n: int = Query(20, ge=1, le=100),
    ):
        api = _get_api()
        if depth is not None:
            snaps = api.list_snapshots(limit=2, scan_depth=depth)
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
                "Report failed: incompatible depths old=%s (depth=%s) new=%s (depth=%s)",
                old_id, getattr(old_snap, "scan_depth", None),
                new_id, getattr(new_snap, "scan_depth", None),
            )
            raise HTTPException(
                400,
                "Snapshots have incompatible scan depths — use ?depth=N to compare at a specific depth",
            )
        result = api.report_dict(report)
        if depth is not None:
            result["_meta"] = {"depth": depth, "matching_snapshots": len(api.list_snapshots(limit=1000, scan_depth=depth))}
        return result

    # -- Drill-Down ----------------------------------------------------------

    @app.get("/api/drill/{snapshot_id}")
    def drill(snapshot_id: int, path: str = Query(...)):
        api = _get_api()
        children = api.drill(snapshot_id, path)
        return [_serialize(c) for c in children]

    @app.get("/api/history")
    def path_history(
        path: str = Query(...), limit: int = Query(50, ge=1),
    ):
        api = _get_api()
        return api.path_history(path, limit=limit)

    @app.get("/api/path/io")
    def path_io_now(path: str = Query(...)):
        api = _get_api()
        return api.path_io_now(path)

    @app.post("/api/path/io/offenders")
    def path_io_offenders(req: PathIOOffendersRequest):
        api = _get_api()
        return api.path_io_offenders(req.paths)

    @app.get("/api/path/io/history")
    def path_io_history(
        path: str = Query(...), limit: int = Query(100, ge=1, le=500),
    ):
        api = _get_api()
        return api.path_io_history(path, limit=limit)

    @app.post("/api/path/io/watch")
    def path_io_watch_start(req: PathIOWatchRequest):
        api = _get_api()
        api.path_io_watch_start(
            req.path, req.duration_minutes, req.sample_interval_sec
        )
        return {"ok": True}

    @app.delete("/api/path/io/watch")
    def path_io_watch_stop(path: str = Query(...)):
        api = _get_api()
        api.path_io_watch_stop(path)
        return {"ok": True}

    @app.get("/api/path/io/watch")
    def path_io_watch_status():
        api = _get_api()
        return api.path_io_watch_status()

    @app.get("/api/path/io/summary")
    def path_io_summary(limit: int = Query(50, ge=1, le=200)):
        api = _get_api()
        return api.path_io_summary(limit=limit)

    @app.post("/api/path/open")
    def path_open_in_finder(req: PathOpenRequest):
        """Open path in system file manager (Finder on macOS, Explorer on Windows)."""
        p = Path(req.path).resolve()
        if not p.exists():
            raise HTTPException(404, f"Path does not exist: {req.path}")
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", str(p)], check=True, timeout=5)
            elif sys.platform == "win32":
                subprocess.run(
                    ["explorer", "/select,", str(p)],
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

    @app.get("/api/top/{snapshot_id}")
    def top_dirs(
        snapshot_id: int, limit: int = Query(20, ge=1, le=200),
    ):
        api = _get_api()
        dirs = api.top_dirs(snapshot_id, limit=limit)
        return [_serialize(d) for d in dirs]

    # -- Scan Jobs (largest files, duplicates) --------------------------------

    @app.post("/api/scan/largest")
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

    @app.post("/api/scan/duplicates")
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

    @app.get("/api/scan/{job_id}/status")
    def scan_job_status(job_id: str):
        job = _scan_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job.status()

    @app.post("/api/scan/{job_id}/stop")
    def scan_job_stop(job_id: str):
        job = _scan_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        _request_stop(job)
        return job.status()

    @app.get("/api/scan/{job_id}/result")
    def scan_job_result(job_id: str):
        job = _scan_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if not job.done:
            raise HTTPException(202, "Scan still running")
        if job.error:
            raise HTTPException(500, job.error)
        return job.result

    @app.get("/api/files/largest")
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

    @app.get("/api/playback/frames")
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

    @app.get("/api/playback/path-timeline")
    def playback_path_timeline(
        path: str = Query(...),
        from_id: int = Query(..., alias="from"),
        to_id: int = Query(..., alias="to"),
    ):
        api = _get_api()
        return api.playback_path_timeline(path, from_id, to_id)

    # -- Deletion ------------------------------------------------------------

    @app.post("/api/delete/preview")
    def delete_preview(req: DeletePreviewRequest):
        api = _get_api()
        preview = api.delete_preview(req.paths, force=req.force)
        return _serialize(preview)

    @app.post("/api/delete/execute")
    def delete_execute(req: DeleteExecuteRequest):
        api = _get_api()
        if not req.confirm:
            raise HTTPException(400, "Must set confirm=true")
        result = api.delete_execute(
            req.paths, dry_run=req.dry_run, force=req.force,
        )
        return _serialize(result)

    @app.get("/api/delete/history")
    def deletion_history(limit: int = Query(100, ge=1)):
        api = _get_api()
        return api.deletion_history(limit=limit)

    # -- Settings ------------------------------------------------------------

    @app.get("/api/settings")
    def get_settings():
        api = _get_api()
        return api.get_settings()

    @app.put("/api/settings")
    def update_settings(req: SettingsUpdateRequest):
        api = _get_api()
        api.save_settings(req.settings)
        return {"ok": True}

    @app.get("/api/db-info")
    def db_info():
        api = _get_api()
        return api.get_db_info()

    @app.post("/api/db/vacuum")
    def vacuum_db():
        api = _get_api()
        api.vacuum_db()
        return {"ok": True}

    @app.get("/api/db/size")
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

    @app.post("/api/db/reset")
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

    @app.post("/api/db/recover")
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

    @app.get("/api/adaptive/stats")
    def adaptive_stats():
        api = _get_api()
        return api.adaptive_stats()

    @app.get("/api/adaptive/plan")
    def adaptive_plan():
        api = _get_api()
        plan = api.plan_next_scan()
        return _serialize(plan)

    @app.post("/api/adaptive/compact")
    def adaptive_compact():
        api = _get_api()
        try:
            result = api.run_compact()
        except Exception as exc:
            _log.exception("Compaction failed")
            raise HTTPException(500, f"Compact failed: {exc}") from exc
        return _serialize(result)

    @app.post("/api/adaptive/reset")
    def adaptive_reset():
        api = _get_api()
        api.reset_adaptive()
        return {"ok": True}

    @app.get("/api/adaptive/paths")
    def adaptive_paths(
        status: str | None = Query(None),
        limit: int = Query(200, ge=1, le=5000),
    ):
        api = _get_api()
        rows = api.store.get_path_statuses(status=status)
        return rows[:limit]

    # -- Watch Mode ----------------------------------------------------------

    @app.get("/api/watch/status")
    def watch_status():
        if _watcher is None:
            return {"running": False, "error": "Watch controller not initialized"}
        return _watcher.status()

    @app.post("/api/watch/start")
    def watch_start(req: WatchStartRequest):
        if _watcher is None:
            raise HTTPException(500, "Watch controller not initialized")
        _watcher.start(interval=req.interval_seconds, one_shot=req.one_shot)
        return _watcher.status()

    @app.post("/api/watch/stop")
    def watch_stop():
        if _watcher is None:
            raise HTTPException(500, "Watch controller not initialized")
        _watcher.stop()
        return _watcher.status()

    @app.get("/api/watch/events")
    def watch_events(after: int = Query(0, ge=0)):
        if _watcher is None:
            return []
        return _watcher.events_since(after)

    @app.get("/api/watch/report")
    def watch_last_report():
        if _watcher is None or _watcher.last_report() is None:
            raise HTTPException(404, "No watch report yet")
        return _watcher.last_report()

    # -- SPA fallback --------------------------------------------------------

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
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
