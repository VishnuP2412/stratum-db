"""Run a compaction on the existing Stratum engine data.

This script assumes that the large data set (the 5 000 SSTable files) has
already been generated in ``tmp_long_data`` and ``tmp_long_tables``.  It
simply loads the engine, prints its own PID (so the caller can kill it),
executes ``engine.compact()`` and exits.

The script does **not** delete or recreate any files – it works on the
existing on‑disk state.
"""

import os
import time
from pathlib import Path

from stratum.engine import Engine

# Directories must match those used by ``run_long_compaction.py``
DATA_DIR = Path("tmp_long_data")
TABLE_DIR = Path("tmp_long_tables")

engine = Engine(DATA_DIR, TABLE_DIR)

print(f"Compaction PID: {os.getpid()}")
start = time.time()
# The actual compaction – this may take several seconds depending on the
# number of SSTable files present.
engine.compact()
elapsed = time.time() - start
print(f"Compaction finished in {elapsed:.1f}s")
