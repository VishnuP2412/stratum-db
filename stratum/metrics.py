from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread


class MetricsRegistry:
    def __init__(self):
        self._lock = Lock()
        self._counters = {}
        self._gauges = {}

    def increment(self, name, value=1):
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def set_gauge(self, name, value):
        with self._lock:
            self._gauges[name] = value

    def render(self):
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)

        lines = []
        for name, value in sorted(counters.items()):
            lines.append(f"# TYPE stratum_{name} counter")
            lines.append(f"stratum_{name} {value}")
        for name, value in sorted(gauges.items()):
            lines.append(f"# TYPE stratum_{name} gauge")
            lines.append(f"stratum_{name} {value}")
        return ("\n".join(lines) + "\n").encode("utf-8")


def start_metrics_server(registry, port):
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_error(404)
                return

            body = registry.render()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            return

    server = ThreadingHTTPServer(("", port), MetricsHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
