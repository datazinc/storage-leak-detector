# sldd — Storage Leak Diff Detector

Cross-platform tool that finds what's eating your disk space by taking filesystem snapshots and comparing them over time. Designed for the scenario where your system runs out of space every few hours and you need to find the culprit fast.

## Features

- **Snapshot & diff** — capture directory sizes, compare any two snapshots, see exactly what grew
- **Anomaly detection** — flags abnormal growth using absolute thresholds, growth rate, relative change, and statistical deviation
- **Depth-aware attribution** — traces growth from `/` down to the deepest directory responsible
- **Adaptive scanning** — starts shallow (depth 3), focuses on what changes, discards the rest. Keeps DB small automatically
- **Web dashboard** — real-time UI with charts, drill-down explorer, playback animation, deletion manager, and settings
- **CLI** — full-featured terminal interface with Rich tables and color output
- **Safe deletion** — preview impact before deleting, blocklist protects system paths, full audit log
- **Playback** — animate filesystem changes over time like a video, with speed controls

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** (only for the web dashboard; CLI works without it)

## Installation

### Quick start (clone, install, run — one command)

[**→ Open in GitHub**](https://github.com/datazinc/storage-leak-detector) | [**→ Download ZIP**](https://github.com/datazinc/storage-leak-detector/archive/refs/heads/main.zip)

**Bash** (Linux, macOS, Git Bash):

```bash
([ -d storage-leak-detector ] || git clone https://github.com/datazinc/storage-leak-detector.git) && cd storage-leak-detector && pip install ".[web]" --no-warn-script-location && python -m sldd.cli web
```

**Windows cmd**:

```cmd
if not exist storage-leak-detector git clone https://github.com/datazinc/storage-leak-detector.git && cd storage-leak-detector && pip install ".[web]" --no-warn-script-location && python -m sldd.cli web
```

**Windows PowerShell**:

```powershell
if (-not (Test-Path storage-leak-detector)) { git clone https://github.com/datazinc/storage-leak-detector.git }; cd storage-leak-detector; pip install ".[web]" --no-warn-script-location; python -m sldd.cli web
```

Skips cloning if the directory already exists. Uses `python -m` so it works without PATH setup.

### Other options

**Install only** (no run):

```bash
# Bash
([ -d storage-leak-detector ] || git clone https://github.com/datazinc/storage-leak-detector.git) && cd storage-leak-detector && pip install ".[web]" --no-warn-script-location

# Windows cmd
if not exist storage-leak-detector git clone https://github.com/datazinc/storage-leak-detector.git && cd storage-leak-detector && pip install ".[web]" --no-warn-script-location
```

**From PyPI** (when published): `pip install sldd[web]`

**Development:** `pip install -e ".[dev,web]"`

### Verify

```bash
sldd --help
```

If `sldd` is not found, use `python -m sldd.cli --help` instead.

### PATH setup

To use `sldd` instead of `python -m sldd.cli`:

**Windows:** Add `Python\Scripts` to PATH (e.g. `C:\Users\<you>\AppData\Local\Programs\Python\Python311\Scripts`). Restart the terminal.

**macOS / Linux:** Add the pip user bin or venv bin to PATH. Restart the terminal or run `source ~/.bashrc` / `source ~/.zshrc`.

**Check:** `which sldd` (macOS/Linux) or `where sldd` (Windows)

## Platform support

| Feature                                           |    Linux     |            macOS            |         Windows          |
| ------------------------------------------------- | :----------: | :-------------------------: | :----------------------: |
| Snapshot, diff, watch, drill, history             |      ✓       |              ✓              |            ✓             |
| Duplicate file detection                          |      ✓       |              ✓              |            ✓             |
| Web dashboard                                     |      ✓       |              ✓              |            ✓             |
| Open in file manager                              | ✓ (xdg-open) |         ✓ (Finder)          |       ✓ (Explorer)       |
| Process I/O (open files, read/write bytes)        |      ✓       | Partial (I/O bytes often 0) |            ✓             |
| Port fallback when in use                         |      ✓       |              ✓              |            ✓             |
| Kill previous sldd on port before start           |   ✓ (lsof)   |          ✓ (lsof)           |        ✓ (psutil)        |
| Graceful SIGINT/SIGTERM (kill child on Ctrl-C)    |      ✓       |              ✓              |            ✓             |
| Run as root detection                             |      ✓       |              ✓              |            ✓             |
| Restart as regular user (sudo → drop privileges)  |      ✓       |              ✓              |            —             |
| Restart as administrator (elevate when not admin) |  ✓ (pkexec)  |        ✓ (osascript)        |         ✓ (UAC)          |
| Symlink following                                 |      ✓       |              ✓              | Partial (may need admin) |

## Usage

### Web dashboard

```bash
sldd web
```

Try `sldd` first; if not found, use `python -m sldd.cli web`.

First run will:

1. Install frontend dependencies if needed (`npm install`)
2. Build the frontend if missing or stale (`npm run build`)
3. Start the server on http://localhost:8080
4. Open your browser automatically

If Node.js is not installed, you'll see instructions to install it. The CLI (snapshot, diff, watch) works without Node.

### Watch mode (CLI)

```bash
sldd watch -r / -i 300
```

(Or `python -m sldd.cli watch -r / -i 300` if `sldd` is not found.)

Scans `/` every 5 minutes with adaptive mode on by default. Prints a report whenever anomalies are detected. Press Ctrl-C to stop.

### Web dashboard options

```bash
sldd web --port 8080 --db snapshots.db
```

(Or `python -m sldd.cli web ...` if `sldd` is not found.)

The dashboard includes:

- **Dashboard** — stats, anomaly table, top growers chart, disk usage timeline
- **Playback** — animate changes between any two snapshots with speed controls
- **Explorer** — navigate the directory tree, see size history for any path
- **Deletion** — safely delete files/directories or prune old snapshots
- **Settings** — configure scan depth, thresholds, adaptive mode, database

For development with hot-reload:

```bash
# Terminal 1: backend
sldd web --port 8080 --db snapshots.db

# Terminal 2: frontend dev server
cd frontend && npx vite --port 5173
```

Then open http://localhost:5173 (proxies API calls to the backend).

### Manual snapshots

```bash
# Take snapshots at different times
sldd snapshot -r / --db snapshots.db
# ... wait ...
sldd snapshot -r / --db snapshots.db

# Compare the two most recent
sldd diff --db snapshots.db

# Compare specific snapshots
sldd diff --from 1 --to 5 --db snapshots.db

# Output as JSON
sldd diff --json --db snapshots.db
```

## CLI Reference

Use `python -m sldd.cli` instead of `sldd` if the command is not found.

| Command                 | Description                               |
| ----------------------- | ----------------------------------------- |
| `sldd snapshot`         | Take a filesystem snapshot                |
| `sldd diff`             | Compare two snapshots and show what grew  |
| `sldd watch`            | Periodic snapshots with anomaly alerts    |
| `sldd web`              | Launch the web dashboard                  |
| `sldd ls`               | List saved snapshots                      |
| `sldd drill -p /path`   | Drill into a directory's children         |
| `sldd history -p /path` | Size history of a path across snapshots   |
| `sldd compact`          | Run compaction (collapse stable subtrees) |
| `sldd prune -k N`       | Keep only the N most recent snapshots     |
| `sldd rm <id>`          | Delete a specific snapshot                |

### Watch mode options

```bash
sldd watch \
  -r /                    # root path to scan
  -i 120                  # scan interval in seconds
  --threshold 200MB       # absolute growth alert threshold
  --rate-threshold 100MB  # growth rate alert threshold (per hour)
  --initial-depth 4       # depth for discovery scans
  --stability-scans 5     # scans before marking a path stable
  --keep 10               # snapshots to retain
  --no-adaptive           # disable adaptive mode (full deep scan)
  --json                  # output reports as JSON
```

### Web server options

```bash
sldd web \
  --port 8080             # port to listen on
  --host 127.0.0.1        # host to bind to
  --db snapshots.db       # database file path
  -r /                    # scan root for safety checks
  --no-auto-restart       # disable auto-restart on crash
  --max-restarts 10       # max consecutive auto-restarts
```

## Adaptive Scanning

The default `auto` mode dramatically reduces storage usage by scanning smart:

| Phase                    | What happens                                                   | Storage cost       |
| ------------------------ | -------------------------------------------------------------- | ------------------ |
| Discovery (scan 0)       | Scans at depth 3 (~20K entries)                                | ~6 MB/snapshot     |
| Tracking (scans 1-2)     | Compares snapshots, identifies growers                         | ~6 MB/snapshot     |
| Focused (scan 3+)        | Only scans growing paths at full depth, skips stable paths     | ~0.5-3 MB/snapshot |
| Compaction (every 3rd)   | Deletes child entries of stable subtrees, prunes old snapshots | Reclaims 50-90%    |
| Rediscovery (every 10th) | Full depth-3 scan to catch new growth                          | ~6 MB              |

**Comparison**: naive full `/` scans produce ~58 MB per snapshot (705 MB for 7 snapshots). Adaptive mode keeps the DB under ~25 MB across 100+ scans.

Configure in the web UI under Settings > Adaptive Scanning, or via CLI flags.

## Architecture

```
src/sldd/
  models.py      Pure dataclasses — Snapshot, DirDiff, Anomaly, configs
  snapshot.py    Filesystem walker — os.scandir + size aggregation
  storage.py     SQLite repository — snapshots, entries, path tracking
  diff.py        Diff engine — SQL join to compare snapshots
  detect.py      Anomaly detection — threshold, statistical, attribution
  adaptive.py    Adaptive scan engine — plan, track, compact
  api.py         Public API facade (SLDD class)
  cli.py         Click CLI
  server.py      FastAPI web server + REST endpoints
  scheduler.py   Watch mode scheduler
  report.py      Terminal report formatting
  delete.py      Safe deletion with blocklist
  playback.py    Playback frame generation

frontend/
  src/api.ts           TypeScript API client
  src/App.tsx          Router + layout + toast system
  src/views/           Dashboard, Playback, Explorer, Deletion, Settings
  src/components/      Card, ResizableTable, DepthFilter, Toast
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev,web]"

# Run tests (136 tests)
pytest

# Lint
ruff check src/

# Type check
mypy src/sldd/

# Frontend type check
cd frontend && npx tsc --noEmit
```

## Distribution

| Method                                 | Use case                                                            |
| -------------------------------------- | ------------------------------------------------------------------- |
| `pip install sldd[web]`                | Standard install from PyPI (frontend bundled)                       |
| `pip install sldd`                     | CLI only (no web dashboard)                                         |
| Source + `pip install -e ".[dev,web]"` | Development, contributions                                          |
| PyInstaller / Nuitka                   | Standalone executable (no Python/Node required) — build scripts TBD |
| Docker                                 | Isolated environment — Dockerfile TBD                               |

**Publishing a release:** Run `cd frontend && npm run build`, then `python scripts/prepare_build.py` to copy the built frontend into the package, then `python -m build`.

## License

MIT
