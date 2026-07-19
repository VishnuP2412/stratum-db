# Stratum DB

`stratum-db` is a write-optimized, crash-safe Python LSM-tree key-value engine.
It implements a durable MemTable + WAL + SSTable storage stack with binary formats,
crash recovery, and a growing roadmap toward compaction, bloom filters, and gRPC.

## What this repo contains

- `stratum/engine.py` — the core `Engine` class that coordinates WAL, MemTable, and SSTable files
- `stratum/wal.py` — write-ahead log with CRC-checked append and replay
- `stratum/memtable.py` — in-memory sorted key-value store with tombstone support
- `stratum/sstable.py` — immutable, sorted on-disk segment file format with range scan support
- `tests/` — pytest coverage for WAL, MemTable, SSTable, recovery, and real SIGKILL crash-safety tests
- `DEVELOPMENT.md` — design rationale, tradeoffs, and phase-by-phase decisions, including known gaps
- `Stratum Dev Roadmap.md` — project scope, phased milestones, and ecosystem alignment

## Status

This repository currently implements:

- durable WAL append with CRC validation and corruption-safe replay
- in-memory `MemTable` with sorted keys, tombstone-based deletes, and `bytes`-only key/value enforcement
- SSTable flush (atomic temp-file + fsync + rename) and range/point read via `scan()`, with tombstone filtering at read time
- `Engine.get()` fallback from MemTable to SSTables on a miss, correctly shadowing older values with newer ones
- replay-based recovery that restores the MemTable from the WAL after a crash or restart
- real process-kill (`SIGKILL`) crash-safety tests covering both the flush-before-rename and rename-before-WAL-truncate windows
- `bytes`-only API contracts enforced (fail loudly, no silent type coercion) at every component boundary

**Known limitation:** SSTable files already flushed to disk in a _previous_ process lifetime are not currently rediscovered on restart — only WAL-driven MemTable state is recovered. This is a tracked, deliberate gap (see `DEVELOPMENT.md`), not an oversight, and is prioritized ahead of compaction work.

Planned next work: compaction, SSTable rediscovery on startup, bloom filters, gRPC, packaging.

## Requirements

- Python 3.12+
- `sortedcontainers`
- `pytest`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install sortedcontainers pytest
```

## Example usage

```python
from pathlib import Path
from stratum.engine import Engine

engine = Engine(Path("./data"))
engine.put(b"user:1", b"Alice")
print(engine.get(b"user:1"))
engine.delete(b"user:1")
```

### Important API contracts

- `Engine.put(key, value)` and `Engine.delete(key)` require `key`/`value` to be `bytes` — non-`bytes` input raises `TypeError` immediately, no silent conversion
- `Engine.get(key)` returns `bytes` or `None`
- A `put()` call that happens to trigger a MemTable flush is **not durable** until that flush completes — if the process dies mid-flush, that specific write is lost (see `DEVELOPMENT.md` for the reasoning)
- WAL and SSTable files are persisted under the provided `data_dir` (SSTables optionally under a separate `table_dir`, defaulting to `data_dir` if not given)

## Project structure

```text
stratum-db/
├── DEVELOPMENT.md
├── LICENSE
├── README.md
├── Stratum Dev Roadmap.md
├── pyproject.toml
├── stratum/
│   ├── __init__.py
│   ├── api.py
│   ├── engine.py
│   ├── memtable.py
│   ├── sstable.py
│   └── wal.py
└── tests/
    ├── test_memtable.py
    ├── test_wal.py
    ├── test_sstable.py
    └── test_recovery.py
```

## Tests

Run the full suite with:

```bash
pytest
```

Includes real `kill -9` (`SIGKILL`) crash-injection tests — not simulated failure — for both WAL replay and SSTable flush/truncate crash windows.

## Design and durability notes

- WAL records use a packed header and CRC32 checksum; replay stops at the first corrupted entry rather than skipping past it
- SSTable flush writes to a temporary file, `fsync`s it to force bytes actually onto disk, then atomically renames into place — the rename is the single commit point
- Tombstones are represented as deleted entries and filtered during `SSTable.scan()`, not inside `Engine`
- `Engine.get()` checks MemTable first, then falls back to SSTables newest-first, so a more recent write always shadows an older one
- `mmap` was deliberately not used for the WAL, despite being in the original project roadmap — chosen against in favor of plain `fsync()`-based writes to avoid `SIGBUS`-class risk on a correctness-critical path; see `DEVELOPMENT.md` for the full tradeoff

## Contributing

Contributions are welcome via issues or pull requests. Please keep changes aligned with the
project's current goal: a correct, durable Python LSM-tree engine with a clean byte-oriented API.

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file.
