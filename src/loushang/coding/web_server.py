"""Standalone browser entrypoint for an installed Host (no desktop required).

The same adapter is used by Vite. HTTP is loopback-only; remote listeners require
TLS. Authentication is separate from model-provider credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import ssl
import threading
from contextlib import suppress
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from loushang.foundation.platform_paths import resolve_platform_home

from .web_gateway import WebGateway


class WebServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, address, gateway, loop, token, dist, secure=False):
        self.gateway, self.loop, self.token, self.dist = gateway, loop, token, dist
        self.cookie_name = (
            "loushang_session_" + hashlib.sha256(token.encode()).hexdigest()[:12]
        )
        self.secure = secure
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, WebHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(90)
        return connection, address

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class WebHandler(BaseHTTPRequestHandler):
    server: WebServer

    def log_message(self, *_):
        # Requests can contain a login token; never log bodies or URL queries.
        pass

    def respond(self, status, body, content_type="application/json", cookie=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            return hmac.compare_digest(authorization[7:], self.server.token)
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return False
        return self.server.cookie_name in cookie and hmac.compare_digest(
            cookie[self.server.cookie_name].value, self.server.token
        )

    def same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True  # Native bearer clients do not send a browser Origin.
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == self.headers.get(
            "Host"
        )

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000 or not self.same_origin():
                return self.respond(403, '{"error":"forbidden"}')
            raw = self.rfile.read(length)
            if self.path == "/login":
                token = parse_qs(raw.decode()).get("token", [""])[0]
                if not hmac.compare_digest(token, self.server.token):
                    return self.respond(401, "Invalid access token", "text/plain")
                cookie = (
                    self.server.cookie_name
                    + "="
                    + self.server.token
                    + "; HttpOnly; SameSite=Strict; Path=/"
                )
                if self.server.secure:
                    cookie += "; Secure"
                return self.respond(
                    200,
                    '<a href="/">Open Loushang</a>',
                    "text/html; charset=utf-8",
                    cookie,
                )
            if (
                self.path != "/api/loushang"
                or not self.authorized()
                or self.headers.get("X-Loushang-Client") != "1"
            ):
                return self.respond(403, '{"error":"forbidden"}')
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError()
            if request.get("operation") == "shutdown-adapter":
                self.respond(200, '{"result":{}}')
                threading.Thread(target=self.server.shutdown).start()
                return
            future = asyncio.run_coroutine_threadsafe(
                self.server.gateway.dispatch(request), self.server.loop
            )
            try:
                result = future.result(timeout=75)
            except TimeoutError:
                future.cancel()
                raise
            return self.respond(200, json.dumps({"result": result}))
        except Exception:
            return self.respond(503, '{"error":"host_request_failed"}')

    def do_GET(self):
        if not self.authorized():
            return self.respond(
                200,
                """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Loushang</title><main><h1>Connect to Loushang</h1>
<form method="post" action="/login"><label>Server access token
<input name="token" type="password" required autocomplete="current-password"></label>
<button>Connect</button></form></main></html>""",
                "text/html; charset=utf-8",
            )
        if self.server.dist is None:
            return self.respond(
                404,
                "Web assets unavailable. Build gui/dist or set host.json web.dist.",
                "text/plain",
            )
        path = (self.server.dist / urlsplit(self.path).path.lstrip("/")).resolve()
        if not path.is_relative_to(self.server.dist):
            return self.respond(403, '{"error":"forbidden"}')
        if path.is_dir():
            path = path / "index.html"
        if not path.is_file():
            return self.respond(404, '{"error":"not_found"}')
        import mimetypes

        self.respond(
            200,
            path.read_bytes(),
            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )


def main():
    parser = argparse.ArgumentParser(description="Serve the real Loushang Host UI")
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    home = resolve_platform_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    (home / "state").mkdir(mode=0o700, exist_ok=True)
    state = home / "state" / "web"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    lease = sqlite3.connect(state / "owner.sqlite3", timeout=1)
    lease.execute("BEGIN IMMEDIATE")
    config_path = home / "host.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    web = config.get("web", {})
    bind, port = web.get("bind", "127.0.0.1"), web.get("port", 1422)
    certificate, key = web.get("certificate"), web.get("privateKey")
    secure = bool(certificate and key)
    if bind not in {"127.0.0.1", "localhost"} and not secure:
        parser.error(
            "a remote listener requires web.certificate and web.privateKey in host.json"
        )
    (home / "auth").mkdir(mode=0o700, exist_ok=True)
    token_path = home / "auth" / "server" / "web-token"
    token_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not token_path.exists():
        descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(secrets.token_urlsafe(32))
    token = token_path.read_text().strip()
    if len(token) < 32:
        parser.error("invalid server access token")
    default_dist = Path(__file__).resolve().parents[3] / "gui" / "dist"
    dist_value = (
        args.dist
        or web.get("dist")
        or (default_dist if default_dist.is_dir() else None)
    )
    dist = Path(dist_value).expanduser().resolve() if dist_value else None
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever)
    thread.start()
    gateway = WebGateway()
    try:
        with WebServer((bind, port), gateway, loop, token, dist, secure) as server:
            if secure:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(certificate, key)
                server.socket = context.wrap_socket(server.socket, server_side=True)
            endpoint_file = state / "endpoint.json"
            endpoint = {
                "url": f"{'https' if secure else 'http'}://127.0.0.1:{server.server_port}",
                "pid": os.getpid(),
            }
            temporary = state / "endpoint.tmp"
            temporary.write_text(json.dumps(endpoint))
            temporary.chmod(0o600)
            temporary.replace(endpoint_file)
            print(
                f"Loushang: {'https' if secure else 'http'}://{bind}:{server.server_port}; access token file: {token_path}",
                flush=True,
            )
            with suppress(KeyboardInterrupt):
                server.serve_forever()
    finally:
        asyncio.run_coroutine_threadsafe(gateway.close(), loop).result(timeout=30)
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()
        lease.close()


if __name__ == "__main__":
    main()
