"""CLI entry point — all commands for snapshot, diff, detect, watch, drill."""

from __future__ import annotations

import sys

import click
from rich.console import Console

from sldd.api import SLDD
from sldd.models import (
    AdaptiveConfig,
    CompactResult,
    DetectConfig,
    Report,
    ScanConfig,
    ScanPlan,
    WatchConfig,
)
from sldd.report import print_report

console = Console()


def _parse_size(value: str) -> int:
    """Parse a human size like '500MB' into bytes."""
    value = value.strip().upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if value.endswith(suffix):
            return int(float(value[: -len(suffix)].strip()) * mult)
    return int(value)


@click.group()
@click.version_option(package_name="sldd")
def main() -> None:
    """sldd — Storage Leak Diff Detector.

    Detect what's eating your disk space by taking filesystem snapshots
    and comparing them over time.
    """


@main.command()
@click.option("--root", "-r", default="/", help="Root path to scan.")
@click.option("--exclude", "-e", multiple=True, help="Paths to exclude (repeatable).")
@click.option("--max-depth", "-d", type=int, default=None, help="Max directory depth.")
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.option("--label", "-l", default="", help="Label for this snapshot.")
@click.option("--follow-symlinks", is_flag=True, help="Follow symbolic links.")
@click.option("--cross-devices", is_flag=True, help="Cross filesystem boundaries.")
def snapshot(
    root: str,
    exclude: tuple[str, ...],
    max_depth: int | None,
    db: str,
    label: str,
    follow_symlinks: bool,
    cross_devices: bool,
) -> None:
    """Take a filesystem snapshot."""
    config = ScanConfig(
        root=root,
        excludes=list(exclude) if exclude else ScanConfig().excludes,
        max_depth=max_depth,
        follow_symlinks=follow_symlinks,
        cross_devices=cross_devices,
        db_path=db,
        label=label,
    )

    def _progress(path: str, count: int) -> None:
        console.print(f"  [dim]Scanning... {count} dirs | {path[:80]}[/dim]", end="\r")

    with SLDD(db_path=db, scan_config=config) as api:
        console.print(f"[bold]Taking snapshot of[/bold] {root}")
        snap = api.take_snapshot(progress=_progress, label=label)
        console.print(f"\n[green]Snapshot #{snap.id} saved[/green] — "
                       f"{len(snap.entries)} directories catalogued")


@main.command()
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.option("--limit", "-n", default=50, help="Max snapshots to list.")
def ls(db: str, limit: int) -> None:
    """List saved snapshots."""
    from rich.table import Table

    with SLDD(db_path=db) as api:
        snaps = api.list_snapshots(limit=limit)
        if not snaps:
            console.print("[yellow]No snapshots found.[/yellow]")
            return

        t = Table(title="Snapshots", show_header=True, header_style="bold")
        t.add_column("ID", width=6)
        t.add_column("Timestamp")
        t.add_column("Root")
        t.add_column("Label")

        for s in snaps:
            t.add_row(str(s.id), s.timestamp.strftime("%Y-%m-%d %H:%M:%S"), s.root_path, s.label)
        console.print(t)


@main.command()
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.option("--from", "from_id", type=int, default=None, help="Old snapshot ID.")
@click.option("--to", "to_id", type=int, default=None, help="New snapshot ID.")
@click.option("--top", "-n", default=20, help="Number of top growers to show.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--min-growth", default="0", help="Min growth to show (e.g. '10MB').")
def diff(
    db: str,
    from_id: int | None,
    to_id: int | None,
    top: int,
    as_json: bool,
    min_growth: str,
) -> None:
    """Compare two snapshots and show what grew."""
    min_bytes = _parse_size(min_growth)

    with SLDD(db_path=db) as api:
        if from_id is not None and to_id is not None:
            report = api.diff_and_detect(from_id, to_id, top_n=top)
        else:
            snaps = api.list_snapshots(limit=2)
            if len(snaps) < 2:
                console.print("[red]Need at least 2 snapshots. Take another snapshot first.[/red]")
                sys.exit(1)
            new, old = snaps[0], snaps[1]
            assert new.id is not None and old.id is not None
            report = api.diff_and_detect(old.id, new.id, top_n=top)

        if report is None:
            console.print("[red]Could not compute diff.[/red]")
            sys.exit(1)

        if min_bytes > 0:
            filtered = [e for e in report.top_growers if e.growth_bytes >= min_bytes]
            report = Report(
                generated_at=report.generated_at,
                diff=report.diff,
                anomalies=report.anomalies,
                top_growers=filtered,
                top_shrinkers=report.top_shrinkers,
            )

        if as_json:
            click.echo(api.report_json(report))
        else:
            api.print_report(report)


