"""E2E tests for Process I/O features.

Uses a background writer subprocess (io_writer) that keeps a file open and
periodically writes to it. Verifies that sldd can detect the process via
path_io_now, store samples, and that watch/history/summary APIs work.

Features tested:
- path_io_now: on-demand snapshot of processes with path open + I/O stats
- sample_path_io: one-time snapshot (used internally)
- path_io_store_samples: persist samples to DB
- path_io_history: historic samples with deltas for charting
- path_io_summary: paths with recent samples
- path_io_watch_start: register path for background I/O watching
- path_io_watch_status: list active watches
- path_io_watch_stop: stop watching a path
- get_processes_with_path_open: low-level collector (via path_io_now)
- diff + path_io: storage growth detection + process attribution together
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from sldd.api import SLDD
from sldd.models import ScanConfig
from sldd.platform_utils import normalize_path


def _run_io_writer(target_path: Path, duration_sec: float = 15, interval_sec: float = 0.5) -> subprocess.Popen:
    """Start io_writer subprocess. Caller must terminate it when done."""
    cmd = [
        sys.executable,
        "-m",
        "tests.io_writer",
        str(target_path),
        "--interval",
        str(interval_sec),
        "--duration",
        str(duration_sec),
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture()
def io_writer_process(tmp_path: Path):
    """Start io_writer, yield (process, target_path), ensure cleanup."""
    target = tmp_path / "writer_root"
    target.mkdir()
    proc = _run_io_writer(target, duration_sec=30, interval_sec=0.3)
    time.sleep(0.5)  # let writer open file and do first write
    yield proc, target
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture()
def api_with_writer(db_path: str, io_writer_process):
    """SLDD API with tmp_dir = writer's root so we can take snapshots too."""
    proc, target = io_writer_process
    cfg = ScanConfig(root=str(target), excludes=[], db_path=db_path)
    a = SLDD(db_path=db_path, scan_config=cfg)
    a.open()
    yield a, proc, target
    a.close()


class TestPathIONow:
    """path_io_now: on-demand snapshot of processes with path open."""

    def test_detects_writer_process(self, api_with_writer) -> None:
        api, proc, target = api_with_writer
        path = normalize_path(str(target))
        infos = api.path_io_now(path)
        pids = [p["pid"] for p in infos]
        assert proc.pid in pids, f"Writer PID {proc.pid} not in {infos}"

    def test_returns_io_fields(self, api_with_writer) -> None:
        api, proc, target = api_with_writer
        path = normalize_path(str(target))
        infos = api.path_io_now(path)
        our = next((p for p in infos if p["pid"] == proc.pid), None)
        assert our is not None
        assert "process_name" in our
        assert "read_bytes" in our
        assert "write_bytes" in our
        assert "open_files_under_path" in our
        assert our["open_files_under_path"] >= 1
        assert "cmdline" in our
        assert "username" in our

    def test_sorted_by_write_bytes(self, api_with_writer) -> None:
        api, _, target = api_with_writer
        path = normalize_path(str(target))
        infos = api.path_io_now(path)
        if len(infos) >= 2:
            for i in range(len(infos) - 1):
                assert infos[i]["write_bytes"] >= infos[i + 1]["write_bytes"]

    def test_empty_for_unrelated_path(self, api_with_writer) -> None:
        api, _, _ = api_with_writer
        infos = api.path_io_now("/nonexistent/path/xyz")
        assert infos == []


class TestPathIOStorage:
    """path_io_store_samples, path_io_history, path_io_summary."""

    def test_store_and_history(self, api_with_writer) -> None:
        api, proc, target = api_with_writer
        path = normalize_path(str(target))
        infos = api.path_io_now(path)
        our = next((p for p in infos if p["pid"] == proc.pid), None)
        assert our is not None

        samples = [
            (path, our["pid"], our["process_name"], our["read_bytes"], our["write_bytes"], our["open_files_under_path"]),
        ]
        api.path_io_store_samples(samples)

        history = api.path_io_history(path, limit=10)
        assert len(history) >= 1
        assert any(h["pid"] == proc.pid for h in history)

    def test_summary_includes_path(self, api_with_writer) -> None:
        api, proc, target = api_with_writer
        path = normalize_path(str(target))
        infos = api.path_io_now(path)
        our = next((p for p in infos if p["pid"] == proc.pid), None)
        assert our is not None

        api.path_io_store_samples([
            (path, our["pid"], our["process_name"], our["read_bytes"], our["write_bytes"], our["open_files_under_path"]),
        ])

        summary = api.path_io_summary(limit=50)
        paths = [s["path"] for s in summary]
        assert path in paths


