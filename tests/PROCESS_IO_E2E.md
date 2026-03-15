# Process I/O E2E Tests

## Overview

The `test_process_io_e2e.py` suite uses a background **periodic I/O writer** (`tests/io_writer.py`) that keeps a file open and writes to it. This proves that sldd can detect the writing process and that all Process I/O features work end-to-end.

## Writer Script

**`tests/io_writer.py`** — runnable as `python -m tests.io_writer <path> [--interval 1] [--duration 30]`

- Creates a file under the given path and keeps it open
- Periodically writes chunks (default 4KB) at a configurable interval
- Runs until `--duration` or SIGTERM/SIGINT
- Used by tests to ensure `psutil.open_files()` and `io_counters()` can detect the process

## Features Tested

| Feature | Test(s) | Description |
|---------|---------|-------------|
| **path_io_now** | `test_detects_writer_process`, `test_returns_io_fields`, `test_empty_for_unrelated_path` | On-demand snapshot of processes with path open + I/O stats |
| **path_io_store_samples** | `test_store_and_history`, `test_summary_includes_path` | Persist samples to DB |
| **path_io_history** | `test_store_and_history`, `test_full_flow` | Historic samples with deltas for charting |
| **path_io_summary** | `test_summary_includes_path`, `test_full_flow` | Paths with recent samples |
| **path_io_watch_start** | `test_watch_start_and_status`, `test_full_flow` | Register path for background I/O watching |
| **path_io_watch_status** | `test_watch_start_and_status`, `test_full_flow` | List active watches |
| **path_io_watch_stop** | `test_watch_start_and_status`, `test_watch_stop_idempotent`, `test_full_flow` | Stop watching a path |
| **get_processes_with_path_open** | All `path_io_now` tests | Low-level collector (via path_io_now) |
| **sample_path_io** | Indirectly via `path_io_store_samples` | One-time snapshot used by watcher/scan |
| **Diff + path_io integration** | `test_diff_and_path_io_together` | Storage growth detection + process attribution together |
| **CLI snapshot + diff** | `test_snapshot_and_diff_via_cli` | `sldd snapshot` and `sldd diff` detect growth from writer |

## Running the Tests

```bash
pytest tests/test_process_io_e2e.py -v
```

## Manual E2E Check

1. Start the writer in one terminal:
   ```bash
   python -m tests.io_writer /tmp/sldd_test --duration 120 --interval 1
   ```

2. In another terminal, run sldd:
   ```bash
   sldd snapshot --root /tmp/sldd_test --db /tmp/sldd.db
   # wait a few seconds
   sldd snapshot --root /tmp/sldd_test --db /tmp/sldd.db
   sldd diff --db /tmp/sldd.db
   ```
   You should see growth reported.

3. With the web server running, open the Inspect modal on the growing path — you should see the `python` (or `python3`) process with the writer's PID and I/O stats.