@main.command()
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.option("--path", "-p", required=True, help="Directory path to drill into.")
@click.option("--snapshot-id", "-s", type=int, default=None, help="Snapshot ID (default: latest).")
def drill(db: str, path: str, snapshot_id: int | None) -> None:
    """Drill down into a directory to see its children's sizes."""
    from rich.table import Table

    with SLDD(db_path=db) as api:
        if snapshot_id is None:
            snap = api.store.get_latest_snapshot()
            if snap is None or snap.id is None:
                console.print("[red]No snapshots found.[/red]")
                sys.exit(1)
            snapshot_id = snap.id

        children = api.drill(snapshot_id, path)
        if not children:
            console.print(f"[yellow]No children found for {path}[/yellow]")
            return

        t = Table(title=f"Children of {path} (snapshot #{snapshot_id})", header_style="bold")
        t.add_column("Path")
        t.add_column("Size", justify="right")
        t.add_column("Files", justify="right")
        t.add_column("Dirs", justify="right")

        for e in children:
            t.add_row(e.path, _format_bytes(e.total_bytes), str(e.file_count), str(e.dir_count))
        console.print(t)


@main.command()
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.option("--path", "-p", required=True, help="Directory path to inspect.")
@click.option("--limit", "-n", default=20, help="Number of history entries.")
def history(db: str, path: str, limit: int) -> None:
    """Show size history of a specific directory across snapshots."""
    from rich.table import Table

    with SLDD(db_path=db) as api:
        rows = api.path_history(path, limit=limit)
        if not rows:
            console.print(f"[yellow]No history found for {path}[/yellow]")
            return

        t = Table(title=f"History of {path}", header_style="bold")
        t.add_column("Snap ID", width=8)
        t.add_column("Timestamp")
        t.add_column("Size", justify="right")
        t.add_column("Files", justify="right")
        t.add_column("Δ Size", justify="right")

        prev_bytes: int | None = None
        for row in reversed(rows):
            delta = ""
            if prev_bytes is not None:
                d = row["total_bytes"] - prev_bytes
                delta = _format_bytes(d) if d != 0 else "—"
            prev_bytes = row["total_bytes"]
            t.add_row(
                str(row["snapshot_id"]),
                row["timestamp"],
                _format_bytes(row["total_bytes"]),
                str(row["file_count"]),
                delta,
            )
        console.print(t)


