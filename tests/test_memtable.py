from stratum.memtable import MemTable

def test_put_and_get():
    mt = MemTable()
    mt.put(b"user:1", b"Alice", 1)
    assert mt.get(b"user:1") == b"Alice"


def test_put_overwrite_updates_value_and_size():
    mt = MemTable()
    mt.put(b"user:1", b"Alice", 1)
    first_size = mt.size
    mt.put(b"user:1", b"Bob", 2)
    assert mt.get(b"user:1") == b"Bob"
    assert mt.size < first_size + len(b"Bob")


def test_delete_writes_tombstone_and_returns_none():
    mt = MemTable()
    mt.put(b"user:1", b"Alice", 1)
    mt.delete(b"user:1", 2)
    assert mt.get(b"user:1") is None


def test_delete_nonexistent_key_still_writes_tombstone():
    mt = MemTable()
    mt.delete(b"user:2", 1)
    assert mt.get(b"user:2") is None


def test_items_returned_in_sorted_key_order():
    mt = MemTable()
    mt.put(b"b", b"two", 1)
    mt.put(b"a", b"one", 2)
    assert [k for k, _ in mt.items()] == [b"a", b"b"]
