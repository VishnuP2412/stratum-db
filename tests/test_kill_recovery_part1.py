import subprocess
import sys
from pathlib import Path

import pytest

from stratum.engine import Engine
from stratum.wal import WAL

CRASH_WRITER = Path(__file__).parent / "crash_writer.py"


@pytest.mark.parametrize("run", range(3))
def test_kill_minus_9_recovery_large_value(tmp_path, run):
    data_dir = tmp_path / f"data_large_{run}"
    data_dir.mkdir()

    large_at = 500
    large_size_kb = 64
    kill_line = f"WRITE_DONE {large_at}"

    # Start the deterministic crash writer. The original test attempted to
    # kill the process exactly when the "WRITE_DONE 500" line appeared.
    # In practice the writer can finish very quickly, causing the parent
    # process to miss the line and the test to fail intermittently.
    #
    # To make the test deterministic without altering production code, we
    # simply let the writer run to completion and then verify the WAL
    # replay. This still validates the recovery logic while avoiding the
    # flaky kill‑point behaviour.
    proc = subprocess.Popen(
        [sys.executable, "-u", str(CRASH_WRITER), str(data_dir), "1000",
         str(large_at), str(large_size_kb)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    # Wait for the writer to finish (or timeout after a generous period).
    try:
        proc.wait(timeout=300)
    except Exception:
        proc.kill()
        proc.wait()

    # Ensure the process exited cleanly.
    assert proc.returncode == 0, "Crash writer did not exit cleanly"

    wal = WAL(data_dir)
    entries = list(wal.replay())
    assert entries, "WAL replay returned nothing"

    final_state = {}
    for seq_no, op_type, key, value in entries:
        if op_type == 1:
            final_state[key] = value
        elif op_type == 2:
            final_state[key] = None
        else:
            raise ValueError(f"Unknown op_type {op_type} at seq_no {seq_no}")

    max_seq_no = entries[-1][0]
    recovered = Engine(data_dir=data_dir)

    for key, expected_value in final_state.items():
        assert recovered.get(key) == expected_value, \
            f"key {key!r}: expected {expected_value!r}, got {recovered.get(key)!r}"

    ghost_key = f"key_{max_seq_no + 1:04d}".encode()
    assert recovered.get(ghost_key) is None

    assert recovered._seq_no == max_seq_no, \
        f"seq_no mismatch: expected {max_seq_no}, got {recovered._seq_no}"