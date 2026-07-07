import os
import random
import struct
import zlib

from stratum.wal import WAL


def test_append_and_replay_single_put(tmp_path):
    
    wal = WAL(tmp_path)

    try:
        wal.append(1, 1, b'key', b'value')
    finally:
        wal.f.close()

    records = list(WAL(tmp_path).replay())
    assert records == [(1, 1, b'key', b'value')]


def test_append_and_replay_single_delete(tmp_path):
    
    wal = WAL(tmp_path)

    try:
        wal.append(2, 2, b'del-key', b'')
    finally:
        wal.f.close()

    records = list(WAL(tmp_path).replay())
    assert records == [(2, 2, b'del-key', b'')]


def test_replay_empty_file(tmp_path):
    
    assert list(WAL(tmp_path).replay()) == []


def test_multiple_entries_replay_order(tmp_path):
    
    wal = WAL(tmp_path)

    try:
        wal.append(1, 1, b'a', b'one')
        wal.append(2, 1, b'b', b'two')
        wal.append(3, 2, b'c', b'')
    finally:
        wal.f.close()

    assert list(WAL(tmp_path).replay()) == [
        (1, 1, b'a', b'one'),
        (2, 1, b'b', b'two'),
        (3, 2, b'c', b''),
    ]


def test_truncate_removes_entries(tmp_path):
    
    wal = WAL(tmp_path)

    try:
        wal.append(1, 1, b'foo', b'bar')
    finally:
        wal.f.close()

    wal = WAL(tmp_path)
    try:
        wal.truncate()
    finally:
        wal.f.close()

    assert list(WAL(tmp_path).replay()) == []
    assert (tmp_path / 'wal.log').read_bytes() == b''


def test_invalid_op_type_raises(tmp_path):
    
    wal = WAL(tmp_path)

    try:
        try:
            wal.append(1, 3, b'bad', b'data')
            raise AssertionError('expected ValueError')
        except ValueError as exc:
            assert 'Invalid op_type' in str(exc)
    finally:
        wal.f.close()


def test_partial_header_stops_replay(tmp_path):
    
    (tmp_path / 'wal.log').write_bytes(b'12345')
    assert list(WAL(tmp_path).replay()) == []


def test_partial_body_stops_replay(tmp_path):
    
    header = struct.pack('>QBII', 1, 1, 4, 5)
    payload = header + b'key'
    (tmp_path / 'wal.log').write_bytes(payload)
    assert list(WAL(tmp_path).replay()) == []


def test_invalid_crc_stops_replay(tmp_path):
    
    header = struct.pack('>QBII', 1, 1, 3, 3)
    body = b'keyval'
    bad_crc = struct.pack('>I', 0)
    (tmp_path / 'wal.log').write_bytes(header + body + bad_crc)
    assert list(WAL(tmp_path).replay()) == []


def test_record_bytes_match_format(tmp_path):
    
    wal = WAL(tmp_path)

    try:
        wal.append(42, 1, b'abc', b'defg')
    finally:
        wal.f.close()

    raw = (tmp_path / 'wal.log').read_bytes()
    assert len(raw) == 17 + 3 + 4 + 4

    header = raw[:17]
    seq_no, op_type, key_len, val_len = struct.unpack('>QBII', header)
    assert seq_no == 42
    assert op_type == 1
    assert key_len == 3
    assert val_len == 4

    body = raw[17:-4]
    assert body == b'abcdefg'

    stored_crc, = struct.unpack('>I', raw[-4:])
    assert stored_crc == (zlib.crc32(header + body) & 0xFFFFFFFF)


def test_partial_write_replay_after_random_truncate(tmp_path):
    
    wal = WAL(tmp_path)

    try:
        wal.append(1, 1, b'a', b'one')
        wal.append(2, 1, b'b', b'two')
        wal.append(3, 1, b'c', b'three')
    finally:
        wal.f.close()

    data = (tmp_path / 'wal.log').read_bytes()
    assert len(data) > 0

    # First record is 25 bytes long, second record is also 25 bytes long.
    # Truncate after at least the first record so replay can yield a valid prefix.
    cut = random.randint(26, len(data) - 1)
    (tmp_path / 'wal.log').write_bytes(data[:cut])

    records = list(WAL(tmp_path).replay())
    assert records in (
        [(1, 1, b'a', b'one')],
        [(1, 1, b'a', b'one'), (2, 1, b'b', b'two')],
    )


def test_replay_on_same_open_wal_handle(tmp_path):
    
    wal = WAL(tmp_path)

    try:
        wal.append(1, 1, b'a', b'one')
        records = list(wal.replay())
        assert records == [(1, 1, b'a', b'one')]

        wal.append(2, 1, b'b', b'two')
    finally:
        wal.f.close()

    assert list(WAL(tmp_path).replay()) == [
        (1, 1, b'a', b'one'),
        (2, 1, b'b', b'two'),
    ]
