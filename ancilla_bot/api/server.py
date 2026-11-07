from __future__ import annotations

import ipaddress
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qsl, urlsplit

from loguru import logger

from ancilla_bot.api import v1, webui
from ancilla_bot.core.execution import ConversationBusy
from ancilla_bot.homelab import events, incidents, store

SSE_POLL_SEC = 2.0
SSE_HEARTBEAT_SEC = 15.0


def _peer(handler: BaseHTTPRequestHandler) -> str:
    return handler.client_address[0]


def _is_loopback(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    return (getattr(ip, "ipv4_mapped", None) or ip).is_loopback


def make_server(
    host: str,
    port: int,
    handler: Callable[[str, list[str] | None], str],
    *,
    cancel_handler: Callable[[], None] | None = None,
) -> ThreadingHTTPServer:
    # ThreadingHTTPServer は接続ごとにスレッド（daemon）を使うので、SSE が他のリクエストを塞がない
    class ChatHandler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError) as e:
                logger.debug("client closed connection before response was sent: {}", e)

        def _authorized(self, need: str) -> bool:
            """Bearer トークンを検証し、足りなければ 401 / 403 を返して False。"""
            auth = self.headers.get("Authorization", "")
            role = store.verify_api_token(auth[7:].strip()) if auth[:7].lower() == "bearer " else None
            if role is None:
                self._json(401, {"error": "unauthorized"})
                return False
            if need == "operate" and role != "operate":
                self._json(403, {"error": "forbidden"})
                return False
            return True

        def _gate(self, v1_path: bool, need: str) -> bool:
            if v1_path:
                return self._authorized(need)
            if _is_loopback(_peer(self)):  # 従来のエンドポイントはループバックなら認証なし
                return True
            if self.headers.get("Authorization"):
                return self._authorized("operate")
            self._json(403, {"error": "forbidden"})
            return False

        def do_GET(self):
            u = urlsplit(self.path)
            is_v1 = u.path.startswith("/api/v1/")
            if u.path in ("/", "/ui"):  # WebUI の入口
                self.send_response(302)
                self.send_header("Location", "/ui/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if u.path.startswith("/ui/"):  # 静的ファイル。トークン不要
                status, ctype, body, cache = webui.resolve(u.path)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", cache)
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if u.path == "/health":  # 生存確認だけ（{"ok": true}）。外部の死活監視用にトークン不要
                self._json(200, {"ok": True})
                return
            if not self._gate(is_v1, "read"):
                return
            if not is_v1:
                if u.path != "/health":
                    self.send_error(404)
                else:
                    self._json(200, {"ok": True})
                return
            q = dict(parse_qsl(u.query))
            if u.path == "/api/v1/stream":
                self._stream(q)
                return
            self._json(*v1.route(u.path, q))

        def _stream(self, q: dict[str, str]) -> None:
            raw = self.headers.get("Last-Event-ID") or q.get("after") or ""
            try:
                cursor = int(raw) if raw else events.last_event_id()
            except ValueError:
                self._json(400, {"error": "Last-Event-ID / after は整数で指定してください"})
                return
            sig = incidents.signature()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            last_write = time.monotonic()

            def send(text: str) -> None:
                nonlocal last_write
                self.wfile.write(text.encode("utf-8"))
                self.wfile.flush()
                last_write = time.monotonic()

            try:
                send(": connected\n\n")
                while True:
                    for e in events.events_after(cursor):
                        cursor = e["id"]
                        send(f"id: {cursor}\nevent: homelab_event\ndata: {json.dumps(e, ensure_ascii=False)}\n\n")
                    new_sig = incidents.signature()
                    if new_sig != sig:
                        sig = new_sig
                        send("event: incidents_changed\ndata: {}\n\n")
                    if time.monotonic() - last_write >= SSE_HEARTBEAT_SEC:
                        send(": heartbeat\n\n")
                    time.sleep(SSE_POLL_SEC)
            except OSError:  # 切断（BrokenPipe / ConnectionReset / Abort）
                return

        def do_POST(self):
            u = urlsplit(self.path)
            is_v1 = u.path.startswith("/api/v1/")
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))  # 拒否前に読み切る（RST 回避）
            except ValueError:
                self.send_error(400, "Bad Request")
                return
            if not self._gate(is_v1, "operate"):
                return
            if u.path == "/cancel" and not is_v1:
                if cancel_handler is not None:
                    cancel_handler()
                self._json(200, {"ok": True})
                return
            if u.path not in ("/chat", "/api/v1/chat"):
                self.send_error(404)
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
                message = (data.get("message") or "").strip()
                images = data.get("images")
                if isinstance(images, list):
                    images = [str(x) for x in images if x][:4]
                else:
                    images = None
            except (ValueError, KeyError):  # JSONDecodeError / UnicodeDecodeError は ValueError
                self.send_error(400, "Bad Request")
                return
            try:
                response_text = handler(message, images)
            except ConversationBusy:
                self._json(409, {"ok": False})
            else:
                self._json(200, {"response": response_text})

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer((host, port), ChatHandler)


def run_server(
    host: str,
    port: int,
    handler: Callable[[str, list[str] | None], str],
    *,
    cancel_handler: Callable[[], None] | None = None,
) -> None:
    make_server(host, port, handler, cancel_handler=cancel_handler).serve_forever()
