"""Compare indexed and unindexed point lookups on a fixed workload.

The default data directory is under the user's home directory so WSL runs use
the native Linux filesystem rather than a mounted Windows drive.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import shutil
import statistics
import time
from pathlib import Path

from stratum.engine import Engine
from stratum.sstable import SSTable

ENTRY_COUNT = 1_000_000
LOOKUP_COUNT = 100_000
SEED = 20261015
VALUE = b"value"
CHUNK_SIZE = 10_000


def key_for(index: int) -> bytes:
    return f"key-{index:07d}".encode()


def build_dataset(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for chunk_start in range(0, ENTRY_COUNT, CHUNK_SIZE):
        chunk_end = min(chunk_start + CHUNK_SIZE, ENTRY_COUNT)
        entries = (
            (key_for(index), (VALUE, index + 1, False))
            for index in range(chunk_start, chunk_end)
        )
        SSTable.flush(data_dir, chunk_start // CHUNK_SIZE + 1, entries)


def run_mode(data_dir: Path, *, use_index: bool, use_bloom: bool, keys: list[bytes]) -> dict[str, float | int | str]:
    engine = Engine(data_dir, use_index=use_index, use_bloom=use_bloom)
    latencies_ns: list[int] = []
    started = time.perf_counter_ns()
    for key in keys:
        lookup_started = time.perf_counter_ns()
        value = engine.get(key)
        latencies_ns.append(time.perf_counter_ns() - lookup_started)
        if value != VALUE:
            raise RuntimeError(f"lookup returned an unexpected value for {key!r}")
    elapsed_ns = time.perf_counter_ns() - started
    latencies_ns.sort()
    return {
        "total_seconds": elapsed_ns / 1_000_000_000,
        "p50_ms": statistics.median(latencies_ns) / 1_000_000,
        "p95_ms": latencies_ns[int(LOOKUP_COUNT * 0.95) - 1] / 1_000_000,
        "lookups": LOOKUP_COUNT,
        "index": "enabled" if use_index else "disabled",
        "bloom_filter": "enabled" if use_bloom else "disabled",
    }


def machine_details() -> dict[str, str | int]:
    return {
        "python": platform.python_version(),
        "system": platform.platform(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count() or 0,
        "filesystem": str(Path.home()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".cache" / "stratum-db-benchmark",
        help="native-filesystem directory for the generated dataset",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="reuse the existing dataset instead of rebuilding it",
    )
    args = parser.parse_args()

    if not args.data_dir.is_absolute():
        raise ValueError("--data-dir must be an absolute path")
    if not args.keep_data and args.data_dir.exists():
        shutil.rmtree(args.data_dir)
    if not args.data_dir.exists():
        args.data_dir.parent.mkdir(parents=True, exist_ok=True)
        build_dataset(args.data_dir)

    keys = [key_for(index) for index in random.Random(SEED).choices(range(ENTRY_COUNT), k=LOOKUP_COUNT)]
    results = {
        "dataset": {"entries": ENTRY_COUNT, "lookups": LOOKUP_COUNT, "seed": SEED},
        "machine": machine_details(),
        "data_dir": str(args.data_dir),
        "indexed": run_mode(args.data_dir, use_index=True, use_bloom=True, keys=keys),
        "unindexed": run_mode(args.data_dir, use_index=False, use_bloom=False, keys=keys),
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
