#!/usr/bin/env bash

# ----------------------------------------------------------------------
# Helper script to demonstrate a real SIGKILL during compaction.
#
# Prerequisite: the large data set (5 000 SSTable files) must already exist.
# If you have never run ``run_long_compaction.py`` before, run it once to
# generate the files and then stop it before the compaction step (or simply
# let it finish – the files remain on disk).
# ----------------------------------------------------------------------

set -e

# Verify that we have some SSTable files; otherwise abort with a helpful message.
if [ ! -d tmp_long_tables ] || [ -z "$(ls -A tmp_long_tables/*.sst 2>/dev/null)" ]; then
  echo "Error: No existing SSTable files found in tmp_long_tables/."
  echo "Run 'python run_long_compaction.py' once to generate the data, then abort"
  echo "before the compaction step (or let it finish – the files stay)."
  exit 1
fi

echo "Starting compaction in background…"
python compact_only.py &
PID=$!
echo "Compaction PID = $PID"

# Give the compaction a moment to start. Adjust the sleep if your machine is
# unusually fast/slow.
sleep 2

echo "Sending SIGKILL to PID $PID"
kill -9 $PID || true

# Give the OS a brief moment to clean up the dead process.
sleep 1

COUNT=$(ls tmp_long_tables/*.sst 2>/dev/null | wc -l)
echo "SSTable files present after kill: $COUNT"

echo "Running recovery check (verifying every key)…"
python recover_check.py
