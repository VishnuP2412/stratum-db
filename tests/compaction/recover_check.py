"""Recover the engine after a forced SIGKILL and verify keys.

This script loads the existing ``tmp_long_data`` / ``tmp_long_tables``
directories, iterates over the expected key‑value pairs, and reports any
mismatches.  It now supports a ``--limit`` argument to stop after a given
number of keys and a ``--workers`` argument to run the verification in
parallel, which dramatically reduces runtime for large data sets.
"""

import argparse
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from stratum.engine import Engine

# Configuration – must match the generation script (defaults)
NUM_TABLES = 5_000
ENTRIES_PER = 200

DATA_DIR = Path("tmp_long_data")
TABLE_DIR = Path("tmp_long_tables")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=NUM_TABLES * ENTRIES_PER,
        help="Maximum number of keys to verify (default: all keys)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel worker threads (default: 1 – sequential)",
    )
    return parser.parse_args()


def verify_range(engine: Engine, start: int, end: int) -> int:
    """Verify keys in ``[start, end)`` and return the number of mismatches.

    This helper is used both in the sequential path and by each worker thread.
    """
    missing = 0
    for i in range(start, end):
        key = f"k{i}".encode()
        expected = f"v{i}".encode()
        val = engine.get(key)
        if val != expected:
            missing += 1
            print(f"Mismatch at {key!r}: expected {expected!r}, got {val!r}")
        print(f"…checked {i:,} keys")
    return missing


def main() -> None:
    args = parse_args()
    total = args.limit
    print(f"Loading engine (this may take a while for many SSTables)…")
    start_load = time.time()
    engine = Engine(DATA_DIR, TABLE_DIR)
    print(f"Engine loaded in {time.time() - start_load:.1f}s")

    missing = 0
    start_verify = time.time()
    if args.workers > 1:
        # Split the range into roughly equal chunks for each worker.
        chunk = total // args.workers
        futures = []
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for w in range(args.workers):
                s = w * chunk
                e = total if w == args.workers - 1 else (w + 1) * chunk
                futures.append(executor.submit(verify_range, engine, s, e))
            for f in as_completed(futures):
                missing += f.result()
    else:
        missing = verify_range(engine, 0, total)

    print(f"Checked {total:,} keys in {time.time() - start_verify:.1f}s, mismatches: {missing}")
    print(f"Current SSTable count: {len(list(TABLE_DIR.glob('*.sst')))}")


if __name__ == "__main__":
    main()
