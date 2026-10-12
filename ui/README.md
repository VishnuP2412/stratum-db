# Optional local UI

The UI is an offline vanilla-JavaScript page served by a small FastAPI gateway. It embeds `stratum.engine.Engine` directly and is disabled unless started explicitly.

## Setup and run

From the repository root, install the UI dependencies into the environment that already has Stratum DB:

```bash
python -m pip install -r ui/requirements.txt
python -m uvicorn ui.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. `STRATUM_UI_HOST` and `STRATUM_UI_PORT` configure the bind address and port. `STRATUM_UI_DATA_DIR` selects the data directory and defaults to `./ui_data`.

The gateway is the single writer for its data directory. Never run it alongside `stratum-server` against the same directory. It binds to localhost by default, has no authentication, and has no CORS configuration. Keep `STRATUM_METADATA_ENABLED` unset or false.

Values are limited to 1 MiB and scan limits to 1,000 rows (default 100). Scan bounds are both required and inclusive. The engine has no public flush method, so the UI exposes compaction but not a flush endpoint. Compaction permanently removes tombstoned keys.
