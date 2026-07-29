import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from stratum.engine import Engine


class TestCompactionPartialUnlink(unittest.TestCase):
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

    def test_partial_unlink_failure(self):
        # Populate engine with two tables so that compaction will attempt to delete two old SSTables
        self.engine.put(b"k1", b"v1")
        self._flush()
        self.engine.put(b"k2", b"v2")
        self._flush()

        # Record the paths of the old SSTables before compaction
        old_paths = [t.path for t in self.engine.sstables]

        # Patch Path.unlink to raise OSError on the second call (simulating a failure)
        original_unlink = Path.unlink
        call_counter = {"count": 0}

        def side_effect(*args, **kwargs):
            """Simulate a failure on the second unlink call.

            The first call should delete the first old SSTable file. Since the
            mock does not provide the ``Path`` instance, we explicitly delete
            the known path from ``old_paths`` based on the call count.
            """
            call_counter["count"] += 1
            if call_counter["count"] == 1:
                # Delete the first old SSTable file to mimic successful unlink.
                original_unlink(old_paths[0])
                return None
            if call_counter["count"] == 2:
                raise OSError("simulated unlink failure")
            # Any further calls (should not happen) behave as a no‑op.
            return None

        with patch.object(Path, "unlink", side_effect=side_effect):
            # Perform compaction; the engine should handle the OSError internally
            self.engine.compact()

        # After compaction, data should still be readable
        self.assertEqual(self.engine.get(b"k1"), b"v1")
        self.assertEqual(self.engine.get(b"k2"), b"v2")

        # Exactly one of the original SSTable files should remain (the one that failed to delete)
        remaining_old = [p for p in old_paths if p.exists()]
        self.assertEqual(len(remaining_old), 1)

        # Engine should now have a single active SSTable
        self.assertEqual(len(self.engine.sstables), 1)


if __name__ == "__main__":
    unittest.main()
