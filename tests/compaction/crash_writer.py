#!/usr/bin/env python3
"""
crash_writer.py — deterministic crash-point writer for kill -9 recovery testing.

Usage:
    python crash_writer.py <data_dir> <num_writes> [large_at] [large_size_kb]

large_at:      iteration number that gets an oversized value instead of the
               normal few-byte value (default: none, all writes are small)
large_size_kb: size in KB of the oversized value (default: 64)

Performs Engine.put() num_writes times. After each put() returns,
immediately prints "WRITE_DONE <K>" and flushes stdout. A parent
process reads this stream and SIGKILLs this process right after the
line for its chosen kill point appears.
"""
import sys
import os
from pathlib import Path

# Ensure the project root is on the Python path when this script is executed
# from the tests directory (e.g., via `python tests/crash_writer.py`).
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.append(repo_root)

from stratum.engine import Engine


def main():
    if len(sys.argv) not in (3, 4, 5):
        print(
            "Usage: crash_writer.py <data_dir> <num_writes> [large_at] [large_size_kb]",
            file=sys.stderr,
        )
        sys.exit(1)

    data_dir = Path(sys.argv[1])
    num_writes = int(sys.argv[2])
    large_at = int(sys.argv[3]) if len(sys.argv) >= 4 else None
    large_size_kb = int(sys.argv[4]) if len(sys.argv) >= 5 else 64

    engine = Engine(data_dir=data_dir)

    for i in range(1, num_writes + 1):
        key = f"key_{i:04d}".encode()
        if i == large_at:
            # Oversized value — crosses multiple OS page boundaries,
            # giving SIGKILL a real chance to land mid-write instead
            # of cleanly between two small, single-page writes.
            value = (f"value_{i:04d}_".encode() * (large_size_kb * 1024 // 10))
        else:
            value = f"value_{i:04d}".encode()
        engine.put(key, value)
        print(f"WRITE_DONE {i}", flush=True)

    print("ALL_WRITES_DONE", flush=True)


if __name__ == "__main__":
    main()