@main.command()
@click.option("--root", "-r", default="/", help="Root path to scan.")
@click.option("--exclude", "-e", multiple=True, help="Paths to exclude.")
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.option("--interval", "-i", default=600, help="Seconds between snapshots.")
@click.option("--threshold", default="500MB", help="Absolute growth threshold for alerts.")
@click.option("--rate-threshold", default="200MB", help="Growth rate threshold per hour.")
@click.option("--keep", default=144, help="Max snapshots to keep.")
@click.option("--json", "as_json", is_flag=True, help="Output reports as JSON.")
@click.option("--adaptive/--no-adaptive", default=True, help="Enable adaptive scanning.")
@click.option("--initial-depth", default=3, help="Depth for discovery scans (adaptive mode).")
@click.option("--stability-scans", default=3, help="Scans before marking a path stable.")
def watch(
    root: str,
    exclude: tuple[str, ...],
    db: str,
    interval: int,
    threshold: str,
    rate_threshold: str,
    keep: int,
    as_json: bool,
    adaptive: bool,
    initial_depth: int,
    stability_scans: int,
) -> None:
    """Watch the filesystem: take periodic snapshots and alert on anomalies."""
    from sldd.scheduler import Watcher

    scan_cfg = ScanConfig(
        root=root,
        excludes=list(exclude) if exclude else ScanConfig().excludes,
        db_path=db,
    )
    detect_cfg = DetectConfig(
        abs_threshold_bytes=_parse_size(threshold),
        growth_rate_threshold_bytes_per_hour=float(_parse_size(rate_threshold)),
    )
    watch_cfg = WatchConfig(
        scan=scan_cfg,
        detect=detect_cfg,
        interval_seconds=interval,
        max_snapshots_kept=keep,
    )
    adaptive_cfg = AdaptiveConfig(
        mode="auto" if adaptive else "disabled",
        initial_depth=initial_depth,
        stability_scans=stability_scans,
        retain_snapshots=keep,
    )

    def _on_report(report: Report) -> None:
        if as_json:
            from sldd.report import report_to_json
            click.echo(report_to_json(report))
        else:
            print_report(report)

    def _on_adaptive(plan: ScanPlan, compact_result: CompactResult | None) -> None:
        console.print(
            f"  [dim]Adaptive: {plan.strategy} — {plan.reason}[/dim]"
        )
        if compact_result and compact_result.entries_removed > 0:
            console.print(
                f"  [dim]Compacted: {compact_result.entries_removed} entries removed, "
                f"{compact_result.paths_collapsed} subtrees collapsed, "
                f"{compact_result.snapshots_pruned} snapshots pruned[/dim]"
            )

    def _on_error(exc: Exception) -> None:
        console.print(f"[red]Error: {exc}[/red]")

    mode_label = f"adaptive (depth {initial_depth})" if adaptive else "full"
    console.print(
        f"[bold]Watching[/bold] {root} every {interval}s "
        f"[dim]({mode_label})[/dim] (Ctrl-C to stop)"
    )
    watcher = Watcher(
        watch_cfg,
        adaptive_config=adaptive_cfg,
        on_report=_on_report,
        on_adaptive=_on_adaptive,
        on_error=_on_error,
    )
    watcher.start()


@main.command()
@click.option("--db", default="snapshots.db", help="Database file path.")
def compact(db: str) -> None:
    """Run compaction: collapse stable subtrees and prune old snapshots."""
    with SLDD(db_path=db) as api:
        stats_before = api.adaptive_stats()
        result = api.run_compact()
        stats_after = api.adaptive_stats()
        console.print("[green]Compaction complete:[/green]")
        console.print(f"  Entries removed: {result.entries_removed}")
        console.print(f"  Subtrees collapsed: {result.paths_collapsed}")
        console.print(f"  Snapshots pruned: {result.snapshots_pruned}")
        console.print(
            f"  DB entries: {stats_before['total_entries']} → {stats_after['total_entries']}"
        )


@main.command()
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.option("--keep", "-k", type=int, required=True, help="Number of recent snapshots to keep.")
def prune(db: str, keep: int) -> None:
    """Delete old snapshots, keeping the N most recent."""
    with SLDD(db_path=db) as api:
        deleted = api.prune(keep=keep)
        console.print(f"[green]Pruned {deleted} snapshot(s), kept {keep} most recent.[/green]")


@main.command()
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.argument("snapshot_id", type=int)
def rm(db: str, snapshot_id: int) -> None:
    """Delete a specific snapshot by ID."""
    with SLDD(db_path=db) as api:
        api.delete_snapshot(snapshot_id)
        console.print(f"[green]Snapshot #{snapshot_id} deleted.[/green]")


