from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


METADATA_ENABLED = True


class Base(DeclarativeBase):
    pass


def get_db_engine():
    if METADATA_ENABLED:
        db_engine = create_engine("postgresql+psycopg://stratum:stratum@localhost:5432/stratum",echo=True)
        return db_engine
    else:
        return None

def get_session_factory():
    db_engine = get_db_engine()
    if db_engine is not None:
        SessionLocal = sessionmaker(bind=db_engine)
        return SessionLocal
    else:
        return None

def record_flush(filename, min_key, max_key, entry_count, file_size_bytes, created_at):
    session_factory = get_session_factory()
    if session_factory is None:
        return None
    session = session_factory()
    from stratum.models import SSTableMeta
    SSTableMetaEntry = SSTableMeta(
        filename = filename,
        min_key = min_key,
        max_key = max_key,
        entry_count = entry_count,
        file_size_bytes = file_size_bytes,
        created_at = created_at
        )
    try:
        session.add(SSTableMetaEntry)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f'[Metadata] record_flush failed: {e}')
    finally:
        session.close()

def record_compaction(status, started_at, completed_at, tombstones_dropped, input_filenames, output_fields):
    session_factory = get_session_factory()
    if session_factory is None:
        return None
    session = session_factory()
    from stratum.models import SSTableMeta, CompactionJob
    try:
        input_rows = (
            session.query(SSTableMeta)
            .filter(SSTableMeta.filename.in_(input_filenames))
            .all()
        )
        for row in input_rows:
            row.is_active = False

        output_row = SSTableMeta(**output_fields)
        compactionJobEntry = CompactionJob(
                status = status,    
                started_at = started_at,
                completed_at = completed_at,
                tombstones_dropped = tombstones_dropped,
                output_sstable = output_row,
                input_sstables = input_rows,)
        session.add(compactionJobEntry)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f'Metadata Write failed: {e}')
    finally:
        session.close()