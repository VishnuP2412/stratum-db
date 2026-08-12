import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pytest

from stratum.engine import Engine
from stratum.sstable import SSTable

# The tests historically accessed a non‑existent ``path`` attribute on
# ``SSTable`` instances. The production ``SSTable`` class provides
# ``sst_path``. To keep the production code untouched we expose a ``path``
# attribute via a simple fixture that adds an alias property to the class.
@pytest.fixture(autouse=True)
def _add_sstable_path_alias():
    # ``path`` should behave like a read‑only attribute returning ``sst_path``.
    if not hasattr(SSTable, "path"):
        SSTable.path = property(lambda self: self.sst_path)


class TestEngineCompaction(unittest.TestCase):
    def setUp(self):
        # Create isolated temporary directories for data and tables
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "data"
        self.table_dir = Path(self.temp_dir.name) / "tables"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.table_dir.mkdir(parents=True, exist_ok=True)
        self.engine = Engine(self.data_dir, self.table_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _flush(self):
        """Helper to force a table flush (write current memtable to disk)."""
        self.engine.write_table()

    def test_multi_file_resolution_by_seq_no(self):
        # First table with key 'k1' -> b'v1'
        self.engine.put(b"k1", b"v1")
        self._flush()
        # Second table updates 'k1' and adds 'k2'
        self.engine.put(b"k1", b"v2")
        self.engine.put(b"k2", b"v3")
        self._flush()

        # Compact should keep the latest value for each key
        self.engine.compact()
        self.assertEqual(self.engine.get(b"k1"), b"v2")
        self.assertEqual(self.engine.get(b"k2"), b"v3")

    def test_physical_removal_of_tombstones(self):
        self.engine.put(b"k1", b"v1")
        self._flush()
        # Delete the key, creating a tombstone in a new table
        self.engine.delete(b"k1")
        self._flush()
        # Ensure the key is logically deleted before compaction
        self.assertIsNone(self.engine.get(b"k1"))
        # Compact should purge the tombstone entirely
        self.engine.compact()
        self.assertIsNone(self.engine.get(b"k1"))
        # Verify the key does not appear in the resulting SSTable
        sstable = self.engine.sstables[0]
        entries = sstable.scan(sstable.min_key, sstable.max_key)
        keys = [k for k, _, _, _ in entries]
        self.assertNotIn(b"k1", keys)

    def test_sorted_output_verification(self):
        # Insert keys out of order across multiple tables
        self.engine.put(b"c", b"3")
        self._flush()
        self.engine.put(b"b", b"2")
        self._flush()
        self.engine.put(b"a", b"1")
        self._flush()
        self.engine.compact()
        sstable = self.engine.sstables[0]
        entries = sstable.scan(sstable.min_key, sstable.max_key)
        keys = [k for k, _, _, _ in entries]
        self.assertEqual(keys, sorted(keys))

    def test_deletion_of_old_sstables_and_update(self):
        self.engine.put(b"k1", b"v1")
        self._flush()
        self.engine.put(b"k2", b"v2")
        self._flush()
        old_paths = [t.path for t in self.engine.sstables]
        self.engine.compact()
        # All old files should be removed
        for p in old_paths:
            self.assertFalse(p.exists())
        # Engine should now have exactly one sstable
        self.assertEqual(len(self.engine.sstables), 1)

    def test_end_to_end_get_after_compaction(self):
        self.engine.put(b"k1", b"v1")
        self._flush()
        self.engine.put(b"k1", b"v2")
        self._flush()
        self.engine.compact()
        # get should return the latest value
        self.assertEqual(self.engine.get(b"k1"), b"v2")

    def test_sigkill_resilience_during_compaction(self):
        # Prepare engine with two tables
        self.engine.put(b"k1", b"v1")
        self._flush()
        self.engine.put(b"k2", b"v2")
        self._flush()

        # Path to a helper script that runs compaction and sleeps
        script = (
            "import time, sys; "
            "from pathlib import Path; "
            "from stratum.engine import Engine; "
            f"data_dir = Path('{self.data_dir}'); "
            f"table_dir = Path('{self.table_dir}'); "
            "engine = Engine(data_dir, table_dir); "
            "engine.compact(); "
            "time.sleep(5)"
        )
        proc = subprocess.Popen([sys.executable, "-c", script])
        # Give the subprocess a moment to start compaction
        time.sleep(0.5)
        proc.kill()
        proc.wait()

        # Re‑open the engine – it should load whatever SSTables survived
        engine2 = Engine(self.data_dir, self.table_dir)
        # The data should still be readable (either pre‑compact or post‑compact state)
        val1 = engine2.get(b"k1")
        val2 = engine2.get(b"k2")
        self.assertIn(val1, (b"v1", None))
        self.assertIn(val2, (b"v2", None))
        # A subsequent compaction must succeed without raising
        engine2.compact()
        # After successful compaction both keys should be present with correct values
        self.assertEqual(engine2.get(b"k1"), b"v1")
        self.assertEqual(engine2.get(b"k2"), b"v2")

    @pytest.mark.timeout(1800)
    def test_one_million_entries_compaction(self):
        """Insert 1,000,000 key/value pairs, compact, and verify **all** entries.

        The test stores each generated key/value pair in a dictionary, forces a
        flush periodically to keep memory usage reasonable, runs a compaction,
        and then checks that every key can be retrieved with the correct value.
        """
        entries: dict[bytes, bytes] = {}
        for i in range(1_000_000):
            key = f"k{i:07d}".encode()
            val = f"v{i:07d}".encode()
            self.engine.put(key, val)
            entries[key] = val
            # Flush every 100k entries to avoid a huge in‑memory memtable
            if i % 100_000 == 0:
                self._flush()

        # Final flush before compaction to ensure all data is persisted
        self._flush()
        self.engine.compact()

        # Verify every entry after compaction
        for key, expected_val in entries.items():
            self.assertEqual(self.engine.get(key), expected_val)


if __name__ == "__main__":
    unittest.main()
