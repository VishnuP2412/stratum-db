import os
import random
import struct
import zlib
from stratum.engine import Engine
from stratum.wal import WAL


def test_basic_recovery(tmp_path):
    path = tmp_path /"test_data.wal" 
    engine1 = Engine(tmp_path)
    engine1.put(b'key1', b'value1')
    engine1.put(b'key2', b'value2')
    engine1.put(b'key3', b'value3')
    del engine1
    engine2 = Engine(tmp_path)
    assert engine2.get(b'key1') == b'value1'
    assert engine2.get(b'key2') == b'value2'
    assert engine2.get(b'key3') == b'value3'
    del engine2

def test_delete_survive_recovery(tmp_path):
    
    engine1 = Engine(tmp_path)
    engine1.put(b'key1', b'value1')
    engine1.delete(b'key1')
    del engine1
    engine2 = Engine(tmp_path)
    assert engine2.get(b'key1') == None
    del engine2

def test_overwrite_survives_recovery(tmp_path):
     
    engine1 = Engine(tmp_path)
    engine1.put(b'key1', b'value1')
    engine1.put(b'key1', b'value2')
    del engine1
    engine2 = Engine(tmp_path)
    assert engine2.get(b'key1') == b'value2'
    del engine2

def test_seq_no_continuity(tmp_path):
    
    engine1 = Engine(tmp_path)
    engine1.put(b'key1', b'value1')
    engine1.put(b'key2', b'value2')
    engine1.put(b'key3', b'value3')
    del engine1
    engine2 = Engine(tmp_path)
    engine2.put(b'key4',b'value4')
    del engine2
    seq_nos = list(WAL(tmp_path).replay())
    assert len(seq_nos) == 4
    assert seq_nos[2][0] < seq_nos[3][0]


def test_empty_directory(tmp_path):
    
    engine1 = Engine(tmp_path)
    assert engine1.get(b'key1') == None
    del engine1