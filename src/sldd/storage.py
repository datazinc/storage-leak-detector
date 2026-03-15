"""SQLite-backed storage — repository pattern so any UI can swap in its own backend."""

from __future__ import annotations

import datetime as _dt
import sqlite3
import threading
from pathlib import Path

from sldd.models import DirEntry, Snapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    root_path   TEXT    NOT NULL,
    label       TEXT    NOT NULL DEFAULT '',
    scan_depth  INTEGER
);

CREATE TABLE IF NOT EXISTS entries (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path        TEXT    NOT NULL,
    total_bytes INTEGER NOT NULL,
    file_count  INTEGER NOT NULL,
    dir_count   INTEGER NOT NULL DEFAULT 0,
    depth       INTEGER NOT NULL,
    error       TEXT,
    PRIMARY KEY (snapshot_id, path)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_entries_snapshot ON entries(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_entries_path     ON entries(path);
CREATE INDEX IF NOT EXISTS idx_entries_size     ON entries(snapshot_id, total_bytes DESC);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS deletions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    bytes_freed INTEGER NOT NULL DEFAULT 0,
    was_dir     INTEGER NOT NULL DEFAULT 0,
    success     INTEGER NOT NULL DEFAULT 1,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS path_status (
    path                TEXT    PRIMARY KEY,
    status              TEXT    NOT NULL DEFAULT 'active',
    last_bytes          INTEGER NOT NULL DEFAULT 0,
    last_file_count     INTEGER NOT NULL DEFAULT 0,
    depth               INTEGER NOT NULL DEFAULT 0,
    consecutive_stable  INTEGER NOT NULL DEFAULT 0,
    last_growth_bytes   INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT    NOT NULL
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_path_status_status ON path_status(status);

CREATE TABLE IF NOT EXISTS path_io_watch (
    path                TEXT PRIMARY KEY,
    started_at         TEXT NOT NULL,
    duration_minutes    INTEGER NOT NULL,
    sample_interval_sec INTEGER NOT NULL DEFAULT 60
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS path_io_samples (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    path                 TEXT NOT NULL,
    timestamp            TEXT NOT NULL,
    pid                  INTEGER NOT NULL,
    process_name         TEXT NOT NULL,
    read_bytes           INTEGER NOT NULL DEFAULT 0,
    write_bytes          INTEGER NOT NULL DEFAULT 0,
    open_files_under_path INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_path_io_samples_path_ts ON path_io_samples(path, timestamp);
"""


class StorageError(Exception):
    pass


class SnapshotStore:
    """Persist and query snapshots.

    Designed as a thin repository: all public methods return domain models,
    making it trivial to replace with a REST client for a web UI.
    """

    def __init__(
        self,
        db_path: str | Path = "snapshots.db",
        *,
        check_same_thread: bool = True,
    ) -> None:
        self._db_path = str(db_path)
        self._check_same_thread = check_same_thread
        self._conn: sqlite3.Connection | None = None
        self._schema_verified = False
        self._lock = threading.RLock()  # reentrant: get_latest_snapshot calls get_snapshot

    # -- lifecycle -----------------------------------------------------------

    def _apply_schema(self) -> None:
        """Create or recreate all tables. Idempotent (uses IF NOT EXISTS)."""
        if self._conn is None:
            raise StorageError("Store is not open. Call open() first.")
        self._conn.executescript(_SCHEMA)
        self._migrate_add_scan_depth()
        self._migrate_add_path_io_tables()
        self._schema_verified = True

    def _migrate_add_scan_depth(self) -> None:
        """Add scan_depth column to snapshots if missing (for existing DBs)."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(snapshots)").fetchall()]
        if "scan_depth" not in cols:
            self._conn.execute("ALTER TABLE snapshots ADD COLUMN scan_depth INTEGER")

    def _migrate_add_path_io_tables(self) -> None:
        """Create path_io tables if missing (for existing DBs)."""
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='path_io_samples'"
        ).fetchone()
        if row is None:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS path_io_watch (
                    path                TEXT PRIMARY KEY,
                    started_at         TEXT NOT NULL,
                    duration_minutes    INTEGER NOT NULL,
                    sample_interval_sec INTEGER NOT NULL DEFAULT 60
                ) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS path_io_samples (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    path                 TEXT NOT NULL,
                    timestamp            TEXT NOT NULL,
                    pid                  INTEGER NOT NULL,
                    process_name         TEXT NOT NULL,
                    read_bytes           INTEGER NOT NULL DEFAULT 0,
                    write_bytes          INTEGER NOT NULL DEFAULT 0,
                    open_files_under_path INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_path_io_samples_path_ts
                    ON path_io_samples(path, timestamp);
            """)

    def _ensure_schema(self) -> None:
        """Ensure tables exist; create them if missing (e.g. after reset or corrupt DB)."""
        if self._conn is None:
            return
        try:
            row = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'"
            ).fetchone()
        except sqlite3.OperationalError:
            self._apply_schema()
            return
        if row is None:
            self._apply_schema()
        else:
            self._schema_verified = True

    def open(self) -> None:
        self._conn = sqlite3.connect(
            self._db_path,
            isolation_level="DEFERRED",
            check_same_thread=self._check_same_thread,
        )
        # Tolerate invalid UTF-8 in text columns (e.g. process_name from psutil)
        self._conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA cache_size=-16000")  # 16 MB — lower to reduce SIGSEGV risk
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.execute("PRAGMA mmap_size=67108864")  # 64 MB mmap for read perf
        self._apply_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SnapshotStore:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StorageError("Store is not open. Call open() or use as context manager.")
        if not self._schema_verified:
            self._ensure_schema()
        return self._conn

    # -- write ---------------------------------------------------------------

    def save_snapshot(self, snapshot: Snapshot) -> Snapshot:
        """Insert a snapshot and all its entries. Returns the snapshot with its assigned id."""
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO snapshots (timestamp, root_path, label, scan_depth) VALUES (?, ?, ?, ?)",
                (
                    snapshot.timestamp.isoformat(),
                    snapshot.root_path,
                    snapshot.label,
                    snapshot.scan_depth,
                ),
            )
            snap_id = cur.lastrowid
            assert snap_id is not None

            self.conn.executemany(
                "INSERT INTO entries "
                "(snapshot_id, path, total_bytes, file_count, dir_count, depth, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (snap_id, e.path, e.total_bytes, e.file_count, e.dir_count, e.depth, e.error)
                    for e in snapshot.entries
                ],
            )
            self.conn.commit()
            return Snapshot(
                id=snap_id,
                timestamp=snapshot.timestamp,
                root_path=snapshot.root_path,
                label=snapshot.label,
                entries=snapshot.entries,
                scan_depth=snapshot.scan_depth,
            )

    def delete_snapshot(self, snapshot_id: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM entries WHERE snapshot_id = ?", (snapshot_id,))
            self.conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
            self.conn.commit()

    def prune_old_snapshots(self, keep: int) -> int:
        """Delete oldest snapshots, keeping *keep* most recent. Returns count deleted."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id FROM snapshots ORDER BY timestamp DESC"
            ).fetchall()
            to_delete = [r[0] for r in rows[keep:]]
            for sid in to_delete:
                self.conn.execute("DELETE FROM entries WHERE snapshot_id = ?", (sid,))
                self.conn.execute("DELETE FROM snapshots WHERE id = ?", (sid,))
            self.conn.commit()
            return len(to_delete)

    # -- read ----------------------------------------------------------------

    def list_snapshots(
        self,
        limit: int = 50,
        scan_depth: int | None = None,
        root_path: str | None = None,
    ) -> list[Snapshot]:
        """Return snapshot metadata (without entries) ordered newest-first.
        If scan_depth is set, only return snapshots with that depth.
        If root_path is set, only return snapshots with that root (same watch scope).
        """
        with self._lock:
            conditions = []
            params: list[object] = []
            if scan_depth is not None:
                conditions.append("scan_depth = ?")
                params.append(scan_depth)
            if root_path is not None:
                conditions.append("root_path = ?")
                params.append(root_path)
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)
            rows = self.conn.execute(
                "SELECT id, timestamp, root_path, label, scan_depth "
                f"FROM snapshots{where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
            return [
                Snapshot(
                    id=r[0],
                    timestamp=_dt.datetime.fromisoformat(r[1]),
                    root_path=r[2],
                    label=r[3],
                    entries=[],
                    scan_depth=r[4] if len(r) > 4 else None,
                )
                for r in rows
            ]

    def get_snapshot_depths(self) -> list[tuple[int, int]]:
        """Return (scan_depth, count) for each depth that has snapshots."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT scan_depth, COUNT(*) FROM snapshots "
                "WHERE scan_depth IS NOT NULL GROUP BY scan_depth ORDER BY scan_depth"
            ).fetchall()
            return [(r[0], r[1]) for r in rows]

    def get_snapshot(self, snapshot_id: int, *, with_entries: bool = False) -> Snapshot | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT id, timestamp, root_path, label, scan_depth FROM snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                return None
            entries: list[DirEntry] = []
            if with_entries:
                entries = self._load_entries(snapshot_id)
            return Snapshot(
                id=row[0],
                timestamp=_dt.datetime.fromisoformat(row[1]),
                root_path=row[2],
                label=row[3],
                entries=entries,
                scan_depth=row[4] if len(row) > 4 else None,
            )

    def get_latest_snapshot(self, *, with_entries: bool = False) -> Snapshot | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM snapshots ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            return self.get_snapshot(row[0], with_entries=with_entries)

    def get_entries(self, snapshot_id: int) -> list[DirEntry]:
        with self._lock:
            return self._load_entries(snapshot_id)

    def get_entry(self, snapshot_id: int, path: str) -> DirEntry | None:
        with self._lock:
            row = self.conn.execute(
            "SELECT path, total_bytes, file_count, dir_count, depth, error "
                "FROM entries WHERE snapshot_id = ? AND path = ?",
                (snapshot_id, path),
            ).fetchone()
            if row is None:
                return None
            return DirEntry(
                path=row[0], total_bytes=row[1], file_count=row[2],
                dir_count=row[3], depth=row[4], error=row[5],
            )

    def get_children(self, snapshot_id: int, parent_path: str, depth: int) -> list[DirEntry]:
        """Get direct children of *parent_path* at *depth* + 1."""
        with self._lock:
            prefix = parent_path.rstrip("/") + "/"
            rows = self.conn.execute(
            "SELECT path, total_bytes, file_count, dir_count, depth, error "
            "FROM entries WHERE snapshot_id = ? AND path LIKE ? AND depth = ? "
                "ORDER BY total_bytes DESC",
                (snapshot_id, prefix + "%", depth + 1),
            ).fetchall()
            return [
                DirEntry(path=r[0], total_bytes=r[1], file_count=r[2],
                         dir_count=r[3], depth=r[4], error=r[5])
                for r in rows
            ]

    def get_top_dirs(self, snapshot_id: int, limit: int = 20) -> list[DirEntry]:
        with self._lock:
            rows = self.conn.execute(
            "SELECT path, total_bytes, file_count, dir_count, depth, error "
                "FROM entries WHERE snapshot_id = ? ORDER BY total_bytes DESC LIMIT ?",
                (snapshot_id, limit),
            ).fetchall()
            return [
                DirEntry(path=r[0], total_bytes=r[1], file_count=r[2],
                         dir_count=r[3], depth=r[4], error=r[5])
                for r in rows
            ]

    # -- diff helpers (used by diff engine) ----------------------------------

    def diff_entries_raw(
        self,
        old_id: int,
        new_id: int,
        *,
        limit: int = 500,
        min_growth: int = 0,
        path_prefix: str | None = None,
    ) -> list[tuple[str, int, int, int, int, int, int]]:
        """Return raw diff tuples (path, old_bytes, new_bytes, growth, ...).

        Sorted by absolute growth descending.
        If path_prefix is set, only return entries under that path (prefix or children).
        """
        with self._lock:
            if path_prefix:
                prefix = path_prefix.rstrip("/")
                if not prefix:
                    prefix = "/"
                # path = prefix OR path LIKE prefix + '/%'
                path_clause = "AND (n.path = ? OR n.path LIKE ?)"
                like_pattern = prefix + "/%"
                params = (old_id, new_id, min_growth, prefix, like_pattern, limit)
            else:
                path_clause = ""
                params = (old_id, new_id, min_growth, limit)

            rows = self.conn.execute(
                f"""
                SELECT
                    n.path,
                    COALESCE(o.total_bytes, 0),
                    n.total_bytes,
                    n.total_bytes - COALESCE(o.total_bytes, 0),
                    COALESCE(o.file_count, 0),
                    n.file_count,
                    n.depth
                FROM entries n
                LEFT JOIN entries o ON o.path = n.path AND o.snapshot_id = ?
                WHERE n.snapshot_id = ?
                  AND (n.total_bytes - COALESCE(o.total_bytes, 0)) >= ?
                  {path_clause}
                ORDER BY (n.total_bytes - COALESCE(o.total_bytes, 0)) DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return rows

    def get_path_history(
        self,
        path: str,
        *,
        limit: int = 50,
        scan_depth: int | None | str = None,
    ) -> list[tuple[int, str, int, int]]:
        """Return (snapshot_id, timestamp, total_bytes, file_count) for a given path over time.

        If scan_depth is an int, only include snapshots with that depth.
        If scan_depth is "legacy", only include snapshots with scan_depth IS NULL.
        If scan_depth is None (not provided), no filter.
        """
        with self._lock:
            if scan_depth == "legacy":
                rows = self.conn.execute(
                    """
                    SELECT s.id, s.timestamp, e.total_bytes, e.file_count
                    FROM entries e
                    JOIN snapshots s ON s.id = e.snapshot_id
                    WHERE e.path = ? AND s.scan_depth IS NULL
                    ORDER BY s.timestamp DESC
                    LIMIT ?
                    """,
                    (path, limit),
                ).fetchall()
            elif isinstance(scan_depth, int):
                rows = self.conn.execute(
                    """
                    SELECT s.id, s.timestamp, e.total_bytes, e.file_count
                    FROM entries e
                    JOIN snapshots s ON s.id = e.snapshot_id
                    WHERE e.path = ? AND s.scan_depth = ?
                    ORDER BY s.timestamp DESC
                    LIMIT ?
                    """,
                    (path, scan_depth, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """
                    SELECT s.id, s.timestamp, e.total_bytes, e.file_count
                    FROM entries e
                    JOIN snapshots s ON s.id = e.snapshot_id
                    WHERE e.path = ?
                    ORDER BY s.timestamp DESC
                    LIMIT ?
                    """,
                    (path, limit),
                ).fetchall()
            return rows

    # -- settings ------------------------------------------------------------

    def get_settings(self) -> dict[str, str]:
        with self._lock:
            rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
            return {r[0]: r[1] for r in rows}

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else default

    def save_setting(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
            self.conn.commit()

    def save_settings(self, settings: dict[str, str]) -> None:
        with self._lock:
            for key, value in settings.items():
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
            self.conn.commit()

    # -- deletion audit log --------------------------------------------------

    def log_deletion(
        self,
        path: str,
        bytes_freed: int,
        *,
        was_dir: bool = False,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO deletions "
                "(timestamp, path, bytes_freed, was_dir, success, error) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    path, bytes_freed, int(was_dir), int(success), error,
                ),
            )
            self.conn.commit()

    def get_deletion_history(self, limit: int = 100) -> list[dict[str, object]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, timestamp, path, bytes_freed, was_dir, success, error "
                "FROM deletions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": r[0], "timestamp": r[1], "path": r[2],
                    "bytes_freed": r[3], "was_dir": bool(r[4]),
                    "success": bool(r[5]), "error": r[6],
                }
                for r in rows
            ]

    def vacuum(self) -> None:
        """Compact the database. In WAL mode, checkpoint before and after to avoid corruption."""
        with self._lock:
            self.conn.commit()
            self.conn.execute("PRAGMA mmap_size=0")  # avoid SIGSEGV on truncation (macOS)
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("VACUUM")
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("PRAGMA mmap_size=67108864")  # restore 64 MB

    def reset(self) -> None:
        """Drop all user data and recreate the schema with empty tables."""
        with self._lock:
            self._schema_verified = False
            tables = [
                r[0]
                for r in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for t in tables:
                self._conn.execute(f"DROP TABLE IF EXISTS [{t}]")
            self._conn.commit()
            # Disable mmap before checkpoint/VACUUM — on macOS, truncating a memory-mapped
            # file can cause SIGSEGV (see sqlite.org/forum, python/cpython#119817).
            self._conn.execute("PRAGMA mmap_size=0")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("VACUUM")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("PRAGMA mmap_size=67108864")  # restore 64 MB
            self._apply_schema()

    def db_size_bytes(self) -> int:
        return Path(self._db_path).stat().st_size

    def snapshot_count(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()
            return row[0] if row else 0

    # -- adaptive: path tracking ---------------------------------------------

    def get_path_statuses(
        self, status: str | None = None,
    ) -> list[dict[str, object]]:
        with self._lock:
            if status:
                rows = self.conn.execute(
                "SELECT path, status, last_bytes, last_file_count, depth, "
                "consecutive_stable, last_growth_bytes, updated_at "
                    "FROM path_status WHERE status = ? ORDER BY path",
                    (status,),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT path, status, last_bytes, last_file_count, depth, "
                    "consecutive_stable, last_growth_bytes, updated_at "
                    "FROM path_status ORDER BY path",
                ).fetchall()
            return [
                {
                    "path": r[0], "status": r[1], "last_bytes": r[2],
                    "last_file_count": r[3], "depth": r[4],
                    "consecutive_stable": r[5], "last_growth_bytes": r[6],
                    "updated_at": r[7],
                }
                for r in rows
            ]

    def upsert_path_status(
        self,
        path: str,
        status: str,
        last_bytes: int,
        last_file_count: int,
        depth: int,
        consecutive_stable: int,
        last_growth_bytes: int,
    ) -> None:
        with self._lock:
            now = _dt.datetime.now(_dt.timezone.utc).isoformat()
            self.conn.execute(
                """INSERT INTO path_status
                   (path, status, last_bytes, last_file_count, depth,
                    consecutive_stable, last_growth_bytes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET
                     status=excluded.status,
                     last_bytes=excluded.last_bytes,
                     last_file_count=excluded.last_file_count,
                     depth=excluded.depth,
                     consecutive_stable=excluded.consecutive_stable,
                     last_growth_bytes=excluded.last_growth_bytes,
                     updated_at=excluded.updated_at""",
                (path, status, last_bytes, last_file_count, depth,
                 consecutive_stable, last_growth_bytes, now),
            )

    def bulk_upsert_path_status(self, rows: list[tuple]) -> None:
        """rows: [(path, status, last_bytes, last_file_count, depth, consec, growth)]"""
        with self._lock:
            now = _dt.datetime.now(_dt.timezone.utc).isoformat()
            self.conn.executemany(
                """INSERT INTO path_status
               (path, status, last_bytes, last_file_count, depth,
                consecutive_stable, last_growth_bytes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                 status=excluded.status,
                 last_bytes=excluded.last_bytes,
                 last_file_count=excluded.last_file_count,
                 depth=excluded.depth,
                 consecutive_stable=excluded.consecutive_stable,
                 last_growth_bytes=excluded.last_growth_bytes,
                 updated_at=excluded.updated_at""",
                [(p, s, b, f, d, c, g, now) for p, s, b, f, d, c, g in rows],
            )
            self.conn.commit()

    def clear_path_statuses(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM path_status")
            self.conn.commit()

    # -- path I/O (process attribution) --------------------------------------

    def insert_path_io_samples(
        self, samples: list[tuple[str, int, str, int, int, int]],
    ) -> None:
        """Insert samples: (path, pid, process_name, read_bytes, write_bytes, open_files)."""
        with self._lock:
            now = _dt.datetime.now(_dt.timezone.utc).isoformat()
            self.conn.executemany(
                """INSERT INTO path_io_samples
               (path, timestamp, pid, process_name, read_bytes, write_bytes, open_files_under_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(p, now, pid, name, r, w, of) for p, pid, name, r, w, of in samples],
            )
            self.conn.commit()

    def get_path_io_history(
        self, path: str, *, limit: int = 100,
    ) -> list[tuple[str, int, str, int, int, int]]:
        """Return (timestamp, pid, process_name, read_bytes, write_bytes, open_files)."""
        with self._lock:
            rows = self.conn.execute(
            """SELECT timestamp, pid, process_name, read_bytes, write_bytes, open_files_under_path
               FROM path_io_samples WHERE path = ?
               ORDER BY timestamp DESC LIMIT ?""",
                (path, limit),
            ).fetchall()
            return list(rows)

    def path_io_watch_insert(
        self, path: str, duration_minutes: int, sample_interval_sec: int = 60,
    ) -> None:
        with self._lock:
            now = _dt.datetime.now(_dt.timezone.utc).isoformat()
            self.conn.execute(
            """INSERT OR REPLACE INTO path_io_watch
               (path, started_at, duration_minutes, sample_interval_sec)
               VALUES (?, ?, ?, ?)""",
                (path, now, duration_minutes, sample_interval_sec),
            )
            self.conn.commit()

    def path_io_watch_delete(self, path: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM path_io_watch WHERE path = ?", (path,))
            self.conn.commit()

    def path_io_watch_list(self) -> list[tuple[str, str, int, int]]:
        """Return (path, started_at, duration_minutes, sample_interval_sec)."""
        with self._lock:
            return self.conn.execute(
                "SELECT path, started_at, duration_minutes, sample_interval_sec FROM path_io_watch"
            ).fetchall()

    def get_path_io_summary(self, limit: int = 50) -> list[tuple[str, str, int]]:
        """Paths with recent samples: (path, last_timestamp, sample_count)."""
        with self._lock:
            rows = self.conn.execute(
                """SELECT path, MAX(timestamp) as last_ts, COUNT(*) as cnt
                   FROM path_io_samples GROUP BY path
                   ORDER BY last_ts DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [(r[0], r[1], r[2]) for r in rows]

    def get_scan_number(self) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'adaptive_scan_number'"
            ).fetchone()
            return int(row[0]) if row else 0

    def set_scan_number(self, n: int) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('adaptive_scan_number', ?)",
                (str(n),),
            )
            self.conn.commit()

    def get_baseline_snapshot_id(self) -> int | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'adaptive_baseline_id'"
            ).fetchone()
            return int(row[0]) if row else None

    def set_baseline_snapshot_id(self, snap_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('adaptive_baseline_id', ?)",
                (str(snap_id),),
            )
            self.conn.commit()

    # -- adaptive: compaction ------------------------------------------------

    def collapse_stable_children(self, stable_paths: list[str]) -> int:
        """For each stable path, delete all deeper child entries from ALL snapshots.

        Keeps the parent row (the aggregate), deletes the children underneath.
        Returns total rows removed.
        """
        with self._lock:
            total = 0
            for path in stable_paths:
                prefix = path.rstrip("/") + "/"
                cur = self.conn.execute(
                    "DELETE FROM entries WHERE path LIKE ? || '%' "
                    "AND path != ?",
                    (prefix, path),
                )
                total += cur.rowcount
            if total > 0:
                self.conn.commit()
            return total

    def delete_unchanged_entries(
        self, old_id: int, new_id: int, *, tolerance_bytes: int = 0,
    ) -> int:
        """Delete entries from old_id that are identical (within tolerance) in new_id.

        Keeps changed entries for historical diff accuracy.
        """
        with self._lock:
            cur = self.conn.execute(
            """DELETE FROM entries WHERE snapshot_id = ? AND path IN (
                SELECT o.path FROM entries o
                JOIN entries n ON n.path = o.path AND n.snapshot_id = ?
                WHERE o.snapshot_id = ?
                  AND ABS(n.total_bytes - o.total_bytes) <= ?
            )""",
                (old_id, new_id, old_id, tolerance_bytes),
            )
            removed = cur.rowcount
            if removed > 0:
                self.conn.commit()
            return removed

    def smart_retain(self, keep: int, baseline_id: int | None = None) -> int:
        """Keep last *keep* snapshots plus the baseline. Delete others."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id FROM snapshots ORDER BY timestamp DESC"
            ).fetchall()
            ids_by_recency = [r[0] for r in rows]

            protected = set(ids_by_recency[:keep])
            if baseline_id is not None:
                protected.add(baseline_id)

            to_delete = [sid for sid in ids_by_recency if sid not in protected]
            for sid in to_delete:
                self.conn.execute("DELETE FROM entries WHERE snapshot_id = ?", (sid,))
                self.conn.execute("DELETE FROM snapshots WHERE id = ?", (sid,))
            self.conn.commit()
            return len(to_delete)

    def entry_count(self, snapshot_id: int | None = None) -> int:
        with self._lock:
            if snapshot_id is not None:
                row = self.conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE snapshot_id = ?",
                    (snapshot_id,),
                ).fetchone()
            else:
                row = self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()
            return row[0] if row else 0

    def total_entry_count(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()
            return row[0] if row else 0

    # -- internal ------------------------------------------------------------

    def _load_entries(self, snapshot_id: int) -> list[DirEntry]:
        rows = self.conn.execute(
            "SELECT path, total_bytes, file_count, dir_count, depth, error "
            "FROM entries WHERE snapshot_id = ? ORDER BY total_bytes DESC",
            (snapshot_id,),
        ).fetchall()
        return [
            DirEntry(path=r[0], total_bytes=r[1], file_count=r[2],
                     dir_count=r[3], depth=r[4], error=r[5])
            for r in rows
        ]
