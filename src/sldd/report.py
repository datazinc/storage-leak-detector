"""Report generation — terminal (rich), JSON, and structured dict output."""

from __future__ import annotations

import json
from typing import Any

from sldd.models import Anomaly, DirDiff, Report, Severity

# ---------------------------------------------------------------------------
# Structured dict (for any UI to consume)
# ---------------------------------------------------------------------------

def report_to_dict(report: Report) -> dict[str, Any]:
    """Convert a Report to a plain dict suitable for JSON serialization or API response."""
    return {
        "generated_at": report.generated_at.isoformat(),
        "snapshot_old": {
            "id": report.diff.snapshot_old.id,
            "timestamp": report.diff.snapshot_old.timestamp.isoformat(),
            "root": report.diff.snapshot_old.root_path,
            "label": report.diff.snapshot_old.label,
        },
        "snapshot_new": {
            "id": report.diff.snapshot_new.id,
            "timestamp": report.diff.snapshot_new.timestamp.isoformat(),
            "root": report.diff.snapshot_new.root_path,
            "label": report.diff.snapshot_new.label,
        },
        "elapsed_seconds": report.diff.elapsed_seconds,
        "total_growth_bytes": report.diff.total_growth_bytes,
        "total_growth_human": _fmt_bytes(report.diff.total_growth_bytes),
        "anomalies": group_anomalies_by_path(
            [_anomaly_dict(a) for a in report.anomalies]
        ),
        "top_growers": [
            _diff_entry_dict(d, report.diff.elapsed_seconds)
            for d in report.top_growers
        ],
        "top_shrinkers": [
            _diff_entry_dict(d, report.diff.elapsed_seconds)
            for d in report.top_shrinkers
        ],
    }


def report_to_json(report: Report, *, indent: int = 2) -> str:
    return json.dumps(report_to_dict(report), indent=indent)


# ---------------------------------------------------------------------------
# Rich terminal output
# ---------------------------------------------------------------------------

