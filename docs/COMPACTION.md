# Compaction

`Engine.compact()` reads the current SSTables, chooses the record with the
highest sequence number for each key, removes keys whose winning record is a
tombstone, and writes one replacement SSTable. The replacement is installed
before the old files are deleted, so an interrupted delete phase leaves
redundant files rather than losing the newly written data.

Compaction is explicit and manual. It is not triggered automatically by a
file-count threshold, and it uses full materialization rather than the
roadmap's tiered `heapq` merge design. This is a closed v1.0 decision:
tiered/background compaction is deferred until after the `v1.0.0` tag and
must not block that release.

This implementation has one compaction level: `compact()` merges every
currently known SSTable. Because no older input level remains after the merge,
dropping a winning tombstone is safe here. A future tiered design must retain
tombstones until it proves that no lower level can contain an older value.

Scanning while compaction is running is unsupported. Callers must serialize
`scan()` and `compact()` at the application boundary; the engine does not
provide a snapshot or concurrency contract for that combination. The current
`scan(start_key, end_key)` API requires both inclusive byte bounds and rejects
an inverted range. Open-ended scans are intentionally not part of v1.0.

The current design prioritizes correctness and a small standalone installation
over background scheduling, write batching, and an outbox integration.
