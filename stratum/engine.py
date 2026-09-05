import re
from stratum.memtable import MemTable
from stratum.wal import WAL
from stratum.sstable import SSTable
from threading import RLock
from pathlib import Path
from sortedcontainers import SortedDict
from datetime import datetime, timezone
from stratum.db import record_flush, record_compaction

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
        for sst_path in sorted(self.table_dir.glob("*.sst")):
            idx_path = sst_path.with_suffix('.idx')
            if not idx_path.exists():
                raise FileNotFoundError(f"Could not find {idx_path}")
            self.sstables.append(SSTable.from_file(sst_path, idx_path))
            match = re.match(r"^(\d+)", sst_path.name)
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
        self.tableCount += 1        
        new_sstable = SSTable.flush(self.table_dir, self.tableCount, data)
        created_at = datetime.now(timezone.utc)
        record_flush(
            filename=new_sstable.sst_path.name,
            min_key=new_sstable.min_key,
            max_key=new_sstable.max_key,
            entry_count=new_sstable.entry_count,
            file_size_bytes=new_sstable.file_size_bytes,
            created_at=created_at
            )
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
                if not sstable.might_contain(key):
                    continue
                results = sstable.search(key)
                if results:
                    _, value, _, deleted = results[0]
                    return None if deleted else value

            return None

    def compact(self):
        started_at = datetime.now(timezone.utc)
        entries = SortedDict()
        input_filenames = []
        for table in self.sstables:
            input_filenames.append(table.sst_path.name)
            table_entries = table.scan(table.min_key, table.max_key)
            for key, val, seq_no, deleted in table_entries:
                old = entries.get(key)
                if old is None:
                    entries[key] = (val, seq_no, deleted)
                else:
                    if seq_no > entries[key][1]:
                        entries[key] = (val, seq_no, deleted)
        del_keys = []
        for key, entry in entries.items():
            if entry[2]:
                del_keys.append(key)
        for key in del_keys:
            del entries[key]

        self.tableCount += 1
        created_at = datetime.now(timezone.utc)
        new_table = SSTable.flush(self.table_dir, self.tableCount, entries.items())

        

        if new_table.min_key is None:
            new_table.min_key = b""
            new_table.max_key = b""
        
        old_sst_paths = [t.sst_path for t in self.sstables]
        old_idx_paths = [t.idx_path for t in self.sstables]
        self.sstables = [new_table]
        output_fields = {
            'filename':new_table.sst_path.name,
            'min_key':new_table.min_key,
            'max_key':new_table.max_key,
            'entry_count':new_table.entry_count,
            'file_size_bytes':new_table.file_size_bytes,
            'created_at':created_at
        }
        completed_at = datetime.now(timezone.utc)
        record_compaction(
            status="Completed",
            started_at=started_at,
            completed_at=completed_at,
            tombstones_dropped=len(del_keys),
            input_filenames=input_filenames,
            output_fields=output_fields
            )
        for sst_path, idx_path in zip(old_sst_paths,old_idx_paths):
            try:
                Path(sst_path).unlink()
            except OSError as e:
                print(f"Failed to delete {sst_path}: {e}")
            try:
                Path(idx_path).unlink()
            except OSError as e:
                print(f"Failed to delete {idx_path}: {e}")