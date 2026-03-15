"""Tests for the CLI — uses click's test runner for safety."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from sldd.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    """A temp dir with files to scan, plus a db path."""
    root = tmp_path / "scanroot"
    root.mkdir()
    (root / "file.txt").write_bytes(b"x" * 100)
    sub = root / "subdir"
    sub.mkdir()
    (sub / "data.bin").write_bytes(b"y" * 500)
    return tmp_path


class TestSnapshotCommand:
    def test_take_snapshot(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        result = runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        assert result.exit_code == 0
        assert "Snapshot #1 saved" in result.output

    def test_take_two_snapshots(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        result = runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        assert result.exit_code == 0
        assert "Snapshot #2 saved" in result.output


class TestLsCommand:
    def test_empty(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        result = runner.invoke(main, ["ls", "--db", db])
        assert result.exit_code == 0
        assert "No snapshots" in result.output

    def test_with_snapshots(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        result = runner.invoke(main, ["ls", "--db", db])
        assert result.exit_code == 0
        assert "1" in result.output  # snapshot ID


class TestDiffCommand:
    def test_diff_needs_two(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        result = runner.invoke(main, ["diff", "--db", db])
        assert result.exit_code != 0
        assert "Need at least 2" in result.output

    def test_diff_two_snapshots(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])

        # Add growth
        (work_dir / "scanroot" / "growth.dat").write_bytes(b"z" * 2000)

        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        result = runner.invoke(main, ["diff", "--db", db])
        assert result.exit_code == 0
        assert "Top Growing" in result.output

    def test_diff_json(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        (work_dir / "scanroot" / "growth.dat").write_bytes(b"z" * 2000)
        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        result = runner.invoke(main, ["diff", "--db", db, "--json"])
        assert result.exit_code == 0
        assert '"top_growers"' in result.output


class TestDrillCommand:
    def test_drill(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])

        from sldd.platform_utils import normalize_path
        norm_root = normalize_path(os.path.realpath(root))
        result = runner.invoke(main, ["drill", "--db", db, "--path", norm_root])
        assert result.exit_code == 0


class TestPruneCommand:
    def test_prune(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        for _ in range(4):
            runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        result = runner.invoke(main, ["prune", "--db", db, "--keep", "2"])
        assert result.exit_code == 0
        assert "Pruned 2" in result.output


class TestRmCommand:
    def test_rm(self, runner: CliRunner, work_dir: Path) -> None:
        db = str(work_dir / "test.db")
        root = str(work_dir / "scanroot")
        runner.invoke(main, ["snapshot", "--root", root, "--db", db, "--exclude", "/proc"])
        result = runner.invoke(main, ["rm", "--db", db, "1"])
        assert result.exit_code == 0
        assert "deleted" in result.output
