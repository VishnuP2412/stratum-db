# WAL format

The write-ahead log is a sequence of big-endian records. Each record is
written and flushed before the corresponding operation is applied to the
MemTable.

## Record layout

| Field | Size | Format |
|---|---:|---|
| Sequence number | 8 bytes | Unsigned 64-bit integer |
| Operation type | 1 byte | `1` = put, `2` = delete |
| Key length | 4 bytes | Unsigned 32-bit integer |
| Value length | 4 bytes | Unsigned 32-bit integer |
| Key | Variable | Raw bytes |
| Value | Variable | Raw bytes |
| CRC32 | 4 bytes | Unsigned 32-bit integer |

The fixed header uses `struct` format `>QBII`. The CRC covers the header and
the key/value payload. Replay stops at the first incomplete or invalid record,
which preserves the valid prefix after a crash.

The replay contract is prefix-based: a reader yields every complete,
CRC-valid record before the first truncated header/body/CRC or CRC mismatch,
then stops without yielding that record or later bytes. EOF is normal because
the log has no record count or end marker. Delete records use a zero-length
value; their operation type remains part of the CRC input.

For example, a put with sequence `1`, key `b"a"`, and value `b"b"` is:

```text
00 00 00 00 00 00 00 01  01 00 00 00 01 00 00 00
01 61 62  XX XX XX XX
```

The final four bytes (`XX`) are the CRC32 calculated from the preceding
header and payload; they are shown symbolically here rather than copied from
a particular runtime-generated file.
