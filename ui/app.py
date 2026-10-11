from __future__ import annotations

import binascii
import os
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from stratum.engine import Engine

MAX_VALUE_BYTES = 1024 * 1024
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def _decode_input(value: str, encoding: str, field_name: str) -> bytes:
    if encoding == "utf8":
        return value.encode("utf-8")
    if encoding == "hex":
        try:
            return binascii.unhexlify(value)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail=f"{field_name} is not valid hex")
    raise HTTPException(status_code=400, detail=f"{field_name} encoding must be utf8 or hex")


def _display_bytes(value: bytes) -> dict[str, str]:
    try:
        return {"value": value.decode("utf-8"), "encoding": "utf8"}
    except UnicodeDecodeError:
        return {"value": value.hex(), "encoding": "hex"}


def _require_nonempty(value: bytes, field_name: str) -> None:
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name} must not be empty")


def _limit_value(limit: int) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise HTTPException(status_code=400, detail=f"limit must be between 1 and {MAX_LIMIT}")
    return limit


class PutRequest(BaseModel):
    key: str
    value: str
    encoding: str = "utf8"


class KeyRequest(BaseModel):
    key: str
    encoding: str = "utf8"


def _state(engine: Engine) -> dict[str, Any]:
    wal_path = getattr(engine.wal, "path", None)
    state: dict[str, Any] = {
        "wal_size_bytes": wal_path.stat().st_size if wal_path is not None and wal_path.exists() else 0,
        "memtable_entries": len(engine.memtable.items()),
        "sstables": [],
    }
    for table in engine.sstables:
        state["sstables"].append(
            {
                "filename": table.sst_path.name,
                "entry_count": table.entry_count,
                "min_key": _display_bytes(table.min_key) if table.min_key is not None else None,
                "max_key": _display_bytes(table.max_key) if table.max_key is not None else None,
            }
        )
    return state


def create_app(data_dir: Path | None = None) -> FastAPI:
    configured_dir = data_dir or Path(os.getenv("STRATUM_UI_DATA_DIR", "./ui_data"))
    engine = Engine(configured_dir)
    gateway_lock = RLock()
    app = FastAPI(title="Stratum DB local UI")
    app.state.engine = engine
    app.state.gateway_lock = gateway_lock

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/api/get")
    def get_value(key: str = Query(...), encoding: str = Query("utf8")) -> dict[str, Any]:
        raw_key = _decode_input(key, encoding, "key")
        _require_nonempty(raw_key, "key")
        with gateway_lock:
            value = engine.get(raw_key)
        response: dict[str, Any] = {"found": value is not None, "key": _display_bytes(raw_key)}
        if value is not None:
            response["value"] = _display_bytes(value)
        return response

    @app.put("/api/put")
    def put_value(request: PutRequest) -> dict[str, Any]:
        raw_key = _decode_input(request.key, request.encoding, "key")
        raw_value = _decode_input(request.value, request.encoding, "value")
        _require_nonempty(raw_key, "key")
        if len(raw_value) > MAX_VALUE_BYTES:
            raise HTTPException(status_code=400, detail="value must be at most 1 MiB")
        with gateway_lock:
            engine.put(raw_key, raw_value)
            state = _state(engine)
        return {"ok": True, "key": _display_bytes(raw_key), "state": state}

    @app.post("/api/delete")
    def delete_value(request: KeyRequest) -> dict[str, Any]:
        raw_key = _decode_input(request.key, request.encoding, "key")
        _require_nonempty(raw_key, "key")
        with gateway_lock:
            engine.delete(raw_key)
            state = _state(engine)
        return {"ok": True, "key": _display_bytes(raw_key), "state": state}

    @app.get("/api/scan")
    def scan(
        start: str = Query(...),
        end: str = Query(...),
        start_encoding: str = Query("utf8"),
        end_encoding: str = Query("utf8"),
        limit: int = Query(DEFAULT_LIMIT),
    ) -> dict[str, Any]:
        start_key = _decode_input(start, start_encoding, "start")
        end_key = _decode_input(end, end_encoding, "end")
        _require_nonempty(start_key, "start")
        _require_nonempty(end_key, "end")
        limit = _limit_value(limit)
        with gateway_lock:
            rows = list(engine.scan(start_key, end_key))[:limit]
        return {
            "items": [
                {"key": _display_bytes(key), "value": _display_bytes(value)}
                for key, value in rows
            ],
            "start": _display_bytes(start_key),
            "end": _display_bytes(end_key),
            "limit": limit,
        }

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        with gateway_lock:
            return _state(engine)

    @app.post("/api/compact")
    def compact() -> dict[str, Any]:
        with gateway_lock:
            engine.compact()
            return {"ok": True, "state": _state(engine)}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "ui.app:app",
        host=os.getenv("STRATUM_UI_HOST", "127.0.0.1"),
        port=int(os.getenv("STRATUM_UI_PORT", "8000")),
    )
