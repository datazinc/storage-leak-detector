"""Periodic I/O writer for e2e testing of Process I/O features.

Runs as a subprocess, keeps a file open under the given path, and periodically
writes to it. Used to prove that path_io_now, sample_path_io, etc. can detect
the writing process.

Usage:
    python -m tests.io_writer <path> [--interval 1] [--duration 30]
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Periodic I/O writer for e2e tests")
    parser.add_argument("path", help="Directory path to write under")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between writes")
    parser.add_argument("--duration", type=float, default=60.0, help="Max seconds to run (0 = forever)")
    parser.add_argument("--chunk", type=int, default=4096, help="Bytes per write")
    args = parser.parse_args()

    root = Path(args.path)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "io_writer_active.dat"

    stop = False

    def on_signal(_sig: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    start = time.monotonic()
    chunk = b"x" * args.chunk

    with open(target, "wb") as f:
        # Keep file open; periodic writes generate I/O that io_counters() will show
        write_count = 0
        while not stop:
            f.write(chunk)
            f.flush()
            write_count += 1
            if args.duration > 0 and (time.monotonic() - start) >= args.duration:
                break
            time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    sys.exit(main())
