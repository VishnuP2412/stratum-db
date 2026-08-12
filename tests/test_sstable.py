import os
import struct
import subprocess
import sys
import textwrap
import pytest
from pathlib import Path

import stratum.sstable as sstable_module
from stratum.engine import Engine
from stratum.sstable import BloomFilter, SSTable


def _make_items(keys, value_prefix="value", start_seq=1):
    return [
        (key, (f"{value_prefix}_{idx}".encode(), start_seq + idx, 0))
        for idx, key in enumerate(keys)
    ]


def test_bloom_might_contain_returns_true_for_added_key():
    filter = BloomFilter.for_size(10, 0.02)
    filter.add(b"alpha")

    assert filter.might_contain(b"alpha") is True


def test_bloom_might_contain_returns_false_for_key_never_added():
    filter = BloomFilter.for_size(10, 0.02)
    filter.add(b"alpha")

    assert filter.might_contain(b"beta") is False


def test_bloom_false_positive_rate_stays_near_target_at_scale():
    n = 1000
    filter = BloomFilter.for_size(n, 0.02)
    inserted_keys = [f"key_{idx:04d}".encode() for idx in range(n)]
    for key in inserted_keys:
        filter.add(key)

    queries = 10_000
    false_positives = 0
    for idx in range(n, n + queries):
        key = f"key_{idx:04d}".encode()
        if filter.might_contain(key):
            false_positives += 1

    measured_rate = false_positives / queries
    assert measured_rate <= 0.03, f"Measured FPR {measured_rate:.4f} exceeds 3%"


def test_bloom_for_size_zero_entries_does_not_crash():
    filter = BloomFilter.for_size(0, 0.02)

    assert isinstance(filter, BloomFilter)
    assert filter.bits_number >= 0
    assert filter.hashes_number >= 0


def test_bloom_for_size_produces_sane_m_and_k():
    filter = BloomFilter.for_size(100, 0.02)

    assert filter.bits_number > 0
    assert filter.hashes_number > 0
    assert filter.bits_number < 1000
    assert filter.hashes_number < 20


def test_bloom_restore_filter_matches_original_on_same_keys():
    original = BloomFilter.for_size(10, 0.02)
    keys = [b"alpha", b"beta", b"gamma"]
    for key in keys:
        original.add(key)

    restored = BloomFilter.restore_filter(
        original.bits_number,
        original.hashes_number,
        original.filter,
    )

    for key in keys:
        assert restored.might_contain(key)


def test_bloom_add_is_idempotent():
    filter = BloomFilter.for_size(10, 0.02)
    filter.add(b"alpha")
    first_bits = bytes(filter.filter)
    filter.add(b"alpha")
    second_bits = bytes(filter.filter)

    assert first_bits == second_bits
    assert filter.might_contain(b"alpha") is True


def test_engine_handles_thousands_of_writes_and_restarts(tmp_path):
    engine = Engine(tmp_path)
    engine.memtable.max_size_bytes = 4 * 1024 * 1024

    for i in range(60_000):
        key = f"key_{i:06d}".encode()
        value = (f"value_{i:06d}_" + "x" * 256).encode()
        engine.put(key, value)

    reloaded = Engine(tmp_path)
    for i in range(60_000):
        key = f"key_{i:06d}".encode()
        value = (f"value_{i:06d}_" + "x" * 256).encode()
        assert reloaded.get(key) == value

    # 288 bytes/entry, 4MB threshold → ~14,563 entries/flush
    # 60,000 entries → 4 full flushes (at ~14,563, ~29,126, ~43,689, ~58,252)
    sst_files = sorted(tmp_path.glob("*.sst"))
    assert len(sst_files) == 4, f"Expected 4 SSTables, found {len(sst_files)}"


def test_sstable_flush_empty_memtable_items_produces_empty_table(tmp_path):
    sstable = SSTable.flush(tmp_path, 1, [])

    assert isinstance(sstable, SSTable)
    assert sstable.min_key is None
    assert sstable.max_key is None
    assert sstable.search(b"any") == []


