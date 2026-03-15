"""Anomaly detection — threshold, statistical, and depth-aware attribution."""

from __future__ import annotations

import math
from pathlib import Path

from sldd.models import Anomaly, DetectConfig, DirDiff, Severity, SnapshotDiff
from sldd.platform_utils import normalize_path
from sldd.storage import SnapshotStore


def _path_contains_db(entry_path: str, db_path: str) -> bool:
    """True if the entry path contains the directory where the sldd DB file lives."""
    norm_entry = normalize_path(entry_path).rstrip("/") or "/"
    norm_db_dir = normalize_path(str(Path(db_path).resolve().parent)).rstrip("/")
    if norm_entry == "/":
        return True
    return norm_entry == norm_db_dir or norm_db_dir.startswith(norm_entry + "/")


def detect_anomalies(
    diff: SnapshotDiff,
    store: SnapshotStore,
    config: DetectConfig | None = None,
) -> list[Anomaly]:
    """Run all detection rules against a diff and return anomalies sorted by severity."""
    cfg = config or DetectConfig()
    anomalies: list[Anomaly] = []
    hours = diff.elapsed_seconds / 3600 if diff.elapsed_seconds > 0 else 1.0

    for entry in diff.entries:
        if entry.bytes_after < cfg.min_size_bytes:
            continue

        growth_bytes = entry.growth_bytes
        sldd_db_bytes = 0
        if _path_contains_db(entry.path, store._db_path):
            try:
                db_size = store.db_size_bytes()
                growth_bytes = max(0, entry.growth_bytes - db_size)
                sldd_db_bytes = min(entry.growth_bytes, db_size)
                if growth_bytes == 0:
                    continue  # only DB changing, don't flag
            except OSError:
                pass

        rate = growth_bytes / hours if hours > 0 else 0.0
        attributed = _attribute_growth(diff, entry)

        # Rule 1: absolute growth threshold
        if growth_bytes >= cfg.abs_threshold_bytes:
            is_extreme = growth_bytes >= cfg.abs_threshold_bytes * 3
            sev = Severity.CRITICAL if is_extreme else Severity.WARNING
            thresh_str = _fmt(cfg.abs_threshold_bytes)
            anomalies.append(Anomaly(
                path=entry.path,
                severity=sev,
                rule="abs_threshold",
                message=f"Grew by {_fmt(growth_bytes)} (threshold: {thresh_str})",
                growth_bytes=growth_bytes,
                growth_rate_bytes_per_hour=rate,
                attributed_path=attributed,
                sldd_db_bytes=sldd_db_bytes,
            ))

        # Rule 2: growth rate threshold
        if rate >= cfg.growth_rate_threshold_bytes_per_hour:
            is_extreme = rate >= cfg.growth_rate_threshold_bytes_per_hour * 3
            sev = Severity.CRITICAL if is_extreme else Severity.WARNING
            thresh_rate = _fmt(cfg.growth_rate_threshold_bytes_per_hour)
            anomalies.append(Anomaly(
                path=entry.path,
                severity=sev,
                rule="growth_rate",
                message=f"Growing at {_fmt(rate)}/h (threshold: {thresh_rate}/h)",
                growth_bytes=growth_bytes,
                growth_rate_bytes_per_hour=rate,
                attributed_path=attributed,
                sldd_db_bytes=sldd_db_bytes,
            ))

        # Rule 3: relative growth (doubled, tripled, etc.)
        above_min = entry.bytes_before > cfg.min_size_bytes
        growth_pct = (growth_bytes / entry.bytes_before * 100) if entry.bytes_before > 0 else 0
        if above_min and growth_pct >= cfg.relative_threshold_pct:
            sev = Severity.CRITICAL if growth_pct >= 300 else Severity.WARNING
            anomalies.append(Anomaly(
                path=entry.path,
                severity=sev,
                rule="relative_growth",
                message=(
                    f"Grew {growth_pct:.0f}% "
                    f"(threshold: {cfg.relative_threshold_pct:.0f}%)"
                ),
                growth_bytes=growth_bytes,
                growth_rate_bytes_per_hour=rate,
                attributed_path=attributed,
                sldd_db_bytes=sldd_db_bytes,
            ))

        # Rule 4: statistical anomaly (needs history)
        stat_anomaly = _check_statistical(entry, store, cfg, rate, attributed, growth_bytes, sldd_db_bytes)
        if stat_anomaly:
            anomalies.append(stat_anomaly)

    anomalies = _deduplicate(anomalies)
    anomalies.sort(key=lambda a: (
        0 if a.severity == Severity.CRITICAL else 1 if a.severity == Severity.WARNING else 2,
        -a.growth_bytes,
    ))
    return anomalies


