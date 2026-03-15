"""Tests for report generation."""

from __future__ import annotations

import datetime as _dt
import json

from sldd.models import (
    Anomaly,
    DirDiff,
    Report,
    Severity,
    SnapshotDiff,
)
from sldd.report import report_to_dict, report_to_json
from tests.conftest import make_snapshot


def _sample_report() -> Report:
    old = make_snapshot([], snap_id=1, timestamp=_dt.datetime(2024, 1, 1, 10, 0, 0, tzinfo=_dt.timezone.utc))
    new = make_snapshot([], snap_id=2, timestamp=_dt.datetime(2024, 1, 1, 11, 0, 0, tzinfo=_dt.timezone.utc))

    diff_entries = [
        DirDiff(path="/root/logs", bytes_before=1000, bytes_after=5000, growth_bytes=4000, growth_pct=400.0, files_before=10, files_after=20, files_delta=10, depth=1),
        DirDiff(path="/root/data", bytes_before=500, bytes_after=600, growth_bytes=100, growth_pct=20.0, files_before=5, files_after=5, files_delta=0, depth=1),
    ]

    diff = SnapshotDiff(
        snapshot_old=old,
        snapshot_new=new,
        elapsed_seconds=3600.0,
        entries=diff_entries,
        total_growth_bytes=4100,
    )

    anomalies = [
        Anomaly(
            path="/root/logs",
            severity=Severity.WARNING,
            rule="abs_threshold",
            message="Grew a lot",
            growth_bytes=4000,
            growth_rate_bytes_per_hour=4000.0,
            attributed_path="/root/logs/access.log",
        ),
    ]

    return Report(
        generated_at=_dt.datetime(2024, 1, 1, 11, 0, 5, tzinfo=_dt.timezone.utc),
        diff=diff,
        anomalies=anomalies,
        top_growers=diff_entries,
        top_shrinkers=(),
    )


class TestReportToDict:
    def test_structure(self) -> None:
        d = report_to_dict(_sample_report())
        assert "generated_at" in d
        assert "snapshot_old" in d
        assert "snapshot_new" in d
        assert "anomalies" in d
        assert "top_growers" in d
        assert d["total_growth_bytes"] == 4100

    def test_anomaly_fields(self) -> None:
        d = report_to_dict(_sample_report())
        a = d["anomalies"][0]
        assert a["path"] == "/root/logs"
        assert a["severity"] == "warning"
        assert a["attributed_path"] == "/root/logs/access.log"

    def test_grower_fields(self) -> None:
        d = report_to_dict(_sample_report())
        g = d["top_growers"][0]
        assert g["growth_bytes"] == 4000
        assert "growth_human" in g
        assert "rate_human" in g


class TestReportToJson:
    def test_valid_json(self) -> None:
        j = report_to_json(_sample_report())
        parsed = json.loads(j)
        assert parsed["total_growth_bytes"] == 4100

    def test_roundtrip(self) -> None:
        report = _sample_report()
        d1 = report_to_dict(report)
        d2 = json.loads(report_to_json(report))
        assert d1 == d2
