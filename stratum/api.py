import os
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

def _get_config():
    data_dir = Path(os.environ.get("STRATUM_DATA_DIR","./data"))

    table_dir_raw = os.environ.get("STRATUM_TABLE_DIR")
    table_dir = Path(table_dir_raw) if table_dir_raw else None

    port_raw = os.environ.get("STRATUM_PORT","50051")

    try:
        port = int(port_raw)
    except ValueError:
        raise ValueError(
            f"STRATUM_PORT must be an integer, got {port_raw!r}"
        )

    log_level_name = os.environ.get("STRATUM_LOG_LEVEL","INFO").upper()
    log_level = getattr(logging, log_level_name)
    if not isinstance(log_level, int):
        raise ValueError(
            f"STRATUM_LOG_LEVEL must be a valid level name, got {log_level_name!r}"
        )

    return data_dir, table_dir, port, log_level

def main():
    data_dir, table_dir, port, log_level = _get_config()
    logging.basicConfig(level=log_level)

    from stratum.grpc.server import serve
    serve(data_dir = data_dir, table_dir=table_dir, port=port)

if __name__ == "__main__":
    main()