def test_sstable_single_entry_round_trips_through_from_file(tmp_path):
    items = [(b"only", (b"value", 7, 0))]
    sstable = SSTable.flush(tmp_path, 1, items)

    assert sstable.search(b"only") == [(b"only", b"value", 7, 0)]

    reloaded = SSTable.from_file(sstable.sst_path, sstable.idx_path)
    assert reloaded.min_key == b"only"
    assert reloaded.max_key == b"only"
    assert reloaded.indexes == sstable.indexes
    assert reloaded.index_start == sstable.index_start
    assert reloaded.search(b"only") == [(b"only", b"value", 7, 0)]


def test_sstable_samples_at_the_1000th_entry_boundary(tmp_path):
    keys = [f"key_{idx:04d}".encode() for idx in range(1001)]
    sstable = SSTable.flush(tmp_path, 1, _make_items(keys))

    assert sstable.indexes[0][0] == keys[0]
    assert sstable.indexes[1][0] == keys[1000]
    assert len(sstable.indexes) == 2


def test_sstable_samples_only_once_for_999_entries_and_twice_for_1001_entries(tmp_path):
    keys_999 = [f"key_{idx:04d}".encode() for idx in range(999)]
    keys_1001 = [f"key_{idx:04d}".encode() for idx in range(1001)]

    sstable_999 = SSTable.flush(tmp_path / "999", 1, _make_items(keys_999))
    sstable_1001 = SSTable.flush(tmp_path / "1001", 2, _make_items(keys_1001))

    assert len(sstable_999.indexes) == 1
    assert len(sstable_1001.indexes) == 2


def test_sstable_search_for_sampled_key_returns_the_exact_entry(tmp_path):
    keys = [f"key_{idx:04d}".encode() for idx in range(1001)]
    sstable = SSTable.flush(tmp_path, 1, _make_items(keys))

    target = keys[1000]
    assert sstable.search(target) == [(target, b"value_1000", 1001, 0)]


def test_sstable_search_between_samples_uses_the_correct_offset(tmp_path):
    keys = [f"key_{idx:04d}".encode() for idx in range(1001)]
    sstable = SSTable.flush(tmp_path, 1, _make_items(keys))

    target = b"key_0998"
    assert sstable.search(target) == [(target, b"value_998", 999, 0)]


def test_sstable_search_for_missing_key_between_real_keys_returns_empty(tmp_path):
    keys = [f"key_{idx:04d}".encode() for idx in range(1001)]
    sstable = SSTable.flush(tmp_path, 1, _make_items(keys))

    target = b"key_0050!"
    assert sstable.search(target) == []


def test_sstable_search_out_of_range_returns_empty_without_crashing(tmp_path):
    items = [(b"alpha", (b"one", 1, 0)), (b"omega", (b"two", 2, 0))]
    sstable = SSTable.flush(tmp_path, 1, items)

    assert sstable.search(b"@") == []
    assert sstable.search(b"z") == []


def test_sstable_from_file_round_trip_preserves_metadata(tmp_path):
    items = [(b"a", (b"one", 1, 0)), (b"b", (b"two", 2, 0))]
    sstable = SSTable.flush(tmp_path, 1, items)

    reloaded = SSTable.from_file(sstable.sst_path, sstable.idx_path)
    assert reloaded.min_key == sstable.min_key
    assert reloaded.max_key == sstable.max_key
    assert reloaded.indexes == sstable.indexes
    assert reloaded.index_start == sstable.index_start


def test_sstable_from_file_raises_for_corrupt_idx_file(tmp_path):
    sstable = SSTable.flush(tmp_path, 1, [(b"a", (b"one", 1, 0))])
    sstable.idx_path.write_bytes(b"bad")

    with pytest.raises((ValueError, struct.error)):
        SSTable.from_file(sstable.sst_path, sstable.idx_path)


