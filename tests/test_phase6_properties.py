from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings, strategies as st

from stratum.engine import Engine
from stratum.wal import WAL


byte_strings = st.binary(min_size=1, max_size=32)
operations = st.lists(
    st.tuples(
        st.sampled_from(["put", "delete"]),
        byte_strings,
        byte_strings,
    ),
    min_size=1,
    max_size=20,
)


@settings(max_examples=30)
@given(
    records=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=2**63 - 1),
            byte_strings,
            byte_strings,
        ),
        min_size=1,
        max_size=20,
    )
)
def test_wal_replay_preserves_arbitrary_records(records):
    with TemporaryDirectory() as directory:
        wal = WAL(Path(directory))
        try:
            for sequence, key, value in records:
                wal.append(sequence, 1, key, value)
        finally:
            wal.f.close()

        assert list(WAL(Path(directory)).replay()) == [
            (sequence, 1, key, value) for sequence, key, value in records
        ]


@settings(max_examples=40)
@given(
    records=st.lists(
        st.tuples(st.integers(min_value=1, max_value=2**63 - 1), byte_strings, byte_strings),
        min_size=1,
        max_size=20,
    ),
    cut=st.integers(min_value=0, max_value=4096),
)
def test_wal_truncation_recovers_a_valid_prefix(records, cut):
    with TemporaryDirectory() as directory:
        path = Path(directory)
        wal = WAL(path)
        for sequence, key, value in records:
            wal.append(sequence, 1, key, value)
        wal.f.close()

        raw = (path / "wal.log").read_bytes()
        (path / "wal.log").write_bytes(raw[:cut])
        replayed = list(WAL(path).replay())
        assert replayed == [
            (sequence, 1, key, value) for sequence, key, value in records
        ][: len(replayed)]


@settings(max_examples=40)
@given(
    records=st.lists(
        st.tuples(st.integers(min_value=1, max_value=2**63 - 1), byte_strings, byte_strings),
        min_size=1,
        max_size=20,
    ),
    corruption=st.integers(min_value=0, max_value=4096),
)
def test_wal_corruption_recovers_a_valid_prefix(records, corruption):
    with TemporaryDirectory() as directory:
        path = Path(directory)
        wal = WAL(path)
        for sequence, key, value in records:
            wal.append(sequence, 1, key, value)
        wal.f.close()

        raw = bytearray((path / "wal.log").read_bytes())
        raw[corruption % len(raw)] ^= 1
        (path / "wal.log").write_bytes(raw)
        replayed = list(WAL(path).replay())
        assert replayed == [
            (sequence, 1, key, value) for sequence, key, value in records
        ][: len(replayed)]


@settings(max_examples=40)
@given(operations=operations)
def test_compaction_preserves_reads_deletes_scan_and_idempotence(operations):
    with TemporaryDirectory() as directory:
        engine = Engine(Path(directory))
        expected = {}

        for operation, key, value in operations:
            if operation == "put":
                engine.put(key, value)
                expected[key] = value
            else:
                engine.delete(key)
                expected.pop(key, None)
            engine.write_table()

        expected_items = sorted(expected.items())
        assert list(engine.scan(b"\x00", b"\xff" * 32)) == expected_items
        engine.compact()
        after_first = list(engine.scan(b"\x00", b"\xff" * 32))
        engine.compact()
        assert after_first == expected_items
        assert list(engine.scan(b"\x00", b"\xff" * 32)) == after_first

        for key, value in expected.items():
            assert engine.get(key) == value
        for operation, key, _ in operations:
            if operation == "delete" and key not in expected:
                assert engine.get(key) is None
