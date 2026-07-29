# Stratum DB

`stratum-db` is a write-optimized, crash-safe Python LSM-tree key-value engine.
It implements a durable MemTable + WAL + SSTable storage stack with binary formats,
crash recovery, compaction, and a growing roadmap toward bloom filters and gRPC.

## What this repo contains

- `stratum/engine.py` — the core `Engine` class that coordinates WAL, MemTable, SSTable files, and compaction
- `stratum/wal.py` — write-ahead log with CRC-checked append and replay
- `stratum/memtable.py` — in-memory sorted key-value store with tombstone support
- `stratum/sstable.py` — immutable, sorted on-disk segment file format with range scan, restart-safe rediscovery, and shared entry-parsing
- `tests/` — pytest coverage for WAL, MemTable, SSTable, recovery, compaction, and real SIGKILL crash-safety tests
- `DEVELOPMENT.md` — design rationale, tradeoffs, and phase-by-phase decisions, including known gaps
- `Stratum Dev Roadmap.md` — project scope, phased milestones, and ecosystem alignment

## Status

This repository currently implements:

- durable WAL append with CRC validation and corruption-safe replay
- in-memory `MemTable` with sorted keys, tombstone-based deletes, and `bytes`-only key/value enforcement
- SSTable flush (atomic temp-file + fsync + rename) and range/point read via `scan()`
- **SSTable rediscovery on restart** — `Engine` rebuilds its full view of on-disk SSTables from a fresh directory scan at startup, so data flushed in a _previous_ process lifetime is visible again after a restart, not just WAL-replayed MemTable state
- **Unambiguous tombstone handling across the MemTable/SSTable boundary** — `scan()` returns tombstones untouched (filtering is the caller's job), and `Engine.get()` stops at the first SSTable (newest-first) that has _any_ record for a key, live or deleted, so a delete correctly shadows an older value in an older file instead of being silently bypassed
- **Manual compaction** (`Engine.compact()`) — merges all current SSTables into one, resolves conflicting versions of a key by highest sequence number, and physically drops tombstoned entries — the first point in the pipeline where deleted data is actually removed from disk rather than just filtered at read time. Not auto-triggered; called explicitly
- `bytes`-only API contracts enforced (fail loudly, no silent type coercion) at every component boundary, including the shared low-level entry-parsing path used by both `scan()` and restart-time loading
- real process-kill (`SIGKILL`) crash-safety tests covering WAL replay, SSTable flush/rename, and compaction's old-file cleanup step (via deterministic fault injection — see `DEVELOPMENT.md` for why a live SIGKILL specifically inside that window wasn't pursued further)

**Known limitation:** `Engine.get()` performs a full linear scan of an SSTable file for every point lookup — there is currently no index of any kind, so lookup cost scales with file size and a key's position within it. This was measured directly during Phase 3 testing (~30 minutes to verify 100,000 sequential lookups against a ~1,000,000-entry compacted file) and is the primary motivation for the next phase of work. This is a tracked, deliberate gap, not an oversight — see `DEVELOPMENT.md`.

Planned next work: bloom filters and a sparse on-disk index (to address the lookup-cost limitation above), gRPC, packaging.

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

# Merge all current SSTables into one, dropping tombstoned keys for good.
# Manual only — not triggered automatically on any threshold.
engine.compact()
```

### Important API contracts

- `Engine.put(key, value)` and `Engine.delete(key)` require `key`/`value` to be `bytes` — non-`bytes` input raises `TypeError` immediately, no silent conversion
- `Engine.get(key)` returns `bytes` or `None`
- A `put()` call that happens to trigger a MemTable flush is **not durable** until that flush completes — if the process dies mid-flush, that specific write is lost (see `DEVELOPMENT.md` for the reasoning)
- `Engine.compact()` is safe to interrupt at any point: a crash before the merged file is fully written leaves all original SSTables untouched; a crash after leaves the merged file and possibly some undeleted (but now redundant) originals — reads remain correct either way, since the newest file always wins on a shadowing conflict (see `DEVELOPMENT.md`, Phase 3)
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
    ├── test_recovery.py
    └── test_compaction.py
```

## Tests

Run the full suite with:

```bash
pytest
```

Includes real `kill -9` (`SIGKILL`) crash-injection tests — not simulated failure — for WAL replay and SSTable flush/truncate crash windows, plus deterministic fault-injection tests for compaction's old-file cleanup step.

## Design and durability notes

- WAL records use a packed header and CRC32 checksum; replay stops at the first corrupted entry rather than skipping past it
- SSTable flush writes to a temporary file, `fsync`s it to force bytes actually onto disk, then atomically renames into place — the rename is the single commit point. `Engine.compact()`'s merged output goes through the same path, reused rather than reimplemented
- Tombstones are represented as deleted entries; `scan()` returns them untouched and callers decide what to do with them — `Engine.get()` treats the first hit (newest file first) as authoritative, `Engine.compact()` sees every tombstone across every file and uses that visibility to drop dead keys permanently
- `Engine.get()` checks MemTable first, then falls back to SSTables newest-first, so a more recent write — or delete — always shadows an older one, across both in-memory and on-disk state
- SSTable entry parsing (header unpack, truncation checks, duplicate-key integrity check) lives in one shared generator used by both `scan()` and restart-time file loading, so a corrupted file is caught consistently regardless of which path reads it first
- `mmap` was deliberately not used for the WAL, despite being in the original project roadmap — chosen against in favor of plain `fsync()`-based writes to avoid `SIGBUS`-class risk on a correctness-critical path; see `DEVELOPMENT.md` for the full tradeoff
- Compaction uses a naive full-materialize-then-sort merge rather than a streaming/heap-based k-way merge — a deliberate choice given measured data volumes at project scale, not a performance oversight; see `DEVELOPMENT.md`, Phase 3, for the tradeoff analysis

## Contributing

Contributions are welcome via issues or pull requests. Please keep changes aligned with the
project's current goal: a correct, durable Python LSM-tree engine with a clean byte-oriented API.

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file.
