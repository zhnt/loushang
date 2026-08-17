"""Simulate a CLI-owned browser interaction for config-driven OAuth login."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

import loushang.ai as ai
from loushang.ai.advanced.registry import (
    clear_api_adapters,
    register_api_adapter,
    reset_api_adapters,
)
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.model import Auth, Capabilities, Model, OAuthConfig
from loushang.ai.provider import ProviderRequest


class _OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/authorize":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        query = parse_qs(parsed.query)
        location = f"{query['redirect_uri'][0]}?{urlencode({'code': 'demo-code', 'state': query['state'][0]})}"
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/token":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        if form.get("code") != ["demo-code"]:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        body = json.dumps(
            {
                "access_token": "oauth-access-secret",
                "refresh_token": "oauth-refresh-secret",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def _oauth_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OAuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _RecordingProvider:
    api = "auth-example-oauth-login"

    def __init__(self) -> None:
        self.request: ProviderRequest | None = None

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        self.request = request
        yield {"type": "response_start", "response_id": "oauth-login-example"}
        yield {"type": "text_delta", "text": "ok"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


async def _open_browser(authorization_url: str) -> None:
    """Offline stand-in for webbrowser.open, owned by this CLI example."""

    async with httpx.AsyncClient(follow_redirects=True, trust_env=False) as client:
        response = await client.get(authorization_url)
    response.raise_for_status()


async def run(base_url: str) -> dict[str, object]:
    provider = _RecordingProvider()
    model = Model(
        id="oauth-login-example",
        provider="example",
        endpoint="oauth",
        api=provider.api,
        base_url="https://offline.example/v1",
        auth=Auth(
            kind="oauth",
            provider="example-oauth",
            oauth=OAuthConfig(
                client_id="example-client",
                authorization_endpoint=f"{base_url}/authorize",
                token_endpoint=f"{base_url}/token",
                scopes=("model.invoke",),
            ),
        ),
        capabilities=Capabilities(stream=True),
    )
    with TemporaryDirectory() as directory:
        store = ai.FileCredentialStore(directory)
        before = await ai.auth.status(model, store=store)
        session = await ai.auth.login(model, store=store)
        browser = asyncio.create_task(_open_browser(session.authorization_url))
        credential = await session.wait()
        await browser
        request_auth = await ai.auth.get_auth(model, store=store)
        after = await ai.auth.status(model, store=store)
        clear_api_adapters()
        register_api_adapter(provider)
        try:
            await ai.complete(
                model,
                {"messages": [{"role": "user", "content": "hello"}]},
                auth=request_auth,
            )
        finally:
            reset_api_adapters()

    if provider.request is None:
        raise RuntimeError("ProviderRequest was not captured")
    return {
        "beforeActions": list(before.actions),
        "browserOpenedByApplication": True,
        "loginProvider": credential.provider,
        "authenticated": after.authenticated,
        "requestAuthorized": provider.request.headers.get("Authorization")
        == "Bearer oauth-access-secret",
    }


def main() -> None:
    with _oauth_server() as base_url:
        print(json.dumps(asyncio.run(run(base_url)), sort_keys=True))


if __name__ == "__main__":
    main()
