from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Table, LargeBinary
from sqlalchemy.orm import relationship
from stratum.db import Base

association_table = Table(
    "association_table",
    Base.metadata,
    Column('sstable_meta_data_id', Integer, ForeignKey('sstable_meta.id'), primary_key=True),
    Column('compaction_job_id', Integer, ForeignKey('compaction_job.id'), primary_key=True)
)

class SSTableMeta(Base):
    __tablename__ = "sstable_meta"
    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable = False)
    min_key = Column(LargeBinary, nullable = False)
    max_key = Column(LargeBinary, nullable = False)
    entry_count = Column(Integer, nullable = False)
    file_size_bytes = Column(Integer, nullable = False)
    created_at = Column(DateTime, nullable = False)
    is_active = Column(Boolean, nullable = False, server_default='true')

class CompactionJob(Base):
    __tablename__ = "compaction_job"
    id = Column(Integer, primary_key = True)
    status = Column(String, nullable = False)
    started_at = Column(DateTime, nullable = False)
    completed_at = Column(DateTime,nullable=True)
    tombstones_dropped = Column(Integer, server_default = '0', nullable = False)
    output_sstable_id = Column(Integer, ForeignKey('sstable_meta.id'), nullable = True)
    output_sstable = relationship('SSTableMeta')
    input_sstables = relationship('SSTableMeta', secondary = association_table)