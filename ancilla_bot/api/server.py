from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urlsplit

from loguru import logger

from ancilla_bot.api import v1, webui
from ancilla_bot.assistant import companion_session, timers
from ancilla_bot.core.cancel import request_cancel
from ancilla_bot.core.execution import ConversationBusy
from ancilla_bot.homelab import events, incidents, store
from ancilla_bot.notifications import store as notif_store
from ancilla_bot.runtime import approval

SSE_POLL_SEC = 2.0
SSE_HEARTBEAT_SEC = 15.0

_stream_cond = threading.Condition()
_stream_gen = 0


def notify_stream_change(*_args) -> None:
    global _stream_gen
    with _stream_cond:
        _stream_gen += 1
        _stream_cond.notify_all()


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
    companion_handler: Callable[..., dict[str, Any]] | None = None,
    companion_end_handler: Callable[[str], bool] | None = None,
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
            info = store.verify_api_token_info(auth[7:].strip()) if auth[:7].lower() == "bearer " else None
            role = info[1] if info else None
            self._token_name = info[0] if info else ""
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
            if u.path == "/api/v1/me":
                auth = self.headers.get("Authorization", "")
                self._json(200, {"name": self._token_name, "role": store.verify_api_token(auth[7:].strip())})
                return
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
            raw_notif = q.get("after_notification") or ""
            try:
                notif_cursor = int(raw_notif) if raw_notif else notif_store.last_notification_id()
            except ValueError:
                self._json(400, {"error": "after_notification は整数で指定してください"})
                return
            sig = incidents.signature()
            asig = approval.signature()
            tsig = timers.signature()
            seen_firing = {t["id"] for t in timers.list_timers() if t["status"] == "firing"}
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
                    with _stream_cond:
                        gen = _stream_gen
                    for e in events.events_after(cursor):
                        cursor = e["id"]
                        send(f"id: {cursor}\nevent: homelab_event\ndata: {json.dumps(e, ensure_ascii=False)}\n\n")
                    new_sig = incidents.signature()
                    if new_sig != sig:
                        sig = new_sig
                        send("event: incidents_changed\ndata: {}\n\n")
                    new_asig = approval.signature()
                    if new_asig != asig:
                        asig = new_asig
                        send("event: approvals_changed\ndata: {}\n\n")
                    for n in notif_store.notifications_after(notif_cursor):
                        notif_cursor = n["id"]
                        send(f"event: notification\ndata: {json.dumps(n, ensure_ascii=False)}\n\n")
                    new_tsig = timers.signature()
                    if new_tsig != tsig:
                        tsig = new_tsig
                        payload = timers.list_timers_payload()
                        current_firing = {t["id"] for t in payload["timers"] if t["status"] == "firing"}
                        for t in payload["timers"]:
                            if t["status"] == "firing" and t["id"] not in seen_firing:
                                send(f"event: timer_fired\ndata: {json.dumps(t, ensure_ascii=False)}\n\n")
                        seen_firing = current_firing
                        send(f"event: timers_changed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n")
                    if time.monotonic() - last_write >= SSE_HEARTBEAT_SEC:
                        send(": heartbeat\n\n")
                    with _stream_cond:
                        if _stream_gen == gen:
                            _stream_cond.wait(timeout=SSE_POLL_SEC)
            except OSError:  # 切断（BrokenPipe / ConnectionReset / Abort）
                return

        def _read_raw(self) -> bytes | None:
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length < 0:
                    raise ValueError
                return self.rfile.read(length)  # 拒否前に読み切る（RST 回避）
            except ValueError:
                self.send_error(400, "Bad Request")
                return None

        def _parse_json_dict(self, raw: bytes) -> dict | None:
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"error": "不正な JSON です"})
                return None
            if not isinstance(data, dict):
                self._json(400, {"error": "JSON object を指定してください"})
                return None
            return data

        def do_POST(self):
            u = urlsplit(self.path)
            is_v1 = u.path.startswith("/api/v1/")
            raw = self._read_raw()
            if raw is None:
                return
            if not self._gate(is_v1, "operate"):
                return
            if (u.path == "/cancel" and not is_v1) or u.path == "/api/v1/chat/cancel":
                (cancel_handler or request_cancel)()
                self._json(200, {"ok": True})
                return
            if u.path == "/api/v1/companion/chat":
                data = self._parse_json_dict(raw)
                if data is None:
                    return
                message = data.get("message")
                if not isinstance(message, str) or not message.strip():
                    self._json(400, {"error": "message は必須です"})
                    return
                session_id = str(data.get("session_id") or "").strip() or "default"
                reset_pending = bool(data.get("reset_pending", False))
                chat_fn = companion_handler or companion_session.handle_companion_message
                try:
                    res = chat_fn(
                        message.strip(),
                        session_id=session_id,
                        reset_pending=reset_pending,
                    )
                except ConversationBusy:
                    self._json(409, {"ok": False, "error": "conversation busy"})
                except ValueError as e:
                    self._json(400, {"error": str(e)})
                else:
                    self._json(200, res)
                return
            if u.path == "/api/v1/companion/session/end":
                data = self._parse_json_dict(raw)
                if data is None:
                    return
                session_id = str(data.get("session_id") or "").strip() or "default"
                end_fn = companion_end_handler or companion_session.end_session
                ended = bool(end_fn(session_id))
                self._json(200, {"ok": True, "ended": ended, "session_id": session_id})
                return
            if u.path == "/api/v1/timers":
                data = self._parse_json_dict(raw)
                if data is None:
                    return
                if "duration_sec" not in data or data["duration_sec"] is None:
                    self._json(400, {"error": "duration_sec は必須です"})
                    return
                try:
                    item = timers.create_timer(
                        data["duration_sec"],
                        label=data.get("label") or "",
                        source=f"api:{self._token_name}",
                    )
                except ValueError as e:
                    self._json(400, {"error": str(e)})
                    return
                self._json(201, item)
                return
            m = re.fullmatch(r"/api/v1/approvals/([^/]+)/(approve|reject)", u.path)
            if m:  # CLI / Discord / Slack と同じ関数。TTL・policy の再検査は Core 側。承認は同期実行（最大 ~60s）
                fn = approval.approve_run if m[2] == "approve" else approval.reject_run
                self._json(200, {"message": fn(unquote(m[1]), f"webui:{self._token_name}")})
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

        def do_PATCH(self):
            u = urlsplit(self.path)
            is_v1 = u.path.startswith("/api/v1/")
            raw = self._read_raw()
            if raw is None:
                return
            if not self._gate(is_v1, "operate"):
                return
            m = re.fullmatch(r"/api/v1/timers/([^/]+)", u.path)
            if not m:
                self._json(404, {"error": "not found"})
                return
            data = self._parse_json_dict(raw)
            if data is None:
                return
            tid = unquote(m[1])
            try:
                if data.get("action") == "stop":
                    items = timers.stop_timer(tid)
                    self._json(200, items[0])
                else:
                    item = timers.update_timer(
                        tid,
                        duration_sec=data.get("duration_sec"),
                        add_sec=data.get("add_sec"),
                        label=data.get("label"),
                    )
                    self._json(200, item)
            except LookupError as e:
                self._json(404, {"error": str(e)})
            except ValueError as e:
                self._json(400, {"error": str(e)})

        def do_DELETE(self):
            u = urlsplit(self.path)
            is_v1 = u.path.startswith("/api/v1/")
            raw = self._read_raw()
            if raw is None:
                return
            if not self._gate(is_v1, "operate"):
                return
            m = re.fullmatch(r"/api/v1/timers/([^/]+)", u.path)
            if not m:
                self._json(404, {"error": "not found"})
                return
            try:
                item = timers.cancel_timer(unquote(m[1]))
            except LookupError as e:
                self._json(404, {"error": str(e)})
                return
            self._json(200, item)

        def log_message(self, format, *args):
            pass

    timers.subscribe_changes(notify_stream_change)
    notif_store.subscribe_notifications(notify_stream_change)
    return ThreadingHTTPServer((host, port), ChatHandler)


def run_server(
    host: str,
    port: int,
    handler: Callable[[str, list[str] | None], str],
    *,
    cancel_handler: Callable[[], None] | None = None,
    companion_handler: Callable[..., dict[str, Any]] | None = None,
    companion_end_handler: Callable[[str], bool] | None = None,
) -> None:
    make_server(
        host,
        port,
        handler,
        cancel_handler=cancel_handler,
        companion_handler=companion_handler,
        companion_end_handler=companion_end_handler,
    ).serve_forever()