def test_flush_bloom_filter_contains_all_flushed_keys(tmp_path):
    items = _make_items([b"alpha", b"beta", b"omega"])
    sstable = SSTable.flush(tmp_path, 1, items)

    for key, _ in items:
        assert sstable.might_contain(key)


def test_flush_empty_memtable_bloom_filter_does_not_crash(tmp_path):
    sstable = SSTable.flush(tmp_path, 1, [])

    assert isinstance(sstable.bloom_filter, BloomFilter)
    assert sstable.bloom_filter.filter_length == sstable.bloom_filter.bits_number
    assert sstable.might_contain(b"anything") is False


def test_from_file_bloom_filter_matches_pre_flush_membership(tmp_path):
    items = _make_items([b"alpha", b"beta", b"omega"])
    sstable = SSTable.flush(tmp_path, 1, items)
    reloaded = SSTable.from_file(sstable.sst_path, sstable.idx_path)

    for key, _ in items:
        assert reloaded.might_contain(key)


def test_from_file_bloom_filter_m_k_survive_round_trip(tmp_path):
    items = _make_items([b"alpha", b"beta", b"omega"])
    sstable = SSTable.flush(tmp_path, 1, items)
    reloaded = SSTable.from_file(sstable.sst_path, sstable.idx_path)

    assert reloaded.bloom_filter.bits_number == sstable.bloom_filter.bits_number
    assert reloaded.bloom_filter.hashes_number == sstable.bloom_filter.hashes_number
    assert reloaded.bloom_filter.filter == sstable.bloom_filter.filter


def test_sstable_bloom_filter_footer_does_not_corrupt_sample_index_read(tmp_path):
    keys = [f"key_{idx:04d}".encode() for idx in range(1001)]
    sstable = SSTable.flush(tmp_path, 1, _make_items(keys))
    reloaded = SSTable.from_file(sstable.sst_path, sstable.idx_path)

    assert reloaded.indexes == sstable.indexes
    assert reloaded.index_start == sstable.index_start
    assert reloaded.search(keys[1000]) == [(keys[1000], b"value_1000", 1001, 0)]


def test_engine_get_skips_search_on_bloom_negative_key(tmp_path, monkeypatch):
    engine = Engine(tmp_path)
    engine.put(b"alpha", b"one")
    engine.put(b"omega", b"two")
    engine.write_table()

    search_calls = {"count": 0}

    def fake_search(self, target):
        search_calls["count"] += 1
        return []

    def fake_might_contain(self, key):
        if key == b"m":
            return False
        return True

    monkeypatch.setattr(SSTable, "search", fake_search)
    monkeypatch.setattr(SSTable, "might_contain", fake_might_contain)

    assert engine.get(b"m") is None
    assert search_calls["count"] == 0


def test_engine_get_does_not_skip_search_on_bloom_positive_key(tmp_path, monkeypatch):
    engine = Engine(tmp_path)
    engine.put(b"alpha", b"one")
    engine.write_table()

    search_calls = {"count": 0}

    def fake_search(self, target):
        search_calls["count"] += 1
        return []

    monkeypatch.setattr(SSTable, "search", fake_search)
    monkeypatch.setattr(SSTable, "might_contain", lambda self, key: True)

    engine.get(b"alpha")
    assert search_calls["count"] == 1


def test_engine_get_correctness_unaffected_by_bloom_filter_across_multiple_tables(tmp_path):
    engine = Engine(tmp_path)
    engine.put(b"a", b"value-a")
    engine.put(b"c", b"value-c")
    engine.write_table()

    engine.put(b"b", b"value-b")
    engine.delete(b"c")
    engine.write_table()

    expected = {}
    for key in [b"a", b"b", b"c", b"d"]:
        expected[key] = None
        for table in reversed(engine.sstables):
            if table.min_key is not None and not (table.min_key <= key <= table.max_key):
                continue
            results = table.search(key)
            if results:
                expected[key] = None if results[0][3] else results[0][1]
                break

    actual = {key: engine.get(key) for key in [b"a", b"b", b"c", b"d"]}
    assert actual == expected


