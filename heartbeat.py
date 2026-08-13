"""A pulse on the network, and nothing else.

The doorbell on the old phone needs to answer one question: is TARS running?
The obvious way would be to ask his dashboard — but that is deliberately
bound to 127.0.0.1, because it can open the camera, shut him down, and hand
back the school password through /api/setup/reveal. Putting THAT on the
WiFi to save a phone a question would be a terrible trade.

So this exists instead: the smallest possible listener that anyone on the
home network may talk to. It accepts a GET and answers the single word
"TARS". It has no other routes, reads no request body, takes no parameters,
touches no files, and can change nothing. The most an attacker on the WiFi
can learn is that this machine runs TARS — which they could tell from the
hostname anyway.

Everything that can actually do something stays on localhost.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8767


class _Pulse(BaseHTTPRequestHandler):
    def do_GET(self) -> None:          # noqa: N802  (stdlib naming)
        body = b"TARS"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass                            # a poll every 20s must not spam the log


def start() -> None:
    """Called from main(). Never fatal: if the port is taken, TARS carries
    on without a heartbeat and the doorbell simply reports him asleep."""
    def serve() -> None:
        try:
            ThreadingHTTPServer(("0.0.0.0", PORT), _Pulse).serve_forever()
        except OSError:
            pass

    threading.Thread(target=serve, daemon=True).start()
