"""Mock Instagram Graph API server for offline publishing tests.

Implements the minimal Reels publishing surface:
  GET  /me                          -> account info
  POST /{ig}/media                  -> container creation
  GET  /{container}                 -> status_code / permalink
  POST /{ig}/media_publish          -> publish
  GET  /files/<name>                -> serves the MP4 (what IG would fetch)
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockIG:
    def __init__(self, files_dir):
        self.files_dir = files_dir
        self.fail_publish_remaining = 0
        self.created = 0
        self.publish_calls = 0
        handler = _make_handler(self)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def _make_handler(state: MockIG):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.endswith("/me"):
                self._json({"id": "100", "username": "words.for.being"})
            elif path.startswith("/files/"):
                name = path.split("/files/", 1)[1]
                f = state.files_dir / name
                if f.exists():
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._json({"error": {"message": f"no file {name}"}}, 404)
            else:  # container status / permalink
                self._json({
                    "status_code": "FINISHED",
                    "permalink": "https://www.instagram.com/reel/wfbmock123/",
                    "code": "wfbmock123",
                    "caption": "mock caption",
                })

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            path = self.path.split("?")[0]
            if path.endswith("/media_publish"):
                state.publish_calls += 1
                if state.fail_publish_remaining > 0:
                    state.fail_publish_remaining -= 1
                    self._json({"error": {"message": "simulated publish failure", "code": 500}}, 500)
                else:
                    self._json({"id": "MOCKPUB1"})
            elif path.endswith("/media"):
                state.created += 1
                self._json({"id": f"MOCKMEDIA{state.created}"})
            else:
                self._json({"error": {"message": f"unknown endpoint {path}"}}, 400)

    return Handler
