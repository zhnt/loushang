"""Standalone browser entrypoint for an installed Host (no desktop required).

The same adapter is used by Vite. The default listener is loopback-only.
Listener exposure is user-configured; account authentication is future work.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sqlite3
import ssl
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from loushang.foundation.platform_paths import resolve_platform_home

from .web_gateway import ExternalHost, WebGateway


class WebServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, address, gateway, loop, dist, secure=False):
        self.gateway, self.loop, self.dist = gateway, loop, dist
        self.secure = secure
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, WebHandler)
        self.local_access = ipaddress.ip_address(self.server_address[0]).is_loopback

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
        # Never log request bodies or URL queries.
        pass

    def respond(self, status, body, content_type="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def allowed_host(self):
        # Keep local-only listeners local even under DNS rebinding. This is
        # request-origin validation, not account authentication.
        if self.server.local_access:
            try:
                target = urlsplit("//" + self.headers.get("Host", ""))
                if (
                    ipaddress.ip_address(self.client_address[0]).is_loopback
                    and target.hostname in {"127.0.0.1", "localhost", "::1"}
                    and target.port == self.server.server_port
                    and not target.username
                    and not target.password
                    and not target.path
                    and not target.query
                    and not target.fragment
                ):
                    return True
            except ValueError:
                pass
        return not self.server.local_access

    def same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True  # Native clients do not send a browser Origin.
        parsed = urlsplit(origin)
        return parsed.scheme == (
            "https" if self.server.secure else "http"
        ) and parsed.netloc == self.headers.get("Host")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000 or not self.same_origin():
                return self.respond(403, '{"error":"forbidden"}')
            raw = self.rfile.read(length)
            if (
                self.path != "/api/loushang"
                or not self.allowed_host()
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
        if not self.allowed_host():
            return self.respond(403, '{"error":"forbidden"}')
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
    parser.add_argument(
        "--external-host", nargs=3, metavar=("WORKSPACE", "CONNECTION_ROOT", "MUX"),
        help="connect to an existing Host whose lifetime is managed externally",
    )
    args = parser.parse_args()
    external_host = None
    if args.external_host is not None:
        workspace, connection_root, mux = args.external_host
        external_host = ExternalHost(
            Path(workspace).expanduser().resolve(), Path(connection_root).expanduser().resolve(), mux
        )
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
    if bool(certificate) != bool(key):
        parser.error("configure both web.certificate and web.privateKey for TLS")
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
    gateway = WebGateway(external_host)
    try:
        with WebServer((bind, port), gateway, loop, dist, secure) as server:
            if secure:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(certificate, key)
                server.socket = context.wrap_socket(server.socket, server_side=True)
            endpoint_file = state / "endpoint.json"
            endpoint = {
                "url": f"{'https' if secure else 'http'}://{'127.0.0.1' if bind in {'0.0.0.0', 'localhost'} else bind}:{server.server_port}",
                "pid": os.getpid(),
            }
            temporary = state / "endpoint.tmp"
            temporary.write_text(json.dumps(endpoint))
            temporary.chmod(0o600)
            temporary.replace(endpoint_file)
            address = f"Loushang: {'https' if secure else 'http'}://{bind}:{server.server_port}"
            print(address, flush=True)
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
