from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

from loushang.ai import OAuthBearerAuth
from loushang.ai.auth import FileCredentialStore, get_auth, login
from loushang.ai.model import Auth, Model, OAuthConfig


@dataclass
class _OAuthServerState:
    authorization_requests: list[dict[str, list[str]]] = field(default_factory=list)
    token_requests: list[dict[str, list[str]]] = field(default_factory=list)
    code_challenge: str | None = None


class _OAuthServer(ThreadingHTTPServer):
    state: _OAuthServerState


class _OAuthHandler(BaseHTTPRequestHandler):
    server: _OAuthServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/authorize":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        query = parse_qs(parsed.query)
        self.server.state.authorization_requests.append(query)
        self.server.state.code_challenge = query.get("code_challenge", [None])[0]
        redirect_uri = query["redirect_uri"][0]
        location = f"{redirect_uri}?{urlencode({'code': 'local-code', 'state': query['state'][0]})}"
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/token":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        self.server.state.token_requests.append(form)
        grant_type = form.get("grant_type", [""])[0]
        if grant_type == "authorization_code":
            verifier = form.get("code_verifier", [""])[0]
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            ).rstrip(b"=").decode("ascii")
            if (
                form.get("code") != ["local-code"]
                or challenge != self.server.state.code_challenge
            ):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_grant"},
                )
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "access_token": "initial-access",
                    "refresh_token": "refresh-token",
                    "expires_in": 1,
                    "token_type": "Bearer",
                },
            )
            return
        if grant_type == "refresh_token" and form.get("refresh_token") == [
            "refresh-token"
        ]:
            self._send_json(
                HTTPStatus.OK,
                {
                    "access_token": "refreshed-access",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
            return
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "unsupported_grant_type"})

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def _fake_oauth_server() -> Iterator[tuple[str, _OAuthServerState]]:
    server = _OAuthServer(("127.0.0.1", 0), _OAuthHandler)
    server.state = _OAuthServerState()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", server.state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.requires_host_runtime
def test_real_authlib_login_store_resolve_refresh_lifecycle(tmp_path: Path) -> None:
    async def scenario(base_url: str, state: _OAuthServerState):
        model = Model(
            id="local-model",
            provider="local",
            endpoint="oauth",
            api="openai-responses",
            base_url="https://model.test/v1",
            auth=Auth(
                kind="oauth",
                provider="local-oauth",
                oauth=OAuthConfig(
                client_id="local-client",
                authorization_endpoint=f"{base_url}/authorize",
                token_endpoint=f"{base_url}/token",
                scopes=("model.read",),
                token_endpoint_auth_method="none",
            ),
            ),
        )
        store = FileCredentialStore(tmp_path)

        session = await login(model, store=store)
        async with httpx.AsyncClient(follow_redirects=True, trust_env=False) as client:
            response = await client.get(session.authorization_url)
        assert response.status_code == HTTPStatus.OK
        initial = await session.wait()
        request_auth = await get_auth(
            model,
            store=store,
            now=initial.expires_at,
        )
        return initial, request_auth, store.load("local-oauth"), state, session

    with _fake_oauth_server() as (base_url, state):
        initial, request_auth, stored, server_state, session = asyncio.run(
            scenario(base_url, state)
        )

    assert initial.access_token == "initial-access"
    assert initial.refresh_token == "refresh-token"
    assert request_auth == OAuthBearerAuth("refreshed-access")
    assert session.authorization_url.startswith(f"{base_url}/authorize?")
    assert session.redirect_uri.startswith("http://127.0.0.1:")
    assert stored is not None
    assert stored.access_token == "refreshed-access"
    assert stored.refresh_token == "refresh-token"
    assert len(server_state.authorization_requests) == 1
    assert server_state.authorization_requests[0]["code_challenge_method"] == [
        "S256"
    ]
    assert [request["grant_type"] for request in server_state.token_requests] == [
        ["authorization_code"],
        ["refresh_token"],
    ]