@main.command()
@click.option("--db", default="snapshots.db", help="Database file path.")
@click.option("--root", "-r", default="/", help="Scan root for safety checks.")
@click.option("--port", "-p", default=8080, help="Port to listen on.")
@click.option("--host", default="127.0.0.1", help="Host to bind to.")
@click.option("--auto-restart/--no-auto-restart", default=True, help="Auto-restart on crash.")
@click.option("--max-restarts", default=10, help="Max consecutive auto-restarts.")
@click.option("--open/--no-open", "open_browser", default=True, help="Auto-open browser.")
@click.option("--build/--no-build", default=True, help="Auto-build frontend if stale.")
def web(
    db: str, root: str, port: int, host: str,
    auto_restart: bool, max_restarts: int,
    open_browser: bool, build: bool,
) -> None:
    """Launch the web dashboard.

    Just run `sldd web` — it auto-builds the frontend if needed and opens
    your browser.  Subsequent restarts skip the browser.
    """
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        console.print(
            "[red]uvicorn not installed. "
            "Run: pip install 'storage-leak-diff-detector[web]'[/red]"
        )
        sys.exit(1)

    import shutil
    import signal
    import socket
    import os
    import subprocess
    import time

    def _port_in_use(h: str, p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((h, p))
                return False
            except OSError:
                return True

    def _kill_our_process_on_port(p: int) -> bool:
        """Kill process on port if it's sldd/uvicorn. Return True if killed."""
        if sys.platform == "win32":
            try:
                import psutil
                killed = False
                for conn in psutil.net_connections(kind="inet"):
                    if conn.laddr and conn.laddr.port == p and conn.pid:
                        try:
                            proc = psutil.Process(conn.pid)
                            name = (proc.name() or "").lower()
                            cmdline = " ".join(proc.cmdline() or []).lower()
                            if "sldd" in name or "sldd" in cmdline or "uvicorn" in name or "uvicorn" in cmdline:
                                proc.kill()
                                killed = True
                                break
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                if killed:
                    time.sleep(1.0)
                return killed
            except Exception:
                return False
        lsof_cmd = shutil.which("lsof") or "/usr/sbin/lsof"
        try:
            out = subprocess.run(
                [lsof_cmd, "-i", f":{p}", "-t"],
                capture_output=True, text=True, timeout=5, env=os.environ,
            )
            raw = (out.stdout or "").strip() or (out.stderr or "").strip()
            if not raw:
                return False
            pids = list(dict.fromkeys(x.strip() for x in raw.split() if x.strip()))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        killed = False
        for pid_s in pids:
            try:
                pid = int(pid_s)
                for ps_arg in ("args=", "command="):
                    cmd = subprocess.run(
                        ["ps", "-p", str(pid), "-o", ps_arg],
                        capture_output=True, text=True, timeout=2,
                    )
                    if cmd.returncode != 0:
                        continue
                    args = (cmd.stdout or "").lower()
                    if "sldd" in args or "uvicorn" in args:
                        os.kill(pid, signal.SIGKILL)
                        killed = True
                        break
                if killed:
                    break
            except (ValueError, ProcessLookupError, PermissionError):
                continue
        if killed:
            time.sleep(1.0)
        return killed

    def _find_available_port(h: str, start: int, max_tries: int = 20) -> int:
        for i in range(max_tries):
            p = start + i
            if not _port_in_use(h, p):
                return p
        return start

    if _port_in_use(host, port):
        if _kill_our_process_on_port(port):
            console.print(f"[dim]Killed previous sldd on port {port}, starting...[/dim]")
    if _port_in_use(host, port):
        preferred = port
        port = _find_available_port(host, port)
        if port != preferred:
            console.print(f"[dim]Port {preferred} in use, using {port}[/dim]")

    if build:
        _ensure_frontend_built()

    url = f"http://{host}:{port}"
    browser_opened = False

    def _maybe_open_browser() -> None:
        nonlocal browser_opened
        if open_browser and not browser_opened:
            import threading
            import webbrowser
            browser_opened = True

            def _open() -> None:
                time.sleep(1.5)
                webbrowser.open(url)

            threading.Thread(target=_open, daemon=True).start()

    if not auto_restart:
        os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
        from sldd.server import create_app
        app = create_app(db_path=db, scan_root=root)
        console.print(f"[bold]Starting web dashboard[/bold] at {url}")
        _maybe_open_browser()
        uvicorn.run(
            app, host=host, port=port, log_level="info",
            loop="asyncio", http="h11",  # avoid C-ext segfaults (httptools)
        )
        return

    def _run_server() -> subprocess.Popen:
        kwargs: dict = {
            "env": {
                **os.environ,
                "SLDD_DB_PATH": db,
                "SLDD_SCAN_ROOT": root,
                "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": "python",
            },
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "sldd.server:app_factory",
                "--host", host, "--port", str(port),
                "--log-level", "info",
                "--loop", "asyncio",
                "--http", "h11",
                "--factory",
            ],
            **kwargs,
        )

    proc: subprocess.Popen | None = None

    def _kill_child(_signum=None, _frame=None):
        nonlocal proc
        if proc is not None and proc.poll() is None:
            proc.kill()  # SIGKILL for immediate exit, no graceful shutdown
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if _signum is not None:
            sys.exit(128 + (_signum or 0))

    restarts = 0
    try:
        while restarts < max_restarts:
            console.print(
                f"[bold]Starting web dashboard[/bold] at {url}"
                + (f" [dim](restart #{restarts})[/dim]" if restarts else "")
            )
            _maybe_open_browser()
            proc = _run_server()
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                # Keep handler ref so it's not GC'd
                def _win_ctrl_handler(dw_ctrl_type: int) -> bool:
                    if dw_ctrl_type in (0, 1):  # CTRL_C_EVENT, CTRL_BREAK_EVENT
                        _kill_child()
                        sys.exit(130)
                    return False

                _win_handler = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(_win_ctrl_handler)
                ctypes.windll.kernel32.SetConsoleCtrlHandler(_win_handler, True)
            else:
                signal.signal(signal.SIGINT, _kill_child)
                signal.signal(signal.SIGTERM, _kill_child)
            proc.wait()
            if proc.returncode == 0:
                break
            restarts += 1
            if restarts < max_restarts:
                console.print(
                    f"[yellow]Server exited with code {proc.returncode}. "
                    f"Restarting in 2s... ({restarts}/{max_restarts})[/yellow]"
                )
                time.sleep(2)
            else:
                console.print(
                    f"[red]Server crashed {max_restarts} times. Giving up.[/red]"
                )
                sys.exit(1)
    except KeyboardInterrupt:
        _kill_child()
        sys.exit(130)


