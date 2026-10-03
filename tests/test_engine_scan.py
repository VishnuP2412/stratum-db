from stratum.engine import Engine


def scan(engine, start_key, end_key):
    return list(engine.scan(start_key, end_key))

def test_scan_multi_result_range(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"b", b"two")
    engine.put(b"c", b"three")
    engine.put(b"d", b"four")

    assert scan(engine, b"b", b"d") == [
        (b"b", b"two"),
        (b"c", b"three"),
        (b"d", b"four"),
    ]


def test_scan_empty_range(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"b", b"two")
    engine.put(b"d", b"four")

    assert scan(engine, b"x", b"z") == []
    assert scan(engine, b"d", b"b") == []


def test_scan_across_sstables_after_compaction(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"a", b"a-value")
    engine.put(b"b", b"b-value")
    engine.write_table()

    engine.put(b"d", b"d-value")
    engine.put(b"e", b"e-value")
    engine.write_table()

    engine.compact()

    # Compaction has produced one SSTable. Create a newer one afterward.
    engine.put(b"g", b"g-value")
    engine.put(b"h", b"h-value")
    engine.write_table()

    assert len(engine.sstables) == 2

    assert scan(engine, b"b", b"h") == [
        (b"b", b"b-value"),
        (b"d", b"d-value"),
        (b"e", b"e-value"),
        (b"g", b"g-value"),
        (b"h", b"h-value"),
    ]


def test_scan_suppresses_live_tombstone(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"deleted", b"old-value")
    engine.write_table()

    engine.delete(b"deleted")

    assert scan(engine, b"deleted", b"deleted") == []


def test_scan_includes_end_key(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"a", b"a-value")
    engine.put(b"b", b"b-value")
    engine.put(b"c", b"c-value")

    assert scan(engine, b"a", b"b") == [
        (b"a", b"a-value"),
        (b"b", b"b-value"),
    ]


def test_scan_uses_newer_memtable_value_over_older_sstable_value(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"a", b"old")
    engine.write_table()

    engine.put(b"a", b"new")

    assert scan(engine, b"a", b"a") == [
        (b"a", b"new"),
    ]

def test_scan_suppresses_flushed_tombstone(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"a", b"old")
    engine.write_table()

    engine.delete(b"a")
    engine.write_table()

    assert scan(engine, b"a", b"a") == []


def test_scan_suppresses_tombstone_from_newer_sstable(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"a", b"old")
    engine.write_table()

    engine.delete(b"a")
    engine.write_table()

    assert len(engine.sstables) == 2
    assert scan(engine, b"a", b"a") == []


def test_empty(tmp_path):
    engine = Engine(tmp_path)

    engine.put(b"b", b"two")
    engine.put(b"c", b"three")
    engine.put(b"d", b"four")

    assert scan(engine, b"d", b"b") == []