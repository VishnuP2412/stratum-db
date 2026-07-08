# NOTE: Real SIGKILL trials (small entries + a 64KB large-value case, multiple
# repetitions, multiple kill points) did not produce a torn/corrupted WAL entry
# in this environment. This suite's proven coverage is: fsync() commit
# boundaries hold under real OS-level process death. Corrupted-tail handling
# (a torn mid-write entry) is covered by synthetic truncation tests in
# test_wal.py, not by this suite. Do not claim "torn-write recovery verified"
# based on this file alone.

import subprocess
import sys
from pathlib import Path

import pytest

from stratum.engine import Engine
from stratum.wal import WAL

CRASH_WRITER = Path(__file__).parent / "crash_writer.py"


# @pytest.mark.parametrize("kill_after", [1, 5, 10, 100])
# @pytest.mark.parametrize("run", range(3))
# def test_kill_minus_9_recovery(tmp_path, kill_after, run):
#     data_dir = tmp_path / f"data_{kill_after}_{run}"
#     data_dir.mkdir()

#     proc = subprocess.Popen(
#         [sys.executable, "-u", str(CRASH_WRITER), str(data_dir), "1000"],
#         stdout=subprocess.PIPE,
#         stderr=subprocess.PIPE,
#         text=True,
#         bufsize=1,
#     )

#     target_line = f"WRITE_DONE {kill_after}"
#     killed = False
#     try:
#         for line in proc.stdout:
#             if line.strip() == target_line:
#                 proc.kill()
#                 killed = True
#                 break
#     finally:
#         proc.wait(timeout=5)

#     assert killed, f"Writer exited before {target_line}"

#     # Ground truth: replay the killed WAL directly, same code path Engine uses.
#     data_dir = Path(__file__).parent / "data_manual_test"
#     wal = WAL(data_dir)
#     entries = list(wal.replay())  # [(seq_no, op_type, key, value), ...]

#     assert entries, "WAL replay returned nothing — writer never got a durable write in"

#     # Reduce to "final state per key" the same way MemTable would end up —
#     # last op per key wins, since replay is in seq_no order.
#     final_state = {}
#     for seq_no, op_type, key, value in entries:
#         if op_type == 1:          # PUT
#             final_state[key] = value
#         elif op_type == 2:        # DELETE
#             final_state[key] = None
#         else:
#             raise ValueError(f"Unknown op_type {op_type} at seq_no {seq_no}")

#     max_seq_no = entries[-1][0]

#     recovered = Engine(data_dir=data_dir)

#     for key, expected_value in final_state.items():
#         assert recovered.get(key) == expected_value, (
#             f"key {key!r}: expected {expected_value!r}, got {recovered.get(key)!r}"
#         )

#     # Nothing beyond what replay() actually found should exist
#     ghost_key = f"key_{max_seq_no + 1:04d}".encode()
#     assert recovered.get(ghost_key) is None, (
#         f"{ghost_key!r} found in recovered engine but was never in the WAL"
#     )

#     # seq_no continuity — the thing you kept skipping
#     assert recovered._seq_no == max_seq_no, (
#         f"seq_no did not continue correctly: expected {max_seq_no}, got {recovered._seq_no}"
#     )


@pytest.mark.parametrize("run", range(3))
def test_kill_minus_9_recovery_large_value(tmp_path, run):
    data_dir = tmp_path / f"data_large_{run}"
    data_dir.mkdir()

    large_at = 500
    large_size_kb = 64
    kill_line = f"WRITE_DONE {large_at}"

    proc = subprocess.Popen(
        [sys.executable, "-u", str(CRASH_WRITER), str(data_dir), "1000",
         str(large_at), str(large_size_kb)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    killed = False
    try:
        for line in proc.stdout:
            if line.strip() == kill_line:
                proc.kill()
                killed = True
                break
    finally:
        proc.wait(timeout=5)

    assert killed, f"Writer exited before {kill_line}"

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

# import struct
# import zlib

# HEADER_FMT = '>QBII'
# HEADER_SIZE = struct.calcsize(HEADER_FMT)

# with open("data_manual_test/wal.log", "rb") as f:
#     data = f.read()

# offset = 0
# last_good_key = None
# while offset < len(data):
#     if offset + HEADER_SIZE > len(data):
#         print(f"Truncated header at offset {offset}")
#         break
#     seq_no, op_type, key_len, val_len = struct.unpack(HEADER_FMT, data[offset:offset+HEADER_SIZE])
#     entry_end = offset + HEADER_SIZE + key_len + val_len + 4  # +4 for CRC
#     if entry_end > len(data):
#         print(f"Truncated entry body at offset {offset}, seq_no={seq_no}")
#         break
#     key = data[offset+HEADER_SIZE : offset+HEADER_SIZE+key_len]
#     val = data[offset+HEADER_SIZE+key_len : offset+HEADER_SIZE+key_len+val_len]
#     stored_crc = struct.unpack('>I', data[entry_end-4:entry_end])[0]
#     computed_crc = zlib.crc32(data[offset:entry_end-4]) & 0xFFFFFFFF
#     if stored_crc != computed_crc:
#         print(f"CRC MISMATCH at seq_no={seq_no}, key={key} — this is where replay() would stop")
#         break
#     last_good_key = key
#     offset = entry_end
#     print("Valid Entry: ", last_good_key, "Offset: ", offset)
# else:
#     print('reached EOF')

# print("Last valid entry:", last_good_key)