def _ensure_frontend_built() -> None:
    """Build the frontend if dist/ is missing or older than src/."""
    import shutil
    import subprocess
    from pathlib import Path

    # Installed package: frontend is bundled in sldd/web/, nothing to build
    pkg_web = Path(__file__).resolve().parent / "web"
    if (pkg_web / "index.html").is_file():
        return

    # Source/dev: check frontend/ directory
    frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
    dist_dir = frontend_dir / "dist"
    index_html = dist_dir / "index.html"

    if not frontend_dir.is_dir():
        console.print("[yellow]Frontend directory not found — serving API only[/yellow]")
        return

    needs_build = False
    if not index_html.is_file():
        needs_build = True
        reason = "dist/index.html not found"
    else:
        src_dir = frontend_dir / "src"
        if src_dir.is_dir():
            newest_src = max(
                (f.stat().st_mtime for f in src_dir.rglob("*") if f.is_file()),
                default=0,
            )
            dist_time = index_html.stat().st_mtime
            if newest_src > dist_time:
                needs_build = True
                reason = "source files newer than build"

    if not needs_build:
        return

    npm = shutil.which("npm")
    if npm is None:
        console.print(
            f"[yellow]Frontend needs building ({reason}) but npm not found. "
            f"Run manually: cd frontend && npm install && npm run build[/yellow]"
        )
        return

    node_modules = frontend_dir / "node_modules"
    if not node_modules.is_dir():
        console.print("[dim]Installing frontend dependencies...[/dim]")
        result = subprocess.run(
            [npm, "install"], cwd=str(frontend_dir),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]npm install failed:[/red]\n{result.stderr[:500]}")
            return

    # Clear dist before build to avoid Vite ENOTEMPTY (e.g. when switching root/user)
    if dist_dir.is_dir():
        try:
            shutil.rmtree(dist_dir)
        except OSError as e:
            console.print(
                f"[yellow]Could not clear dist/ ({e}). "
                f"Try: rm -rf frontend/dist[/yellow]"
            )

    console.print(f"[dim]Building frontend ({reason})...[/dim]")
    result = subprocess.run(
        [npm, "run", "build"], cwd=str(frontend_dir),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Frontend build failed:[/red]\n{result.stderr[:500]}")
        return

    console.print("[green]Frontend built successfully[/green]")


def _format_bytes(n: int | float) -> str:
    sign = "-" if n < 0 else ("+" if n > 0 else "")
    abs_n = abs(n)
    if abs_n >= 1024 ** 3:
        return f"{sign}{abs_n / 1024**3:.2f} GB"
    if abs_n >= 1024 ** 2:
        return f"{sign}{abs_n / 1024**2:.1f} MB"
    if abs_n >= 1024:
        return f"{sign}{abs_n / 1024:.1f} KB"
    return f"{sign}{abs_n:.0f} B"


if __name__ == "__main__":
    main()
