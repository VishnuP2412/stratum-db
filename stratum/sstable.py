from __future__ import annotations
from pathlib import Path
import struct
import os
import bisect
import hashlib
import math

class SSTable:
    def __init__(self, sst_path = None, idx_path = None, min_key = None, max_key = None,indexes = None, index_start = None, bloom_filter = None, file_size_bytes = None, entry_count = None):
        if not isinstance(sst_path, Path):
            raise TypeError(
                f"SSTable requires a pathlib.Path, got {type(sst_path).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
        if not isinstance(idx_path, Path):
            raise TypeError(
                f".IDX requires a pathlib.Path, got {type(idx_path).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
        self.sst_path = sst_path
        self.idx_path = idx_path
        self.min_key = min_key
        self.max_key = max_key
        self.indexes = indexes if indexes else []
        self.index_start = index_start
        self.bloom_filter = bloom_filter
        self.file_size_bytes = file_size_bytes
        self.entry_count = entry_count

    @classmethod
    def flush(cls, path, tableCount, memtable_items) -> SSTable:
        if not isinstance(path, Path):
            raise TypeError(
                f"SSTable requires a pathlib.Path, got {type(path).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
        path.mkdir(parents=True, exist_ok=True)
        #sst_path = path / f"{tableCount:06d}_{uuid.uuid4().hex}.sst"
        sst_path = path / f"{tableCount:06d}.sst"
        tmp_sst_path = sst_path.with_name(sst_path.name + ".tmp")
        idx_path = path / f"{tableCount:06d}.idx"
        tmp_idx_path = idx_path.with_name(idx_path.name + ".tmp")

        memtable_items = list(memtable_items)
        number_of_entries = len(memtable_items)
        filter = BloomFilter.for_size(number_of_entries, 0.01)
        min_key = None
        max_key = None
        count = 0
        indexes = []
        pos = None
        with open(tmp_sst_path, 'wb') as file:
            for key, (value, seq_no, deleted) in memtable_items:
                if count % 1000 == 0:
                    indexes.append((key, file.tell()))
                count += 1
                if min_key is None:
                    min_key = key
                max_key = key
                header = struct.pack(">IIQB", len(key), len(value), seq_no, deleted)
                file.write(header + key + value)
                filter.add(key)

            pos = file.tell()
            with open(tmp_idx_path, 'wb') as idxWrite:
                idxWrite.write(struct.pack('>I',pos))
                idxWrite.flush()
                os.fsync(idxWrite.fileno())
            os.replace(tmp_idx_path, idx_path)

            if count > 0:
                file.write(struct.pack('>I', filter.bits_number))
                file.write(struct.pack('>I', filter.hashes_number))
                file.write(struct.pack('>I', filter.filter_length))
                file.write(filter.filter)
                for k, idx in indexes:
                    file.write(struct.pack('>I',len(k)))
                    file.write(k)
                    file.write(struct.pack('>I',idx))
                file.flush()
                os.fsync(file.fileno())

        os.replace(tmp_sst_path, sst_path)
        file_size_bytes = os.path.getsize(sst_path)
        return SSTable(sst_path=sst_path, idx_path = idx_path, min_key=min_key, max_key=max_key,indexes=indexes, index_start=pos, bloom_filter=filter, file_size_bytes=file_size_bytes, entry_count = count)

    @classmethod
    def from_file(cls, sst_path, idx_path) -> SSTable:
        if not isinstance(sst_path, Path):
            raise TypeError(
                f"SSTable requires a pathlib.Path, got {type(sst_path).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
        if not isinstance(idx_path, Path):
            raise TypeError(
                f"IDX sidecar requires a pathlib.Path, got {type(idx_path).__name__}. "
                f"Wrap it with Path(...) at the call site."
            )
            
        min_key = None
        max_key = None
        indexes = []
        file_size_bytes = os.path.getsize(sst_path)
        with open(idx_path,'rb') as file:
            index_start = struct.unpack('>I',file.read())[0]

        with open(sst_path, 'rb') as file:
            if index_start == 0 and file.read(1) == b"":
                filter = BloomFilter.for_size(0, 0.02)
            else:
                file.seek(index_start, 0)
                size = struct.calcsize(">I")
                bytesNumber = struct.unpack('>I', file.read(4))[0]
                hashesNumber = struct.unpack('>I', file.read(4))[0]
                filterLen = struct.unpack('>I', file.read(4))[0]
                filterArray = file.read(filterLen)

                filter = BloomFilter.restore_filter(bytesNumber, hashesNumber,filterArray)
                while True:
                    entrySize = file.read(size)
                    if entrySize == b"":       # clean EOF
                        break

                    if len(entrySize) < size:
                        raise ValueError("Truncated Index Table. Unable to read key size")

                    entrySize = struct.unpack('>I',entrySize)[0]
                    key = file.read(entrySize)

                    if len(key) < entrySize:
                        raise ValueError("Truncated Index Table. Unable to read key")
                    idx = file.read(size)

                    if len(idx) < size:
                        raise ValueError("Truncated Index Table. Unable to read index")

                    indexes.append((key, struct.unpack('>I',idx)[0]))

            file.seek(0, 0)
            count = 0
            for (key, value, seq_no, deleted) in SSTable.read_entries(file, index_start):
                if min_key is None:
                    min_key = key
                max_key = key
                count += 1
        return SSTable(sst_path=sst_path, idx_path = idx_path, min_key=min_key, max_key=max_key,indexes=indexes, index_start=index_start,bloom_filter=filter, file_size_bytes=file_size_bytes, entry_count=count)


    def might_contain(self, key):
        return self.bloom_filter.might_contain(key)

    def search(self, target):
        offset_index = bisect.bisect_right(self.indexes,target, key=lambda x:x[0]) - 1
        offset = self.indexes[offset_index][1] if offset_index != -1 else 0
        return self.scan(target, target, offset)


    def scan(self, start_key, end_key, offset = None) -> list:
        if not isinstance(start_key, bytes):
            raise TypeError(f"SSTable.scan requires bytes start_key, got {type(start_key).__name__}")

        if not isinstance(end_key, bytes):
            raise TypeError(f"SSTable.scan requires bytes end_key, got {type(end_key).__name__}")

        if not isinstance(self.idx_path, Path):
                    raise TypeError(
                        f"IDX sidecar requires a pathlib.Path, got {type(self.idx_path).__name__}. "
                        f"Wrap it with Path(...) at the call site."
                    )

        if self.index_start is None:
            with open(self.idx_path,'rb') as file:
                self.index_start = struct.unpack('>I',file.read())[0]

        with open(self.sst_path, 'rb') as file:
            if offset is not None:
                file.seek(offset, 0)
            results = []
            for (key, value, seq_no, deleted) in SSTable.read_entries(file,self.index_start):
                if start_key <= key <= end_key:
                    results.append((key, value, seq_no, deleted))
                elif key > end_key:
                    break
        return results
    
    @staticmethod
    def read_entries(file, index_offset = None):
        seen_keys = set()
        while True:
            if index_offset is not None and file.tell() >= index_offset:
                return
            
            header = file.read(17)
            if not header:
                return
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
            
            yield (key, value, seq_no, deleted)

class BloomFilter:
    def __init__(self, number_of_bits, number_of_hashes, filterData = None):
        self.bits_number = number_of_bits
        self.filter = filterData if filterData is not None else bytearray(number_of_bits)
        self.hashes_number = number_of_hashes
        self.filter_length = len(self.filter)

    
    def _indices(self, key:bytes):
        h1_raw = int(hashlib.md5(key).hexdigest(),16)
        h2_raw = int(hashlib.sha1(key).hexdigest(),16)
        h1 = h1_raw % self.filter_length
        h2 = h2_raw % self.filter_length
        for i in range(0,self.hashes_number):
            yield (h1 + i * h2) % self.filter_length

    def add(self, key:bytes):
        for idx in self._indices(key):
            self.filter[idx] = 1

    def might_contain(self, key:bytes):
        for idx in self._indices(key):
            if self.filter[idx] != 1:
                return False
        return True

    @classmethod
    def restore_filter(cls, m, k, array):
        if not isinstance(array, bytearray):
            array = bytearray(array)
        return BloomFilter(number_of_bits=m,number_of_hashes=k,filterData=array)

    @classmethod
    def for_size(cls, n, target_fpr = 0.01):
        if n <= 0:
            return BloomFilter(number_of_bits=1, number_of_hashes=1)

        bits_number = max(1, math.ceil(-(n * math.log(target_fpr)) / (math.log(2) ** 2)))
        hashes_number = max(1, math.ceil((bits_number / n) * math.log(2)))

        return BloomFilter(number_of_bits=bits_number, number_of_hashes=hashes_number)