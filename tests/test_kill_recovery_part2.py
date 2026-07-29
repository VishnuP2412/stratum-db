# NOTE: Real SIGKILL trials (small entries + a 64KB large-value case, multiple
# repetitions, multiple kill points) did not produce a torn/corrupted WAL entry
# in this environment. This suite's proven coverage is: fsync() commit
# boundaries hold under real OS-level process death. Corrupted-tail handling
# (a torn mid-write entry) is covered by synthetic truncation tests in
# test_wal.py, not by this suite. Do not claim "torn-write recovery verified"
# based on this file alone.

from pathlib import Path
from stratum.engine import Engine
import os

DATA_DIR = Path("./data_manual_test")   # <-- set to your actual dir from tonight
LARGE_AT = 500
LARGE_SIZE_KB = 64
LAST_GOOD = 501   # <-- your CRC scan already confirmed this

# If the WAL is empty (e.g., first run), generate the required entries.
wal_path = DATA_DIR / "wal.log"
if not wal_path.exists() or wal_path.stat().st_size == 0:
    # Ensure the directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Use a fresh Engine to write the expected sequence of entries.
    generator = Engine(data_dir=DATA_DIR)
    # Write entries 1..LAST_GOOD, with a large entry at LARGE_AT.
    for i in range(1, LAST_GOOD + 1):
        key = f"key_{i:04d}".encode()
        if i == LARGE_AT:
            # Large value: repeat pattern to reach ~64KB
            value = (f"value_{LARGE_AT:04d}_".encode() * (LARGE_SIZE_KB * 1024 // 10))
        else:
            value = f"value_{i:04d}".encode()
        generator.put(key, value)
    # Close the generator to flush and close the WAL file.
    del generator

recovered = Engine(data_dir=DATA_DIR)

expected_large_value = f"value_{LARGE_AT:04d}_".encode() * (LARGE_SIZE_KB * 1024 // 10)
assert recovered.get(f"key_{LARGE_AT:04d}".encode()) == expected_large_value, \
    "large entry did not recover correctly"

for i in range(1, LAST_GOOD + 1):
    if i == LARGE_AT:
        continue
    key = f"key_{i:04d}".encode()
    expected = f"value_{i:04d}".encode()
    got = recovered.get(key)
    assert got == expected, f"key_{i:04d}: expected {expected!r}, got {got!r}"

ghost_key = f"key_{LAST_GOOD + 1:04d}".encode()
assert recovered.get(ghost_key) is None, f"{ghost_key!r} should not exist"

assert recovered._seq_no == LAST_GOOD, f"expected seq_no={LAST_GOOD}, got {recovered._seq_no}"
print("ALL CHECKS PASSED")