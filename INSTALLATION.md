# Stratum DB User Documentation

Stratum DB is a write-optimized, crash-safe Python LSM-tree key-value engine.
It stores data in a write-ahead log (WAL) and immutable SSTable files, and
supports an optional gRPC server and optional PostgreSQL metadata integration.

## Requirements

- Python 3.12 or newer, as declared by the package metadata.
- Persistent filesystem storage for any data directory used outside a test.

The core library requires only `sortedcontainers`. Server, metadata, and test
features are optional extras.

## Install from PyPI

If a published PyPI release is available, install the core library with:

```bash
python -m pip install stratum-db
```

Install optional capabilities as needed:

```bash
python -m pip install "stratum-db[server]"
python -m pip install "stratum-db[metadata]"
python -m pip install "stratum-db[server,metadata]"
python -m pip install "stratum-db[dev]"
```

The `server` extra provides gRPC, protobuf tooling, `.env` loading, the
`stratum/grpc/` package, and the `stratum-server` entry point. The `metadata`
extra provides SQLAlchemy and the PostgreSQL driver. The `dev` extra provides
pytest and Hypothesis. The wheel is limited to the `stratum*` packages and
does not include the repository's `ui/` directory.

## Install directly from GitHub

Install the default branch directly from GitHub:

```bash
python -m pip install "git+https://github.com/VishnuP2412/stratum-db.git"
```

GitHub extras use the same syntax:

```bash
python -m pip install \
  "stratum-db[server] @ git+https://github.com/VishnuP2412/stratum-db.git"
```

To install a tagged release or commit, append the Git ref:

```bash
python -m pip install \
  "stratum-db @ git+https://github.com/VishnuP2412/stratum-db.git@v0.1.0"
```

If the project has not been published to PyPI, use the GitHub form or install
from a local clone.

## Install from a local clone

```bash
git clone https://github.com/VishnuP2412/stratum-db.git
cd stratum-db
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

For development and tests:

```bash
python -m pip install -e ".[server,dev]"
```

On Windows PowerShell, activate the virtual environment with
`.venv\Scripts\Activate.ps1`.

## Use the embedded engine

```python
from pathlib import Path
from stratum.engine import Engine

engine = Engine(Path("./data"))
engine.put(b"user:1", b"Alice")

value = engine.get(b"user:1")
print(value)  # b"Alice"

engine.delete(b"user:1")
print(engine.get(b"user:1"))  # None
```

Keys and values must be `bytes`; the API rejects strings and other types rather
than silently converting them. `Engine.scan(start_key, end_key)` uses inclusive
byte bounds. `Engine.compact()` is manual and permanently removes keys whose
latest record is a tombstone.

## Run the gRPC server

Install the server extra and start the packaged entry point:

```bash
python -m pip install ".[server]"
stratum-server
```

Useful configuration:

```bash
export STRATUM_DATA_DIR=./data
export STRATUM_PORT=50051
export STRATUM_LOG_LEVEL=INFO
# Optional:
export STRATUM_TABLE_DIR=./tables
export STRATUM_METRICS_PORT=8000
```

The server provides `Get`, `Put`, and streaming `Scan`. It does not provide a
gRPC `Delete` method in v0.1.0. The default transport is insecure and has no
authentication or TLS, so use it only on a trusted network or behind a
properly secured proxy.

## Optional PostgreSQL metadata

Install the metadata extra and enable it explicitly:

```bash
python -m pip install "stratum-db[metadata]"
export STRATUM_METADATA_ENABLED=true
python -m stratum.init_db
```

Metadata is disabled by default. PostgreSQL does not replace the WAL or
SSTable files; preserve the configured filesystem directories as well. The
`stratum/db.py` is not a source of credentials. Metadata requires
`DATABASE_URL` when enabled; provide it through a secret-managed environment
variable. There is no default database password or connection string.

## Configuration reference

| Variable | Default | Description |
| --- | --- | --- |
| `STRATUM_DATA_DIR` | `./data` | WAL and primary data directory |
| `STRATUM_TABLE_DIR` | unset | Separate SSTable directory; defaults to the data directory |
| `STRATUM_PORT` | `50051` | gRPC server port |
| `STRATUM_LOG_LEVEL` | `INFO` | Logging level |
| `STRATUM_METRICS_PORT` | unset | Enables the HTTP `/metrics` endpoint when set |
| `STRATUM_METADATA_ENABLED` | `false` | Enables PostgreSQL metadata writes |

The server loads a `.env` file when `python-dotenv` is installed. Explicit
process environment variables take precedence.

## Project layout and further documentation

- `stratum/engine.py` — core storage engine.
- `stratum/wal.py` — CRC-checked write-ahead log.
- `stratum/sstable.py` — immutable SSTables, indexes, and Bloom filters.
- `stratum/grpc/` — protobuf definitions and gRPC implementation.
- `tests/` — unit, crash-safety, gRPC, and property-based tests.
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — deployment types and operations.
- [`docs/WAL_FORMAT.md`](docs/WAL_FORMAT.md) — WAL binary format.
- [`docs/SSTABLE_FORMAT.md`](docs/SSTABLE_FORMAT.md) — SSTable binary format.
- [`docs/COMPACTION.md`](docs/COMPACTION.md) — compaction behavior and recovery.
- [`STRATUM_PROJECT.md`](STRATUM_PROJECT.md) — design rationale and known
  limitations.

## Verify an installation

From a clone with the development extra installed:

```bash
python -m pytest
```

The default test configuration excludes tests marked `slow`. Run the server
only after confirming that the configured data directory is writable and
persistent.
