from sortedcontainers import SortedDict
from threading import RLock

class MemTable:
    def __init__(self, max_size_bytes=4 * 1024 * 1024):
        self.table = SortedDict()
        self.lock = RLock()
        self._set_bytes = 0
        self.max_size_bytes = max_size_bytes

    def put(self, key, value, seq_no, deleted=False):
        with self.lock:
            old_record = self.table.get(key)
            if old_record is not None:
                old_value, _, _ = old_record
                self._set_bytes -= len(key) + len(old_value) + 8 + 1

            data = (value, seq_no, deleted)
            self.table[key] = data
            self._set_bytes += len(key) + len(value) + 8 + 1

    def delete(self, key, seq_no):
        with self.lock:
            self.put(key, b"", seq_no, deleted=True)

    def get(self, key):
        with self.lock:
            record = self.table.get(key)
            if record is None:
                return None
            value, seq_no, deleted = record
            if deleted:
                return None
            return value

    def is_full(self):
        with self.lock:
            return self._set_bytes >= self.max_size_bytes
    
    @property
    def size(self):
        with self.lock:
            return self._set_bytes
    
    def items(self):
        with self.lock:
            return list(self.table.items())