def print_report(report: Report) -> None:
    """Pretty-print a report to the terminal using rich."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()
    hours = report.diff.elapsed_seconds / 3600
    rate_str = _fmt_bytes(
        report.diff.total_growth_bytes / hours if hours > 0 else 0,
    )

    console.print()
    console.print(Panel.fit(
        f"[bold]Storage Diff Report[/bold]\n"
        f"From: {report.diff.snapshot_old.timestamp:%Y-%m-%d %H:%M:%S} "
        f"(#{report.diff.snapshot_old.id})\n"
        f"  To: {report.diff.snapshot_new.timestamp:%Y-%m-%d %H:%M:%S} "
        f"(#{report.diff.snapshot_new.id})\n"
        f"Elapsed: {_fmt_duration(report.diff.elapsed_seconds)}  |  "
        f"Total growth: {_fmt_bytes(report.diff.total_growth_bytes)}  |  "
        f"Rate: {rate_str}/h",
        title="sldd",
        border_style="blue",
    ))

    # -- Anomalies -----------------------------------------------------------
    if report.anomalies:
        console.print()
        console.print("[bold red]Anomalies Detected[/bold red]")
        console.print()
        for a in report.anomalies:
            sev_style = {
                Severity.CRITICAL: "bold white on red",
                Severity.WARNING: "bold black on yellow",
                Severity.INFO: "dim",
            }.get(a.severity, "")
            sev_tag = Text(
                f" {a.severity.value.upper()} ", style=sev_style,
            )
            r = a.growth_rate_bytes_per_hour
            console.print(
                sev_tag,
                Text(f"  {a.rule}", style="dim"),
                f"  {_fmt_bytes(a.growth_bytes)}",
                f"  ({_fmt_bytes(r)}/h)" if r else "",
            )
            console.print(
                f"      Path:       [bold]{_esc(a.path)}[/bold]",
            )
            if a.attributed_path != a.path:
                console.print(
                    f"      Root cause: "
                    f"[bold cyan]{_esc(a.attributed_path)}[/bold cyan]",
                )
            console.print(
                f"      {a.message}", style="dim",
            )
            console.print()
    else:
        console.print("\n[green]No anomalies detected.[/green]")

    # -- Top Growers ---------------------------------------------------------
    growers = report.top_growers
    if growers:
        console.print("[bold]Top Growing Directories[/bold]")
        gt = Table(
            show_header=True,
            header_style="bold",
            padding=(0, 1),
            expand=True,
        )
        gt.add_column("#", width=3, no_wrap=True)
        gt.add_column("Path", min_width=30, ratio=3)
        gt.add_column("Growth", justify="right", min_width=10, no_wrap=True)
        gt.add_column("Rate/h", justify="right", min_width=10, no_wrap=True)
        gt.add_column("Size", justify="right", min_width=10, no_wrap=True)
        gt.add_column("%", justify="right", width=7, no_wrap=True)
        gt.add_column("Files", justify="right", width=8, no_wrap=True)

        for i, d in enumerate(growers[:20], 1):
            growth_style = (
                "bold red" if d.growth_bytes > 100 * 1024 * 1024
                else "red" if d.growth_bytes > 0
                else "green" if d.growth_bytes < 0
                else ""
            )
            r = d.growth_bytes / hours if hours > 0 else 0
            gt.add_row(
                str(i),
                Text(d.path, overflow="ellipsis", no_wrap=True),
                Text(_fmt_bytes(d.growth_bytes), style=growth_style),
                _fmt_bytes(r),
                _fmt_bytes(d.bytes_after),
                f"{d.growth_pct:.1f}%",
                f"{d.files_delta:+d}",
            )
        console.print(gt)
    else:
        console.print("\n[dim]No directory growth detected.[/dim]")

    # -- Growth Drilldown (if anomalies found) -------------------------------
    if report.anomalies:
        _print_drilldown(console, report)

    console.print()


def _print_drilldown(console: Any, report: Report) -> None:
    """Print a merged tree showing paths from root to each attributed cause."""
    from rich.tree import Tree

    entries_by_path = {e.path: e for e in report.diff.entries}
    root_path = report.diff.snapshot_old.root_path

    seen_targets: set[str] = set()
    chains: list[list[DirDiff]] = []
    for anomaly in report.anomalies:
        target = anomaly.attributed_path
        if target in seen_targets:
            continue
        seen_targets.add(target)
        chain = _build_chain(target, root_path, entries_by_path)
        if len(chain) > 1:
            chains.append(chain)

    if not chains:
        return

    console.print()
    console.print("[bold]Growth Attribution[/bold]")

    all_paths: set[str] = set()
    leaf_paths: set[str] = set()
    for chain in chains:
        for entry in chain:
            all_paths.add(entry.path)
        leaf_paths.add(chain[-1].path)

    root_entry = chains[0][0]
    root_path_esc = _esc(root_entry.path)
    tree = Tree(
        f"[bold]{root_path_esc}[/bold]  "
        f"[red]+{_fmt_bytes(root_entry.growth_bytes)}[/red]  "
        f"({_fmt_bytes(root_entry.bytes_after)} total)",
    )

    node_map: dict[str, Any] = {root_entry.path: tree}

    for path in sorted(all_paths - {root_entry.path}):
        entry = entries_by_path.get(path)
        if entry is None:
            continue
        parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
        if not parent_path:
            parent_path = root_entry.path
        parent_node = node_map.get(parent_path, tree)
        is_leaf = path in leaf_paths
        path_esc = _esc(path)
        if is_leaf:
            label = (
                f"[bold cyan]{path_esc}[/bold cyan]  "
                f"[red]+{_fmt_bytes(entry.growth_bytes)}[/red]  "
                f"({_fmt_bytes(entry.bytes_after)} total, "
                f"{entry.files_delta:+d} files)"
                "  [bold cyan]\u2190 root cause[/bold cyan]"
            )
        else:
            label = (
                f"{path_esc}  "
                f"[red]+{_fmt_bytes(entry.growth_bytes)}[/red]  "
                f"({_fmt_bytes(entry.bytes_after)} total, "
                f"{entry.files_delta:+d} files)"
            )
        node_map[path] = parent_node.add(label)

    console.print(tree)


def _build_chain(
    target: str,
    root: str,
    entries: dict[str, DirDiff],
) -> list[DirDiff]:
    """Build the chain of DirDiff entries from root to the target path."""
    parts: list[str] = []
    current = target
    while current and current != root:
        parts.append(current)
        parent = current.rsplit("/", 1)[0] if "/" in current else ""
        if parent == current:
            break
        current = parent
    if root not in parts:
        parts.append(root)
    parts.reverse()

    return [entries[p] for p in parts if p in entries]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Escape Rich markup characters in a string."""
    return text.replace("[", "\\[")