class TestPathIOWatch:
    """path_io_watch_start, path_io_watch_status, path_io_watch_stop."""

    def test_watch_start_and_status(self, api_with_writer) -> None:
        api, _, target = api_with_writer
        path = normalize_path(str(target))

        api.path_io_watch_start(path, duration_minutes=5, sample_interval_sec=2)
        status = api.path_io_watch_status()
        assert any(s["path"] == path for s in status)

        api.path_io_watch_stop(path)
        status = api.path_io_watch_status()
        assert not any(s["path"] == path for s in status)

    def test_offenders_batch(self, api_with_writer) -> None:
        api, proc, target = api_with_writer
        path = normalize_path(str(target))
        result = api.path_io_offenders([path, "/nonexistent"])
        assert path in result
        assert result[path] is not None
        assert result[path]["pid"] == proc.pid
        assert result["/nonexistent"] is None

    def test_watch_stop_idempotent(self, api_with_writer) -> None:
        api, _, target = api_with_writer
        path = normalize_path(str(target))
        api.path_io_watch_stop(path)  # not watching; should not raise
        api.path_io_watch_stop(path)  # again


class TestCLIDetectsWriterGrowth:
    """CLI snapshot + diff detects storage growth from io_writer."""

    def test_snapshot_and_diff_via_cli(self, tmp_path: Path) -> None:
        """Run sldd snapshot and diff while writer runs; CLI detects growth."""
        from click.testing import CliRunner
        from sldd.cli import main
        from sldd.cli import main

        target = tmp_path / "writer_root"
        target.mkdir()
        proc = _run_io_writer(target, duration_sec=20, interval_sec=0.3)
        try:
            time.sleep(0.5)
            db = str(tmp_path / "cli.db")
            runner = CliRunner()
            r1 = runner.invoke(main, ["snapshot", "--root", str(target), "--db", db])
            assert r1.exit_code == 0
            time.sleep(1.5)
            r2 = runner.invoke(main, ["snapshot", "--root", str(target), "--db", db])
            assert r2.exit_code == 0
            r3 = runner.invoke(main, ["diff", "--db", db])
            assert r3.exit_code == 0
            assert "Top Growing" in r3.output or "growth" in r3.output.lower()
        finally:
            proc.terminate()
            proc.wait(timeout=5)


class TestPathIOWithDiffDetection:
    """Integration: diff detects growth, path_io_now detects the writer."""

    def test_diff_and_path_io_together(self, api_with_writer) -> None:
        """Take snapshots, writer grows dir, diff detects it, path_io_now finds writer."""
        api, proc, target = api_with_writer
        path = normalize_path(str(target))

        s1 = api.take_snapshot(label="before")
        time.sleep(1.5)  # writer adds more data
        s2 = api.take_snapshot(label="after")

        report = api.diff_and_detect(s1.id, s2.id)
        assert report is not None
        grower_paths = [g.path for g in report.top_growers]
        assert path in grower_paths or any(path in p or p in path for p in grower_paths)

        infos = api.path_io_now(path)
        assert any(p["pid"] == proc.pid for p in infos), f"Writer {proc.pid} not in {infos}"


class TestPathIOFullFlow:
    """Full flow: writer running, snapshot, store samples, history."""

    def test_full_flow(self, api_with_writer) -> None:
        api, proc, target = api_with_writer
        path = normalize_path(str(target))

        # 1. On-demand snapshot detects writer
        infos = api.path_io_now(path)
        assert any(p["pid"] == proc.pid for p in infos)

        # 2. Store samples
        our = next((p for p in infos if p["pid"] == proc.pid))
        api.path_io_store_samples([
            (path, our["pid"], our["process_name"], our["read_bytes"], our["write_bytes"], our["open_files_under_path"]),
        ])

        # 3. History returns data
        history = api.path_io_history(path, limit=10)
        assert len(history) >= 1

        # 4. Summary includes path
        summary = api.path_io_summary(limit=50)
        assert any(s["path"] == path for s in summary)

        # 5. Watch lifecycle
        api.path_io_watch_start(path, duration_minutes=1, sample_interval_sec=2)
        assert any(s["path"] == path for s in api.path_io_watch_status())
        api.path_io_watch_stop(path)
        assert not any(s["path"] == path for s in api.path_io_watch_status())
