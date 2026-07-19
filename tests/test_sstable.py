import os
import struct
import subprocess
import sys
import textwrap
import pytest
from pathlib import Path

from stratum.engine import Engine
from stratum.sstable import SSTable


def parse_sstable_records(path):
    records = []
    data = path.read_bytes()
    offset = 0

    while offset < len(data):
        if offset + 17 > len(data):
            raise ValueError("Incomplete SSTable record header")

        key_len, val_len, seq_no, deleted = struct.unpack(">IIQB", data[offset : offset + 17])
        offset += 17

        if offset + key_len + val_len > len(data):
            raise ValueError("Incomplete SSTable record body")

        key = data[offset : offset + key_len]
        offset += key_len
        value = data[offset : offset + val_len]
        offset += val_len

        records.append((key, value, seq_no, deleted))

    return records


# flush() tests
def test_flush_empty_memtable_creates_empty_sstable_file(tmp_path):
    path = tmp_path / "empty.sst"
    sstable = SSTable.flush(path, [])

    assert isinstance(sstable, SSTable)
    assert path.exists()
    assert path.stat().st_size == 0
    assert sstable.min_key is None
    assert sstable.max_key is None


def test_flush_single_entry_sets_min_max_equal_and_returns_sstable(tmp_path):
    path = tmp_path / "single.sst"
    items = [(b"apple", (b"pie", 1, 0))]

    sstable = SSTable.flush(path, items)

    assert isinstance(sstable, SSTable)
    assert path.exists()
    assert sstable.min_key == b"apple"
    assert sstable.max_key == b"apple"
    assert sstable.path == path

    records = parse_sstable_records(path)
    assert records == [(b"apple", b"pie", 1, 0)]


def test_flush_multiple_entries_writes_records_in_sorted_key_order(tmp_path):
    path = tmp_path / "multi.sst"
    items = [
        (b"alpha", (b"first", 1, 0)),
        (b"bravo", (b"second", 2, 0)),
        (b"zulu", (b"last", 3, 0)),
    ]

    sstable = SSTable.flush(path, items)
    assert path.exists()
    assert isinstance(sstable, SSTable)

    records = parse_sstable_records(path)
    assert [record[0] for record in records] == [b"alpha", b"bravo", b"zulu"]
    assert [record[1] for record in records] == [b"first", b"second", b"last"]
    assert [record[2] for record in records] == [1, 2, 3]


def test_flush_writes_tombstone_byte_for_deleted_entries(tmp_path):
    path = tmp_path / "deleted.sst"
    items = [(b"ghost", (b"", 7, 1))]

    sstable = SSTable.flush(path, items)
    assert path.exists()
    assert isinstance(sstable, SSTable)

    records = parse_sstable_records(path)
    assert records == [(b"ghost", b"", 7, 1)]


def test_flush_removes_tmp_file_and_creates_final_sstable(tmp_path):
    path = tmp_path / "final.sst"
    items = [(b"a", (b"1", 1, 0))]

    sstable = SSTable.flush(path, items)

    assert path.exists()
    assert not tmp_path.joinpath("final.sst.tmp").exists()
    assert isinstance(sstable, SSTable)


def test_flush_rejects_non_path_path_argument(tmp_path):
    bad_path = str(tmp_path / "bad.sst")
    with pytest.raises(TypeError, match="pathlib.Path"):
        SSTable.flush(bad_path, [(b"a", b"1", 1, 0)])


# scan() tests
def test_scan_full_range_round_trips_flushed_records(tmp_path):
    path = tmp_path / "full_range.sst"
    items = [
        (b"a", (b"one", 1, 0)),
        (b"b", (b"two", 2, 0)),
        (b"c", (b"three", 3, 0)),
    ]

    sstable = SSTable.flush(path, items)
    result = sstable.scan(b"a", b"z")

    assert result == [(b"a", b"one", 1), (b"b", b"two", 2), (b"c", b"three", 3)]


def test_scan_narrow_range_excludes_out_of_range_entries(tmp_path):
    path = tmp_path / "narrow_range.sst"
    items = [
        (b"a", (b"one", 1, 0)),
        (b"b", (b"two", 2, 0)),
        (b"c", (b"three", 3, 0)),
    ]

    sstable = SSTable.flush(path, items)
    result = sstable.scan(b"b", b"b")

    assert result == [(b"b", b"two", 2)]


def test_scan_omits_deleted_records_in_range(tmp_path):
    path = tmp_path / "deleted_scan.sst"
    items = [
        (b"a", (b"one", 1, 0)),
        (b"b", (b"", 2, 1)),
        (b"c", (b"three", 3, 0)),
    ]

    sstable = SSTable.flush(path, items)
    result = sstable.scan(b"a", b"z")

    assert all(record[0] != b"b" for record in result)
    assert result == [(b"a", b"one", 1), (b"c", b"three", 3)]


