from __future__ import annotations
from pathlib import Path
import struct
import os

class SSTable:
    def __init__(self, path, min_key, max_key):
        if not isinstance(path, Path):
            raise TypeError(
                f"SSTable requires a pathlib.Path, got {type(path).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
        self.path = path
        self.min_key = min_key
        self.max_key = max_key

    @classmethod
    def flush(cls, path, memtable_items) -> SSTable:
        if not isinstance(path, Path):
            raise TypeError(
                f"SSTable requires a pathlib.Path, got {type(path).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
        tmp_path = path.with_name(path.name + ".tmp")
        min_key = None
        max_key = None
        with open(tmp_path, 'wb') as file:
            for key, (value, seq_no, deleted) in memtable_items:
                if min_key is None:
                    min_key = key
                max_key = key
                header = struct.pack(">IIQB", len(key), len(value), seq_no, deleted)
                file.write(header + key + value)
            file.flush()
            os.fsync(file.fileno())

        os.replace(tmp_path, path)
        return SSTable(path=path, min_key=min_key, max_key=max_key)

    @classmethod
    def from_file(cls, path) -> SSTable:
        if not isinstance(path, Path):
            raise TypeError(
                f"SSTable requires a pathlib.Path, got {type(path).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
        min_key = None
        max_key = None
        with open(path, 'rb') as file:
            while True:
                header = file.read(17)
                if not header:
                    break
                if len(header) < 17:
                    raise ValueError("Truncated SSTable header")
                key_len, val_len, seq_no, deleted = struct.unpack(">IIQB", header)
                key = file.read(key_len)
                if len(key) < key_len:
                    raise ValueError("Truncated SSTable key body")
                value = file.read(val_len)
                if len(value) < val_len:
                    raise ValueError("Truncated SSTable value body")

                if min_key is None:
                    min_key = key
                max_key = key
        return SSTable(path=path, min_key=min_key, max_key=max_key)

    def scan(self, start_key, end_key) -> list:
        if not isinstance(start_key, bytes):
            raise TypeError(f"SSTable.scan requires bytes start_key, got {type(start_key).__name__}")
        if not isinstance(end_key, bytes):
            raise TypeError(f"SSTable.scan requires bytes end_key, got {type(end_key).__name__}")
        with open(self.path, 'rb') as file:
            results = []
            seen_keys = set()
            while True:
                header = file.read(17)
                if not header:
                    break
                if len(header) < 17:
                    raise ValueError("Truncated SSTable header")
                key_len, val_len, seq_no, deleted = struct.unpack(">IIQB", header)
                key = file.read(key_len)
                if len(key) < key_len:
                    raise ValueError("Truncated SSTable key body")
                value = file.read(val_len)
                if len(value) < val_len:
                    raise ValueError("Truncated SSTable value body")

                if key in seen_keys:
                    raise ValueError(f"Duplicate key {key!r} found in single SSTable file — invariant violated.")
                seen_keys.add(key)

                if start_key <= key <= end_key:
                    if not deleted:
                        results.append((key, value, seq_no))
        return results