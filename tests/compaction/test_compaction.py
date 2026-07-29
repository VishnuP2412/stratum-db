import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from stratum.engine import Engine


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


if __name__ == "__main__":
    unittest.main()