def _anomaly_dict(a: Anomaly) -> dict[str, Any]:
    d: dict[str, Any] = {
        "path": a.path,
        "severity": a.severity.value,
        "rule": a.rule,
        "message": a.message,
        "growth_bytes": a.growth_bytes,
        "growth_rate_bytes_per_hour": a.growth_rate_bytes_per_hour,
        "growth_human": _fmt_bytes(a.growth_bytes),
        "rate_human": _fmt_bytes(a.growth_rate_bytes_per_hour) + "/h",
        "attributed_path": a.attributed_path,
    }
    if a.sldd_db_bytes > 0:
        d["sldd_db_bytes"] = a.sldd_db_bytes
        d["sldd_db_human"] = _fmt_bytes(a.sldd_db_bytes)
    return d


def group_anomalies_by_path(
    anomalies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge anomalies that share the same path into a single row.

    Keeps the worst severity, combines rule names, and picks the most
    informative message.
    """
    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    groups: dict[str, dict[str, Any]] = {}

    for a in anomalies:
        path = a["path"]
        if path not in groups:
            groups[path] = {**a, "rules": [a["rule"]]}
        else:
            g = groups[path]
            g["rules"].append(a["rule"])
            if sev_rank.get(a["severity"], 9) < sev_rank.get(g["severity"], 9):
                g["severity"] = a["severity"]
                g["message"] = a["message"]

    result = []
    for g in groups.values():
        g["rule"] = ", ".join(sorted(set(g["rules"])))
        del g["rules"]
        result.append(g)

    result.sort(key=lambda x: (sev_rank.get(x["severity"], 9), -x["growth_bytes"]))
    return result


def _diff_entry_dict(d: DirDiff, elapsed_seconds: float) -> dict[str, Any]:
    hours = elapsed_seconds / 3600 if elapsed_seconds > 0 else 1.0
    return {
        "path": d.path,
        "bytes_before": d.bytes_before,
        "bytes_after": d.bytes_after,
        "growth_bytes": d.growth_bytes,
        "growth_pct": round(d.growth_pct, 2),
        "growth_human": _fmt_bytes(d.growth_bytes),
        "rate_bytes_per_hour": d.growth_bytes / hours,
        "rate_human": _fmt_bytes(d.growth_bytes / hours) + "/h",
        "files_before": d.files_before,
        "files_after": d.files_after,
        "files_delta": d.files_delta,
        "depth": d.depth,
    }


def _fmt_bytes(n: float) -> str:
    sign = "-" if n < 0 else ""
    abs_n = abs(n)
    if abs_n >= 1024 ** 3:
        return f"{sign}{abs_n / 1024**3:.2f} GB"
    if abs_n >= 1024 ** 2:
        return f"{sign}{abs_n / 1024**2:.1f} MB"
    if abs_n >= 1024:
        return f"{sign}{abs_n / 1024:.1f} KB"
    return f"{sign}{abs_n:.0f} B"


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m {seconds % 60:.0f}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"
