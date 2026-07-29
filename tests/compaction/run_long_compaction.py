import os, sys, time
from pathlib import Path
from stratum.engine import Engine

# ----------------------------------------------------------------------
# Configuration – tweak these numbers if you want a longer/shorter run
# ----------------------------------------------------------------------
NUM_TABLES   = 5_000          # how many *flushes* (i.e. SSTables) we will create
ENTRIES_PER = 200            # rows per flush – total rows ≈ NUM_TABLES * ENTRIES_PER
DATA_DIR    = Path("tmp_long_data")
TABLE_DIR   = Path("tmp_long_tables")

# Clean any previous run
for p in (DATA_DIR, TABLE_DIR):
    if p.exists():
        for child in p.rglob("*"):
            child.unlink(missing_ok=True)
        p.rmdir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
TABLE_DIR.mkdir(parents=True,  exist_ok=True)

engine = Engine(DATA_DIR, TABLE_DIR)

print(f"🗂️  Data dir : {DATA_DIR.resolve()}")
print(f"📁  Table dir: {TABLE_DIR.resolve()}")
print(f"🔨  Generating {NUM_TABLES:,} SSTable files …")

# ----------------------------------------------------------------------
# 1️⃣ Write a huge number of tiny tables (flush after each batch)
# ----------------------------------------------------------------------
for tbl in range(NUM_TABLES):
    base = tbl * ENTRIES_PER
    for i in range(ENTRIES_PER):
        key   = f"k{base + i}".encode()
        value = f"v{base + i}".encode()
        engine.put(key, value)
    # Force a write‑to‑disk (creates one SSTable file)
    engine.write_table()

    # Optional progress indicator (prints every 500 tables)
    if (tbl + 1) % 500 == 0:
        print(f"   …written {tbl + 1:,} tables")

print("✅  Data generation finished.")
print(f"🗂️  Current SSTable count: {len(engine.sstables)}")
print("\n🚀  Starting compaction – this is the window you will kill.")
print("    (The process will stay alive until compaction finishes.)")
print(f"    PID = {os.getpid()}\n")

# ----------------------------------------------------------------------
# 2️⃣ Run the real compaction (this may take several seconds)
# ----------------------------------------------------------------------
start = time.time()
engine.compact()
elapsed = time.time() - start

print("\n✅  Compaction completed.")
print(f"⏱️  Time taken: {elapsed:.2f}s")
print(f"🗂️  Final SSTable count: {len(engine.sstables)}")
print("\n🔎  Quick sanity‑check – read a few keys:")
for k in [b"k0", b"k12345", b"k999999"]:
    val = engine.get(k)
    print(f"   {k!r} → {val!r}")

# Keep the process alive a tiny bit so you can see the final output
time.sleep(1)