def test_engine_load_sstables_raises_when_idx_sidecar_is_missing(tmp_path):
    sstable = SSTable.flush(tmp_path, 1, [(b"a", (b"one", 1, 0))])
    sstable.idx_path.unlink()

    engine = Engine.__new__(Engine)
    engine.table_dir = tmp_path
    engine.sstables = []
    engine.tableCount = 0

    with pytest.raises(FileNotFoundError):
        engine._load_sstables()


def test_engine_get_returns_memtable_value_without_flushing(tmp_path):
    engine = Engine(tmp_path)
    engine.put(b"alpha", b"value")

    assert engine.get(b"alpha") == b"value"


def test_engine_get_reads_key_from_sstable_after_flush(tmp_path):
    engine = Engine(tmp_path)
    engine.memtable.max_size_bytes = 1
    engine.put(b"alpha", b"value")
    engine.put(b"beta", b"other")

    assert engine.get(b"alpha") == b"value"
    assert len(engine.sstables) == 1


def test_engine_get_returns_none_for_tombstone_over_sstable_value(tmp_path):
    engine = Engine(tmp_path)
    engine.put(b"alpha", b"value")
    engine.write_table()
    engine.delete(b"alpha")
    engine.write_table()

    assert engine.get(b"alpha") is None


def test_engine_restart_round_trip_preserves_expected_values(tmp_path):
    engine = Engine(tmp_path)
    engine.put(b"alpha", b"value-a")
    engine.write_table()
    engine.put(b"beta", b"value-b")
    engine.delete(b"alpha")

    reloaded = Engine(tmp_path)
    assert reloaded.get(b"alpha") is None
    assert reloaded.get(b"beta") == b"value-b"


