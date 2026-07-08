from stratum.memtable import MemTable
from stratum.wal import WAL
from threading import RLock
from pathlib import Path

class Engine:
    def __init__(self, data_dir):
        if not isinstance(data_dir, Path):
            raise TypeError(
                f"WAL requires a pathlib.Path, got {type(data_dir).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )

        self.memtable = MemTable()
        self.wal = WAL(data_dir)
        self._seq_no = 0
        self.lock =RLock()

        self._recover()

    def _recover(self):
        for seq_no,op_type,key,value in self.wal.replay():
            self._seq_no = seq_no
            if op_type == 1:
                self.memtable.put(key,value,self._seq_no)
            else:
                self.memtable.delete(key,self._seq_no)

    def put(self, key, value):
        with self.lock:
            self._seq_no += 1
            self.wal.append(self._seq_no, 1, key, value)
            self.memtable.put(key,value,self._seq_no)


    def delete(self, key):
        with self.lock:
            self._seq_no += 1
            self.wal.append(self._seq_no, 2, key, b"")
            self.memtable.delete(key,self._seq_no)

    def get(self, key):
        with self.lock:
            return self.memtable.get(key)