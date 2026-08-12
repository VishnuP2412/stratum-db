import tempfile
from pathlib import Path

import pytest

from stratum.engine import Engine


@pytest.mark.timeout(120)
def test_compact_10000_entries():
    """Create 10,000 key/value pairs, compact them into an SSTable, and verify all entries.

    The test uses a temporary directory for the engine's data storage, ensuring no
    persistent files are left behind. After inserting the entries, ``engine.compact``
    merges any intermediate SSTables. Finally, each key is read back and compared
    to the original value.
    """

    # Use a temporary directory for the engine's data path
    with tempfile.TemporaryDirectory() as tmp_dir:
        data_path = Path(tmp_dir) / "data"
        data_path.mkdir(parents=True, exist_ok=True)

        engine = Engine(data_dir=data_path)

        # Insert 10,000 sequential entries
        total = 10_000
        for i in range(total):
            key = f"key{i:05d}".encode()
            value = f"value{i:05d}".encode()
            # seq_no is incremented automatically by Engine.put
            engine.put(key, value)

        # Force a compaction to flush memtables to SSTable(s) and merge them
        engine.compact()

        # Verify each entry can be read back correctly
        for i in range(total):
            key = f"key{i:05d}".encode()
            expected_value = f"value{i:05d}".encode()
            actual_value = engine.get(key)
            assert actual_value == expected_value, f"Mismatch for key {key!r}"
