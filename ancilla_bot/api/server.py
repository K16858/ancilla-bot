from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


def run_server(host: str, port: int, handler: Callable[[str], str]) -> None:
    class ChatHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/chat":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body or "{}")
                message = (data.get("message") or "").strip()
            except (ValueError, json.JSONDecodeError, KeyError):
                self.send_error(400, "Bad Request")
                return
            response_text = handler(message)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"response": response_text}, ensure_ascii=False).encode("utf-8"))

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer((host, port), ChatHandler)
    server.serve_forever()
