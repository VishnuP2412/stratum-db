import re
import uuid
from stratum.memtable import MemTable
from stratum.wal import WAL
from stratum.sstable import SSTable
from threading import RLock
from pathlib import Path

class Engine:
    def __init__(self, data_dir, table_dir=None):
        if not isinstance(data_dir, Path):
            raise TypeError(
                f"WAL requires a pathlib.Path, got {type(data_dir).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
        if table_dir is None:
            table_dir = data_dir
        if not isinstance(table_dir, Path):
            raise TypeError(
                f"SSTable requires a pathlib.Path, got {type(table_dir).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )

        self.data_dir = data_dir
        self.table_dir = table_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.table_dir.mkdir(parents=True, exist_ok=True)

        self.memtable = MemTable()
        self.wal = WAL(self.data_dir)
        self._seq_no = 0
        self.lock = RLock()
        self.sstables = []
        self.tableCount = 0

        self._load_sstables()
        self._recover()

    def _load_sstables(self):
        for path in sorted(self.table_dir.glob("*.sst")):
            self.sstables.append(SSTable.from_file(path))
            match = re.match(r"^(\d+)_", path.name)
            if match:
                self.tableCount = max(self.tableCount, int(match.group(1)) + 1)

    def _recover(self):
        for seq_no, op_type, key, value in self.wal.replay():
            self._seq_no = seq_no
            if op_type == 1:
                self.memtable.put(key, value, self._seq_no)
            else:
                self.memtable.delete(key, self._seq_no)

    def put(self, key, value):
        with self.lock:
            if self.memtable.is_full():
                self.write_table()
            self._seq_no += 1
            self.wal.append(self._seq_no, 1, key, value)
            self.memtable.put(key, value, self._seq_no)


    def write_table(self):
        data = self.memtable.items()
        path = self.table_dir / f"{self.tableCount:06d}_{uuid.uuid4().hex}.sst"
        self.tableCount += 1
        new_sstable = SSTable.flush(path, data)
        self.sstables.append(new_sstable)
        self.wal.truncate()
        self.memtable = MemTable()

    def delete(self, key):
        with self.lock:
            self._seq_no += 1
            self.wal.append(self._seq_no, 2, key, b"")
            self.memtable.delete(key,self._seq_no)

    def get(self, key):
        with self.lock:
            record = self.memtable.get_record(key)
            if record is not None:
                value, _, deleted = record
                return None if deleted else value

            for sstable in reversed(self.sstables):
                if sstable.min_key is not None and not (sstable.min_key <= key <= sstable.max_key):
                    continue
                results = sstable.scan(key, key)
                if results:
                    _, value, _, deleted = results[0]
                    return None if deleted else value

            return None