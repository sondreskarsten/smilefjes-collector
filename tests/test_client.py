from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import client as client_module
from client import SmilefjesClient


class FakeResponse:
    content = b"\xef\xbb\xbfheader\nvalue\n"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def get(self, url, *, timeout):
        return FakeResponse()


class ClientTests(unittest.TestCase):
    def test_fetch_preserves_the_exact_publisher_bytes(self):
        client = SmilefjesClient()
        client._session = FakeSession()

        body = client.fetch("tilsyn")

        self.assertEqual(body, b"\xef\xbb\xbfheader\nvalue\n")

    def test_fetch_retries_transient_http_failures(self):
        class Handler(BaseHTTPRequestHandler):
            attempts = 0

            def do_GET(self):
                Handler.attempts += 1
                if Handler.attempts < 3:
                    self.send_response(503)
                    self.end_headers()
                    return
                body = b"header\nvalue\n"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        with patch.object(client_module, "BASE", base):
            try:
                body = SmilefjesClient(timeout=2).fetch("tilsyn")
            except Exception as exc:
                self.fail(f"transient failures were not retried: {exc}")

        self.assertEqual(body, b"header\nvalue\n")
        self.assertEqual(Handler.attempts, 3)


if __name__ == "__main__":
    unittest.main()
