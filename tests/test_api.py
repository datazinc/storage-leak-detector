"""Tests for the public API facade."""

from __future__ import annotations

from pathlib import Path

from sldd.api import SLDD
from sldd.models import ScanConfig


class TestAPISnapshot:
    def test_take_and_list(self, api: SLDD) -> None:
        snap = api.take_snapshot()
        assert snap.id is not None
        assert len(snap.entries) > 0

        listed = api.list_snapshots()
        assert len(listed) == 1
        assert listed[0].id == snap.id

    def test_take_two_and_diff(self, api: SLDD, tmp_dir: Path) -> None:
        s1 = api.take_snapshot(label="before")

        # Add a big file
        (tmp_dir / "big.bin").write_bytes(b"x" * 10_000)

        s2 = api.take_snapshot(label="after")

        diff = api.diff(s1.id, s2.id)
        assert diff is not None
        assert diff.total_growth_bytes > 0

    def test_full_pipeline(self, api: SLDD, tmp_dir: Path) -> None:
        s1 = api.take_snapshot()

        (tmp_dir / "c" / "growth.dat").write_bytes(b"x" * 50_000)

        s2 = api.take_snapshot()

        report = api.diff_and_detect(s1.id, s2.id)
        assert report is not None
        assert len(report.top_growers) > 0

        d = api.report_dict(report)
        assert "anomalies" in d
        assert "top_growers" in d
        assert d["total_growth_bytes"] > 0

        j = api.report_json(report)
        assert '"top_growers"' in j


class TestAPIDrillDown:
    def test_drill(self, api: SLDD, tmp_dir: Path) -> None:
        snap = api.take_snapshot()

        from sldd.platform_utils import normalize_path
        root_path = normalize_path(str(tmp_dir))
        children = api.drill(snap.id, root_path)
        child_paths = {e.path for e in children}
        assert normalize_path(str(tmp_dir / "a")) in child_paths

    def test_drill_nonexistent(self, api: SLDD) -> None:
        snap = api.take_snapshot()
        children = api.drill(snap.id, "/nonexistent")
        assert children == []


class TestAPIHistory:
    def test_path_history(self, api: SLDD, tmp_dir: Path) -> None:
        api.take_snapshot()

        (tmp_dir / "a" / "extra.txt").write_bytes(b"y" * 500)
        api.take_snapshot()

        from sldd.platform_utils import normalize_path
        a_path = normalize_path(str(tmp_dir / "a"))
        history = api.path_history(a_path)
        assert len(history) == 2
        assert history[0]["total_bytes"] > history[1]["total_bytes"]


class TestAPIPrune:
    def test_prune(self, api: SLDD) -> None:
        for _ in range(5):
            api.take_snapshot()

        deleted = api.prune(keep=2)
        assert deleted == 3
        assert len(api.list_snapshots()) == 2


class TestAPIContextManager:
    def test_context_manager(self, db_path: str, tmp_dir: Path) -> None:
        cfg = ScanConfig(root=str(tmp_dir), excludes=[], db_path=db_path)
        with SLDD(db_path=db_path, scan_config=cfg) as a:
            snap = a.take_snapshot()
            assert snap.id is not None