def test_scan_rejects_non_bytes_start_and_end_keys(tmp_path):
    path = tmp_path / "type_check.sst"
    items = [(b"a", (b"one", 1, 0))]
    sstable = SSTable.flush(path, items)

    with pytest.raises(TypeError, match="requires bytes start_key"):
        sstable.scan("a", b"z")

    with pytest.raises(TypeError, match="requires bytes end_key"):
        sstable.scan(b"a", "z")


def test_scan_returns_empty_list_for_fully_out_of_range_query(tmp_path):
    path = tmp_path / "out_of_range.sst"
    items = [
        (b"a", (b"one", 1, 0)),
        (b"b", (b"two", 2, 0)),
    ]
    sstable = SSTable.flush(path, items)

    assert sstable.scan(b"z", b"zz") == []
    assert sstable.scan(b"\x00", b"`") == []


def test_scan_raises_on_duplicate_keys_in_sstable_file(tmp_path):
    path = tmp_path / "duplicate.sst"
    key = b"dup"
    value = b"value"
    header = struct.pack(
        ">IIQB",
        len(key),
        len(value),
        1,
        0,
    )
    raw = header + key + value + header + key + value
    path.write_bytes(raw)

    sstable = SSTable(path, None, None)
    with pytest.raises(ValueError, match="Duplicate key"):
        sstable.scan(b"a", b"z")


def test_scan_raises_on_truncated_sstable_file(tmp_path):
    path = tmp_path / "truncated.sst"
    key = b"abc"
    value = b"def"
    seq_no = 1
    deleted = 0

    header = struct.pack(
        ">IIQB",
        len(key),
        len(value),
        seq_no,
        deleted,
    )
    path.write_bytes(header + key + value)

    data = path.read_bytes()
    path.write_bytes(data[:-2])

    sstable = SSTable(path, None, None)

    with pytest.raises(ValueError, match="Truncated SSTable"):
        sstable.scan(b"", b"zzz")


# kill-9 tests
CRASH_WRITER = Path(__file__).parent / "DataWriter.py"


def _run_kill_harness(data_dir, child_code, kill_marker, occurrence=1):
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", child_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    killed = False
    seen = 0
    try:
        for line in proc.stdout:
            if line.strip() == kill_marker:
                seen += 1
                if seen == occurrence:
                    proc.kill()
                    killed = True
                    break
    finally:
        proc.wait(timeout=5)

    assert killed, f"Writer exited before {kill_marker} occurrence {occurrence}"


def _build_child_script(data_dir, script_body):
    return textwrap.dedent(f"""
        import os
        import time
        from pathlib import Path
        from stratum.engine import Engine

        data_dir = Path(r'{data_dir}')
        engine = Engine(data_dir)
        engine.memtable.max_size_bytes = 1

        orig_replace = os.replace

        def replace_and_pause(src, dst):
            print('REPLACE_ENTER', flush=True)
            time.sleep(10)
            return orig_replace(src, dst)

        os.replace = replace_and_pause

        {script_body}
    """)


def test_kill_during_flush_before_rename_preserves_wal_and_prevents_sstable_exposure(tmp_path):
    data_dir = tmp_path / "kill_before_rename"
    data_dir.mkdir()

    child_body = """
        engine.put(b'key_0001', b'value_0001')
        engine.put(b'key_0002', b'value_0002')
    """

    child_code = _build_child_script(data_dir, child_body)
    _run_kill_harness(data_dir, child_code, "REPLACE_ENTER")

    assert not list(data_dir.glob("*.sst")), "No completed SSTable should exist after kill before rename"
    wal_path = data_dir / "wal.log"
    assert wal_path.exists(), "WAL must still exist after interrupted flush"

    recovered = Engine(data_dir)
    assert recovered.get(b'key_0001') == b'value_0001'
    assert recovered.get(b'key_0002') is None


def test_kill_after_replace_before_wal_truncate_replays_redundant_entries_safely(tmp_path):
    data_dir = tmp_path / "kill_after_replace"
    data_dir.mkdir()

    child_body = """
        engine.put(b'key_0001', b'value_0001')

        orig_truncate = engine.wal.truncate

        def truncate_and_pause():
            print('TRUNCATE_ENTER', flush=True)
            time.sleep(10)
            return orig_truncate()

        engine.wal.truncate = truncate_and_pause
        engine.put(b'key_0002', b'value_0002')
    """

    child_code = _build_child_script(data_dir, child_body)
    _run_kill_harness(data_dir, child_code, "TRUNCATE_ENTER", occurrence=1)

    recovered = Engine(data_dir)
    assert recovered.get(b'key_0001') == b'value_0001'
    assert recovered.get(b'key_0002') is None
    assert recovered._seq_no == 1