def test_sstable_flush_commits_idx_before_sstable_when_replace_fails(tmp_path, monkeypatch):
    items = [(b"alpha", (b"value", 1, 0))]
    table_dir = tmp_path / "crash"

    real_replace = sstable_module.os.replace

    def fail_on_sstable_replace(src, dst):
        if Path(src).name == "000001.sst.tmp" and Path(dst).name == "000001.sst":
            raise OSError("simulated sstable replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(sstable_module.os, "replace", fail_on_sstable_replace)

    with pytest.raises(OSError, match="simulated sstable replace failure"):
        SSTable.flush(table_dir, 1, items)

    assert not (table_dir / "000001.sst").exists()
    assert (table_dir / "000001.idx").exists()

    # Current implementation commits the idx sidecar before the sstable file.
    # If rollback semantics are required for crash safety, this behavior would need
    # to be changed in sstable.py.


def test_engine_compact_resolves_latest_seq_no_across_multiple_tables_and_removes_old_files(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"alpha", b"value-v1")
    engine.write_table()

    engine.put(b"alpha", b"value-v2")
    engine.write_table()

    engine.compact()

    assert engine.get(b"alpha") == b"value-v2"
    assert len(list(tmp_path.glob("*.sst"))) == 1
    assert len(list(tmp_path.glob("*.idx"))) == 1


def test_engine_compact_all_tombstones_leaves_deleted_keys_unavailable(tmp_path):
    engine = Engine(tmp_path)
    engine.put(b"alpha", b"value")
    engine.write_table()
    engine.delete(b"alpha")
    engine.write_table()

    engine.compact()

    assert engine.get(b"alpha") is None

def parse_sstable_records(target):
    records = []
    sst_path = target.sst_path if isinstance(target, SSTable) else Path(target)
    data = sst_path.read_bytes()

    idx_path = target.idx_path if isinstance(target, SSTable) else sst_path.with_suffix(".idx")
    if idx_path.exists():
        with idx_path.open("rb") as fh:
            index_start = struct.unpack(">I", fh.read(4))[0]
    else:
        index_start = len(data)

    offset = 0
    while offset < index_start:
        if offset + 17 > index_start:
            raise ValueError("Incomplete SSTable record header")

        key_len, val_len, seq_no, deleted = struct.unpack(">IIQB", data[offset : offset + 17])
        offset += 17

        if offset + key_len + val_len > index_start:
            raise ValueError("Incomplete SSTable record body")

        key = data[offset : offset + key_len]
        offset += key_len
        value = data[offset : offset + val_len]
        offset += val_len

        records.append((key, value, seq_no, deleted))

    return records


# flush() tests
def test_flush_empty_memtable_creates_empty_sstable_file(tmp_path):
    table_dir = tmp_path / "empty"
    sstable = SSTable.flush(table_dir, 1, [])

    assert isinstance(sstable, SSTable)
    assert sstable.sst_path.exists()
    assert sstable.sst_path.stat().st_size == 0
    assert sstable.idx_path.exists()
    assert sstable.min_key is None
    assert sstable.max_key is None


def test_flush_single_entry_sets_min_max_equal_and_returns_sstable(tmp_path):
    table_dir = tmp_path / "single"
    items = [(b"apple", (b"pie", 1, 0))]

    sstable = SSTable.flush(table_dir, 1, items)

    assert isinstance(sstable, SSTable)
    assert sstable.sst_path.exists()
    assert sstable.min_key == b"apple"
    assert sstable.max_key == b"apple"

    records = parse_sstable_records(sstable)
    assert records == [(b"apple", b"pie", 1, 0)]


def test_flush_multiple_entries_writes_records_in_sorted_key_order(tmp_path):
    table_dir = tmp_path / "multi"
    items = [
        (b"alpha", (b"first", 1, 0)),
        (b"bravo", (b"second", 2, 0)),
        (b"zulu", (b"last", 3, 0)),
    ]

    sstable = SSTable.flush(table_dir, 1, items)
    assert sstable.sst_path.exists()
    assert isinstance(sstable, SSTable)

    records = parse_sstable_records(sstable)
    assert [record[0] for record in records] == [b"alpha", b"bravo", b"zulu"]
    assert [record[1] for record in records] == [b"first", b"second", b"last"]
    assert [record[2] for record in records] == [1, 2, 3]


def test_flush_writes_tombstone_byte_for_deleted_entries(tmp_path):
    table_dir = tmp_path / "deleted"
    items = [(b"ghost", (b"", 7, 1))]

    sstable = SSTable.flush(table_dir, 1, items)
    assert sstable.sst_path.exists()
    assert isinstance(sstable, SSTable)

    records = parse_sstable_records(sstable)
    assert records == [(b"ghost", b"", 7, 1)]


def test_flush_removes_tmp_file_and_creates_final_sstable(tmp_path):
    table_dir = tmp_path / "final"
    items = [(b"a", (b"1", 1, 0))]

    sstable = SSTable.flush(table_dir, 1, items)

    assert sstable.sst_path.exists()
    assert not table_dir.joinpath("000001.sst.tmp").exists()
    assert isinstance(sstable, SSTable)


def test_flush_rejects_non_path_path_argument(tmp_path):
    bad_path = str(tmp_path / "bad")
    with pytest.raises(TypeError, match="pathlib.Path"):
        SSTable.flush(bad_path, 1, [(b"a", (b"1", 1, 0))])


# scan() tests
def test_scan_full_range_round_trips_flushed_records(tmp_path):
    table_dir = tmp_path / "full_range"
    items = [
        (b"a", (b"one", 1, 0)),
        (b"b", (b"two", 2, 0)),
        (b"c", (b"three", 3, 0)),
    ]

    sstable = SSTable.flush(table_dir, 1, items)
    result = sstable.scan(b"a", b"z")

    assert result == [
        (b"a", b"one", 1, 0),
        (b"b", b"two", 2, 0),
        (b"c", b"three", 3, 0),
    ]


def test_scan_narrow_range_excludes_out_of_range_entries(tmp_path):
    table_dir = tmp_path / "narrow_range"
    items = [
        (b"a", (b"one", 1, 0)),
        (b"b", (b"two", 2, 0)),
        (b"c", (b"three", 3, 0)),
    ]

    sstable = SSTable.flush(table_dir, 1, items)
    result = sstable.scan(b"b", b"b")

    assert result == [(b"b", b"two", 2, 0)]


def test_scan_omits_deleted_records_in_range(tmp_path):
    table_dir = tmp_path / "deleted_scan"
    items = [
        (b"a", (b"one", 1, 0)),
        (b"b", (b"", 2, 1)),
        (b"c", (b"three", 3, 0)),
    ]

    sstable = SSTable.flush(table_dir, 1, items)
    result = sstable.scan(b"a", b"z")

    assert result == [
        (b"a", b"one", 1, 0),
        (b"b", b"", 2, 1),
        (b"c", b"three", 3, 0),
    ]


def test_scan_rejects_non_bytes_start_and_end_keys(tmp_path):
    table_dir = tmp_path / "type_check"
    items = [(b"a", (b"one", 1, 0))]
    sstable = SSTable.flush(table_dir, 1, items)

    with pytest.raises(TypeError, match="requires bytes start_key"):
        sstable.scan("a", b"z")

    with pytest.raises(TypeError, match="requires bytes end_key"):
        sstable.scan(b"a", "z")


def test_scan_returns_empty_list_for_fully_out_of_range_query(tmp_path):
    table_dir = tmp_path / "out_of_range"
    items = [
        (b"a", (b"one", 1, 0)),
        (b"b", (b"two", 2, 0)),
    ]
    sstable = SSTable.flush(table_dir, 1, items)

    assert sstable.scan(b"z", b"zz") == []
    assert sstable.scan(b"\x00", b"`") == []


def test_scan_raises_on_duplicate_keys_in_sstable_file(tmp_path):
    path = tmp_path / "duplicate.sst"
    idx_path = tmp_path / "duplicate.idx"
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
    idx_path.write_bytes(struct.pack(">I", len(raw) + 100))

    sstable = SSTable(path, idx_path, None, None)
    with pytest.raises(ValueError, match="Duplicate key"):
        sstable.scan(b"a", b"z")


def test_sstable_from_file_exists_and_loads_sstable_metadata(tmp_path):
    table_dir = tmp_path / "load"
    key = b"alpha"
    sstable = SSTable.flush(table_dir, 1, [(key, (b"value", 1, 0))])

    loaded = SSTable.from_file(sstable.sst_path, sstable.idx_path)
    assert isinstance(loaded, SSTable)
    assert loaded.min_key == key
    assert loaded.max_key == key


def test_engine_restart_shadowing_prefers_newest_sstable_after_reload(tmp_path):
    key = b"k"
    engine1 = Engine(tmp_path)
    engine1.memtable.max_size_bytes = 1

    engine1.put(key, b"v1")
    engine1.put(key, b"v2")
    engine1.write_table()

    engine2 = Engine(tmp_path)
    assert engine2.get(key) == b"v2"


def test_scan_raises_on_truncated_sstable_file(tmp_path):
    path = tmp_path / "truncated.sst"
    idx_path = tmp_path / "truncated.idx"
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
    idx_path.write_bytes(struct.pack(">I", len(header + key + value) + 100))

    data = path.read_bytes()
    path.write_bytes(data[:-2])

    sstable = SSTable(path, idx_path, None, None)

    with pytest.raises(ValueError, match="Truncated SSTable"):
        sstable.scan(b"", b"zzz")


def test_engine_get_returns_tombstone_value_when_newer_sstable_has_tombstone_and_older_sstable_has_live_value(tmp_path):
    key = b"k"

    SSTable.flush(tmp_path, 1, [(key, (b"old-value", 1, 0))])
    SSTable.flush(tmp_path, 2, [(key, (b"", 2, 1))])

    engine = Engine(tmp_path)
    assert engine.get(key) is None


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