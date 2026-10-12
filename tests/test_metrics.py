from pathlib import Path
from urllib.request import urlopen

from stratum.engine import Engine
from stratum.metrics import start_metrics_server


def test_engine_metrics_render_current_operations(tmp_path):
    engine = Engine(Path(tmp_path))
    engine.put(b"key", b"value")
    assert engine.get(b"key") == b"value"

    output = engine.metrics.render().decode()

    assert "stratum_puts_total 1" in output
    assert "stratum_gets_total 1" in output
    assert "stratum_sstables 0" in output
    assert "stratum_memtable_entries 1" in output


def test_metrics_endpoint_returns_prometheus_text(tmp_path):
    engine = Engine(Path(tmp_path))
    engine.put(b"key", b"value")
    server = start_metrics_server(engine.metrics, 0)
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/metrics") as response:
            body = response.read().decode()
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/plain")
            assert "stratum_puts_total 1" in body
    finally:
        server.shutdown()
        server.server_close()