def _check_statistical(
    entry: DirDiff,
    store: SnapshotStore,
    cfg: DetectConfig,
    rate: float,
    attributed: str,
    growth_bytes: int,
    sldd_db_bytes: int = 0,
) -> Anomaly | None:
    """Check if this entry's growth deviates significantly from its historical mean."""
    history = store.get_path_history(entry.path, limit=cfg.min_snapshots_for_stats + 5)
    if len(history) < cfg.min_snapshots_for_stats:
        return None

    sizes = [row[2] for row in history]
    deltas: list[float] = []
    for i in range(len(sizes) - 1):
        deltas.append(float(sizes[i] - sizes[i + 1]))

    if len(deltas) < 2:
        return None

    mean = sum(deltas) / len(deltas)
    variance = sum((d - mean) ** 2 for d in deltas) / len(deltas)
    stddev = math.sqrt(variance) if variance > 0 else 0

    if stddev == 0:
        return None

    current_delta = float(growth_bytes)
    z_score = (current_delta - mean) / stddev

    if z_score >= cfg.stddev_factor:
        sev = Severity.CRITICAL if z_score >= cfg.stddev_factor * 2 else Severity.WARNING
        return Anomaly(
            path=entry.path,
            severity=sev,
            rule="statistical",
            message=(
                f"Growth is {z_score:.1f}σ above historical mean "
                f"(threshold: {cfg.stddev_factor:.1f}σ)"
            ),
            growth_bytes=growth_bytes,
            growth_rate_bytes_per_hour=rate,
            attributed_path=attributed,
            sldd_db_bytes=sldd_db_bytes,
        )
    return None


def _attribute_growth(diff: SnapshotDiff, entry: DirDiff) -> str:
    """Walk down to find the deepest child responsible for the majority of growth.

    If a single child accounts for >= concentration threshold of the parent's
    growth, drill into that child. Repeat until no single child dominates.
    """
    concentration = 80.0
    current = entry
    visited: set[str] = set()

    while True:
        visited.add(current.path)
        prefix = current.path.rstrip("/") + "/"
        children = [
            e for e in diff.entries
            if e.path.startswith(prefix)
            and e.depth == current.depth + 1
            and e.path not in visited
        ]
        if not children:
            break

        children.sort(key=lambda c: c.growth_bytes, reverse=True)
        top_child = children[0]

        if current.growth_bytes <= 0:
            break
        share = (top_child.growth_bytes / current.growth_bytes) * 100
        if share >= concentration and top_child.growth_bytes > 0:
            current = top_child
        else:
            break

    return current.path


def _deduplicate(anomalies: list[Anomaly]) -> list[Anomaly]:
    """Remove redundant anomalies.

    1. If the same (path, rule) appears, keep only the highest severity.
    2. If multiple paths share the same (attributed_path, rule), keep only the
       deepest one — the ancestors are just aggregating the same root cause.
    """
    severity_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}

    seen_path_rule: dict[tuple[str, str], Anomaly] = {}
    for a in anomalies:
        key = (a.path, a.rule)
        existing = seen_path_rule.get(key)
        if existing is None or severity_order[a.severity] < severity_order[existing.severity]:
            seen_path_rule[key] = a

    deduped = list(seen_path_rule.values())

    seen_attr_rule: dict[tuple[str, str], Anomaly] = {}
    for a in deduped:
        key = (a.attributed_path, a.rule)
        existing = seen_attr_rule.get(key)
        if existing is None:
            seen_attr_rule[key] = a
        else:
            e_depth = existing.path.count("/")
            a_depth = a.path.count("/")
            e_sev = severity_order[existing.severity]
            a_sev = severity_order[a.severity]
            if a_sev < e_sev or (a_sev == e_sev and a_depth > e_depth):
                seen_attr_rule[key] = a

    return list(seen_attr_rule.values())


def _fmt(n: float) -> str:
    abs_n = abs(n)
    if abs_n >= 1024 ** 3:
        return f"{n / 1024**3:.1f} GB"
    if abs_n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MB"
    if abs_n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n:.0f} B"
