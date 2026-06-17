from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from loguru import logger


def run_server(
    host: str,
    port: int,
    handler: Callable[[str, list[str] | None], str],
    *,
    cancel_handler: Callable[[], None] | None = None,
) -> None:
    class ChatHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/cancel":
                if cancel_handler is not None:
                    cancel_handler()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8"))
                return
            if self.path != "/chat":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body or "{}")
                message = (data.get("message") or "").strip()
                images = data.get("images")
                if isinstance(images, list):
                    images = [str(x) for x in images if x][:4]
                else:
                    images = None
            except (ValueError, json.JSONDecodeError, KeyError):
                self.send_error(400, "Bad Request")
                return
            response_text = handler(message, images)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"response": response_text}, ensure_ascii=False).encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError) as e:
                logger.debug("client closed connection before response was sent: {}", e)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer((host, port), ChatHandler)
    server.serve_forever()
