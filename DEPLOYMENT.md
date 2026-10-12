# Stratum DB Deployment Guide

This document describes the supported ways to deploy Stratum DB. Choose the
smallest deployment that matches how the application will use the database.

## Deployment types

### 1. Embedded library deployment

Use Stratum DB as an in-process Python library when the application and storage
engine run in the same process.

```python
from pathlib import Path
from stratum.engine import Engine

engine = Engine(Path("/var/lib/stratum-db/data"))
engine.put(b"user:1", b"Alice")
```

This is the simplest deployment. The application owns the process lifecycle
and the `data_dir` must be on persistent storage. If `table_dir` is omitted,
SSTables are stored in the same directory as the WAL.

Recommended for:

- local applications and development tools;
- one application process with local disk;
- tests and single-node services.

### 2. Standalone gRPC deployment

Use the packaged `stratum-server` command when multiple processes or
applications need to access one Stratum DB instance over the network.

Install the server extra and start the service:

```bash
pip install "stratum-db[server]"
stratum-server
```

The default gRPC listener is `0.0.0.0:50051`. The service exposes `Get`, `Put`,
and streaming `Scan`. Configure it with environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `STRATUM_DATA_DIR` | `./data` | Directory containing the WAL and runtime data |
| `STRATUM_TABLE_DIR` | unset | Optional separate directory for SSTables |
| `STRATUM_PORT` | `50051` | gRPC port |
| `STRATUM_LOG_LEVEL` | `INFO` | Python logging level |
| `STRATUM_METRICS_PORT` | unset | Optional HTTP port for `/metrics` |
| `STRATUM_METADATA_ENABLED` | `false` | Enables optional PostgreSQL metadata writes |

For a persistent deployment, mount durable storage at the data and table
directories and restart the service with the same paths. The gRPC server in
this release is intentionally insecure: it does not provide TLS or
authentication. Put it behind a trusted private network or an authenticated
proxy until those capabilities are added.

### 3. Experimental: gRPC deployment with PostgreSQL metadata

Enable this mode when operators need PostgreSQL records describing SSTable
flushes and compaction jobs in addition to Stratum's filesystem data.

Install the server and metadata extras:

```bash
pip install "stratum-db[server,metadata]"
export STRATUM_METADATA_ENABLED=true
stratum-server
```

The PostgreSQL database is metadata only; the WAL and SSTable files remain the
source of truth and still require persistent storage. Initialize the metadata
schema using the project's database initialization module before starting the
service:

```bash
python -m stratum.init_db
```

This mode is experimental. Set `DATABASE_URL` through your platform's
secret-management facility before enabling metadata. The application has no
database URL default and fails clearly if `DATABASE_URL` is missing. Never
commit database credentials to source control.

Do not enable this mode unless PostgreSQL is reachable and the metadata
dependencies are installed. The optional development Compose file
(`docker-compose.dev.yml`) can provide local PostgreSQL for development; it is
not a production deployment definition.

## Operational requirements

- Use persistent, local filesystem storage for `STRATUM_DATA_DIR` and
  `STRATUM_TABLE_DIR`; do not place them on ephemeral container storage.
- Run one writer process for a given data directory. Stratum DB v0.1.0 is not a
  clustered or multi-writer database.
- Back up the WAL and all `.sst`/`.idx` files together. Restoring only one part
  can produce an incomplete database state.
- Call `Engine.compact()` from a controlled maintenance process when obsolete
  SSTables should be removed. Compaction is manual and is not automatically
  triggered by file count or size.
- Set `STRATUM_METRICS_PORT` only when monitoring is needed. The metrics
  endpoint is plain HTTP and should be bound to a trusted network.
- Test recovery and restore procedures before production use.

## Container and process-manager patterns

Stratum DB can run in a Python container or under a process manager such as
systemd. Regardless of the wrapper:

1. install the required package extras;
2. provide the `STRATUM_*` variables through the environment or a `.env` file;
3. mount persistent storage for database files;
4. expose the gRPC port only to trusted clients;
5. use a supervisor to restart the process after failure;
6. monitor logs, disk usage, and optional `/metrics` counters.

There is no production Docker image or orchestration manifest in this
repository. Deployment teams should supply those artifacts according to their
platform's secret, storage, networking, and health-check conventions.
