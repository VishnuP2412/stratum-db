# SSTable format

An SSTable contains immutable, sorted records produced by a MemTable flush.
The file is accompanied by a sparse index file with the same name and an
`.idx` suffix. All integers are big-endian.

The data-record region starts at byte offset zero. The `.idx` sidecar contains
exactly one unsigned 32-bit integer: the byte offset at which the footer/index
region starts in the `.sst` file. The sidecar is written and atomically
renamed before the `.sst` file is installed.

## Record layout

| Field | Size | Format |
|---|---:|---|
| Key length | 4 bytes | Unsigned 32-bit integer |
| Value length | 4 bytes | Unsigned 32-bit integer |
| Sequence number | 8 bytes | Unsigned 64-bit integer |
| Deleted flag | 1 byte | `0` = live, `1` = tombstone |
| Key | Variable | Raw bytes |
| Value | Variable | Raw bytes |

The fixed header uses `struct` format `>IIQB`. Records are ordered by key.
Sequence numbers resolve shadowing when the same key occurs in multiple
SSTables.

## Footer and sparse index

The footer/index region starts immediately after the final record:

| Field | Size | Format |
|---|---:|---|
| Bloom bit count | 4 bytes | Unsigned 32-bit integer |
| Bloom hash count | 4 bytes | Unsigned 32-bit integer |
| Bloom byte length | 4 bytes | Unsigned 32-bit integer |
| Bloom bytes | Variable | Raw bytes, one byte per Bloom bit |
| Index entries | Variable | Repeated entries to end of file |

Each sparse-index entry is:

| Field | Size | Format |
|---|---:|---|
| Key length | 4 bytes | Unsigned 32-bit integer |
| Sample key | Variable | Raw bytes |
| Record offset | 4 bytes | Unsigned 32-bit integer |

There is one index entry for the first record and then every 1000th record.
The offset points to that record's 17-byte header. A reader selects the last
sample key less than or equal to a target and scans forward. The index is an
optimization; correctness must not depend on it.

An empty flush has no records and no footer payload. Its sidecar offset is zero.
Readers treat that combination as an empty table with an empty Bloom filter.
Non-empty files contain the footer fields above, and the sidecar offset is
greater than zero and no greater than the `.sst` size.

## Example

A one-byte key, a three-byte value, sequence `7`, and a live record have this
header and payload:

```text
00 00 00 01  00 00 00 03  00 00 00 00 00 00 00 07
00 61 76 61 6C
```

The final bytes are the raw key and value (`a` and `val`). Tombstones retain
the original key and sequence number but have deleted flag `1` and a
zero-length value. `SSTable.scan()` exposes the raw deleted flag; `Engine.get()`
and `Engine.scan()` suppress deleted records from public results.
