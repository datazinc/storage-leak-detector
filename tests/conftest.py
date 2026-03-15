"""Shared fixtures for the sldd test suite."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from sldd.api import SLDD
from sldd.models import DirEntry, ScanConfig, Snapshot
from sldd.storage import SnapshotStore


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """A temporary directory pre-populated with a known file tree.

    Layout:
        root/
        ├── a/
        │   ├── file1.txt   (100 bytes)
        │   └── b/
        │       └── file2.txt (200 bytes)
        ├── c/
        │   └── file3.txt   (50 bytes)
        └── file0.txt        (10 bytes)
    """
    root = tmp_path / "root"
    root.mkdir()
    (root / "file0.txt").write_bytes(b"x" * 10)

    a = root / "a"
    a.mkdir()
    (a / "file1.txt").write_bytes(b"x" * 100)

    b = a / "b"
    b.mkdir()
    (b / "file2.txt").write_bytes(b"x" * 200)

    c = root / "c"
    c.mkdir()
    (c / "file3.txt").write_bytes(b"x" * 50)

    return root


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture()
def store(db_path: str) -> SnapshotStore:
    s = SnapshotStore(db_path)
    s.open()
    yield s
    s.close()


@pytest.fixture()
def api(db_path: str, tmp_dir: Path) -> SLDD:
    cfg = ScanConfig(root=str(tmp_dir), excludes=[], db_path=db_path)
    a = SLDD(db_path=db_path, scan_config=cfg)
    a.open()
    yield a
    a.close()


def make_snapshot(
    entries: list[DirEntry],
    *,
    snap_id: int | None = None,
    root: str = "/test",
    label: str = "",
    timestamp: _dt.datetime | None = None,
) -> Snapshot:
    """Helper to build a Snapshot for tests."""
    return Snapshot(
        id=snap_id,
        timestamp=timestamp or _dt.datetime.now(_dt.timezone.utc),
        root_path=root,
        label=label,
        entries=entries,
    )
