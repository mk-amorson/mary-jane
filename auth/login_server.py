"""Localhost HTTP server for Telegram Login Widget callback."""

import asyncio
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)


def _find_free_port(start=37100, end=37110) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port in range 37100-37110")


class LoginCallbackServer:
    """Start a temporary localhost server to receive Telegram auth callback."""

    def __init__(self):
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None
        self._result: dict | None = None
        self._event = threading.Event()
        self.port: int | None = None

    def start(self) -> int:
        self.port = _find_free_port()
        self._result = None

        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return

                params = parse_qs(parsed.query)
                # Flatten single-value params
                parent._result = {k: v[0] for k, v in params.items()}

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = (
                    "<html><body style='background:#1c1c20;color:#c8c8c8;"
                    "font-family:sans-serif;display:flex;justify-content:center;"
                    "align-items:center;height:100vh;margin:0'>"
                    "<h1>Авторизация успешна! Закройте вкладку.</h1>"
                    "</body></html>"
                )
                self.wfile.write(html.encode())

                # Signal that we got the callback
                parent._event.set()

            def log_message(self, format, *args):
                pass  # suppress HTTP logs

        self._server = HTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        log.info("Login callback server started on port %d", self.port)
        return self.port

    async def wait_for_callback(self, timeout: float = 120.0) -> dict | None:
        try:
            loop = asyncio.get_running_loop()
            got = await loop.run_in_executor(None, self._event.wait, timeout)
            if got:
                return self._result
            log.warning("Login callback timed out")
            return None
        finally:
            self.stop()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        log.info("Login callback server stopped")
