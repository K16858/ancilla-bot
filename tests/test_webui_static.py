import socket
import threading

import httpx
import pytest

from ancilla_bot.api import server


@pytest.fixture
def ui(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>ui</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "assets" / "app.css").write_text("a{}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    monkeypatch.setenv("ANCILLA_WEBUI_DIR", str(dist))
    srv = server.make_server("127.0.0.1", 0, lambda m, i: "")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], dist
    srv.shutdown()
    srv.server_close()


def get(port, path):
    # httpx は ../ を正規化するので生のリクエストを送る
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(f"GET {path} HTTP/1.0\r\nHost: x\r\n\r\n".encode())
        buf = b""
        while chunk := s.recv(65536):
            buf += chunk
    head, _, body = buf.partition(b"\r\n\r\n")
    return int(head.split()[1]), head.decode("latin-1").lower(), body


def test_index_and_assets_without_token(ui):
    port, _ = ui
    for p in ("/ui", "/ui/"):
        r = httpx.get(f"http://127.0.0.1:{port}{p}", follow_redirects=True)
        assert r.status_code == 200 and "<title>ui</title>" in r.text
        assert r.headers["content-type"].startswith("text/html")
    r = httpx.get(f"http://127.0.0.1:{port}/ui/assets/app.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    r = httpx.get(f"http://127.0.0.1:{port}/ui/assets/app.css")
    assert r.headers["content-type"].startswith("text/css")
    r = httpx.get(f"http://127.0.0.1:{port}/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/ui/"


def test_spa_fallback_but_missing_asset_404(ui):
    port, _ = ui
    r = httpx.get(f"http://127.0.0.1:{port}/ui/incidents/INC-000001")
    assert r.status_code == 200 and "<title>ui</title>" in r.text
    assert httpx.get(f"http://127.0.0.1:{port}/ui/assets/missing.js").status_code == 404


@pytest.mark.parametrize("path", [
    "/ui/../secret.txt", "/ui/%2e%2e/secret.txt", "/ui/%2E%2E%2Fsecret.txt",
    "/ui/assets/../../secret.txt", "/ui/..%5Csecret.txt", "/ui/%00",
    "/ui/C:/Windows/win.ini", "/ui//etc/passwd",
])
def test_traversal_rejected(ui, path):
    port, _ = ui
    status, _, body = get(port, path)
    assert b"SECRET" not in body
    assert status != 200 or b"<title>ui</title>" in body  # 脱出せず index か 404


def test_traversal_not_served_directly(ui):
    port, _ = ui
    for p in ("/ui/../secret.txt", "/ui/%2e%2e/secret.txt"):
        assert get(port, p)[0] == 404


def test_missing_dist_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCILLA_WEBUI_DIR", str(tmp_path / "none"))
    srv = server.make_server("127.0.0.1", 0, lambda m, i: "")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = httpx.get(f"http://127.0.0.1:{srv.server_address[1]}/ui/")
        assert r.status_code == 404 and "npm run build" in r.text
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_still_requires_token(ui):
    port, _ = ui
    assert httpx.get(f"http://127.0.0.1:{port}/api/v1/summary").status_code == 401
