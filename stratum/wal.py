import struct
import zlib
import os
from threading import RLock

class WAL:

    def __init__(self, path):
        self.path = path
        self.f = open(path,'ab')
        self.lock = RLock()
        

    def append(self,seq_no, op_type, key, value):
        with self.lock:
            if op_type not in (1,2):
                raise ValueError(f"Invalid op_type: {op_type}")
            header = struct.pack(">QBII",seq_no, op_type,len(key),len(value))
            payload = header + key + value
            crc = zlib.crc32(payload) & 0xFFFFFFFF
            crc_bytes = struct.pack(">I",crc)
            self.f.write(payload+crc_bytes)
            self.f.flush()
            os.fsync(self.f.fileno())

    def replay(self):
        with open(self.path,"rb") as file:
            while True:
                header = file.read(17)
                if not header:
                    break
                if len(header) < 17:
                    break

                seq_no,op_type, key_len, val_len = struct.unpack(">QBII",header)

                body = file.read(key_len + val_len)
                if len(body) < key_len + val_len:
                    break

                key = body[:key_len]
                value = body[key_len:]

                crc_bytes = file.read(4)
                if len(crc_bytes) < 4:
                    break

                stored_crc, = struct.unpack('>I', crc_bytes)
                computed_crc = zlib.crc32(header+body) & 0xFFFFFFFF
                if computed_crc != stored_crc:
                    break

                yield seq_no,op_type, key, value

    def truncate(self):
        with self.lock:
            self.f.close()
            with open(self.path,'wb'):
                pass
            self.f = open(self.path,'ab')