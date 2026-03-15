#!/usr/bin/env python3
"""Verify that process I/O counters (read_bytes, write_bytes) work on this platform.

Runs the io_writer subprocess to generate real file I/O, then queries
path_io_now to see if psutil reports non-zero read/write values.

On macOS, psutil often returns 0 for per-process I/O. On Linux, values are
typically non-zero. Run this script to verify behavior on your system.

Usage:
    python scripts/verify_io_counters.py
    python -m scripts.verify_io_counters
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sldd.process_io import get_processes_with_path_open


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sldd_io_verify_") as tmp:
        target = (Path(tmp) / "io_test").resolve()
        target.mkdir()

        print("Starting io_writer subprocess...")
        proc = subprocess.Popen(
            [sys.executable, "-m", "tests.io_writer", str(target), "--interval", "0.2", "--duration", "5"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.8)  # Let writer open file and do several writes
            path_str = str(target)
            infos = get_processes_with_path_open(path_str)
            writer = next((p for p in infos if p.pid == proc.pid), None)
            if writer:
                print(f"Writer PID {proc.pid} detected:")
                print(f"  read_bytes:  {writer.read_bytes:,}")
                print(f"  write_bytes: {writer.write_bytes:,}")
                print(f"  open_files:  {writer.open_files_under_path}")
                if writer.read_bytes > 0 or writer.write_bytes > 0:
                    print("\nI/O counters are working on this platform.")
                else:
                    print("\nI/O counters report 0 (common on macOS). Open count is still accurate.")
            else:
                print(f"Writer PID {proc.pid} not found in path_io_now results.")
                print(f"Processes with path open: {[p.pid for p in infos]}")
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    return 0


if __name__ == "__main__":
    sys.exit(main())
