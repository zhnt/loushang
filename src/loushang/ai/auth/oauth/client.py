from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from loushang.ai.auth.credentials import OAuthCredential
from loushang.ai.auth.errors import (
    AuthError,
    InvalidCredentialError,
    OAuthProviderNotConfiguredError,
    RefreshFailedError,
)
from loushang.ai.auth.oauth.base import AuthorizationCallback
from loushang.ai.auth.store import FileCredentialStore

_DEFAULT_REDIRECT_URI = "http://127.0.0.1:0/callback"


@dataclass(frozen=True, slots=True)
class OAuthClientConfig:
    client_id: str | None
    authorization_endpoint: str | None
    token_endpoint: str | None
    redirect_uri: str | None
    client_secret: str | None = None
    scopes: Sequence[str] = ()
    revocation_endpoint: str | None = None
    token_endpoint_auth_method: str | None = None


class OAuthLoginSession:
    """Pending OAuth authorization owned by the calling application."""

    def __init__(
        self,
        *,
        provider: str,
        authorization_url: str,
        redirect_uri: str,
        wait_for_credential: Callable[[], Awaitable[OAuthCredential]],
        close_session: Callable[[], Awaitable[None]],
    ) -> None:
        self.provider = provider
        self.authorization_url = authorization_url
        self.redirect_uri = redirect_uri
        self._wait_for_credential = wait_for_credential
        self._close_session = close_session
        self._wait_task: asyncio.Future[OAuthCredential] | None = None

    async def wait(self) -> OAuthCredential:
        if self._wait_task is None:
            self._wait_task = asyncio.ensure_future(self._wait_for_credential())
        return await self._wait_task

    async def close(self) -> None:
        if self._wait_task is not None and not self._wait_task.done():
            self._wait_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._wait_task
        await self._close_session()


class AuthlibOAuthProvider:
    """OAuth authorization-code provider implemented by Authlib."""

    id: str

    def __init__(self, provider_id: str, config: OAuthClientConfig) -> None:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id must be a non-empty string")
        self.id = provider_id.strip()
        self.config = config

    async def start_login(
        self,
        *,
        store: FileCredentialStore | None = None,
    ) -> OAuthLoginSession:
        self._require_login_config(allow_default_redirect=True)
        callback = await _LoopbackOAuthCallback.start(
            self.config.redirect_uri or _DEFAULT_REDIRECT_URI
        )
        client = self._new_client(redirect_uri=callback.redirect_uri)
        from authlib.common.security import (  # type: ignore[import-untyped]
            generate_token,
        )

        code_verifier = generate_token(48)
        try:
            authorization_url, state = client.create_authorization_url(
                self.config.authorization_endpoint,
                code_verifier=code_verifier,
            )
        except Exception:
            await callback.close()
            await client.aclose()
            raise

        closed = False

        async def close_session() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            await callback.close()
            await client.aclose()

        async def wait_for_credential() -> OAuthCredential:
            try:
                authorization_response = await callback.wait()
                try:
                    token = await client.fetch_token(
                        self.config.token_endpoint,
                        authorization_response=authorization_response,
                        code_verifier=code_verifier,
                        state=state,
                    )
                except AuthError:
                    raise
                except Exception as error:
                    raise AuthError(
                        "OAuth login failed.",
                        provider=self.id,
                        details={
                            "cause": type(error).__name__,
                            "recovery": "login",
                        },
                    ) from error
                credential = self.credential_from_token(token)
                (store or FileCredentialStore()).save(credential)
                return credential
            finally:
                await close_session()

        return OAuthLoginSession(
            provider=self.id,
            authorization_url=authorization_url,
            redirect_uri=callback.redirect_uri,
            wait_for_credential=wait_for_credential,
            close_session=close_session,
        )

    async def login(
        self,
        *,
        authorize: AuthorizationCallback | None = None,
    ) -> OAuthCredential:
        self._require_login_config()
        if authorize is None:
            raise OAuthProviderNotConfiguredError(
                "OAuth login requires an authorization callback that returns the final redirect URL.",
                provider=self.id,
                details={"recovery": "provide_login_interaction"},
            )
        from authlib.common.security import (  # type: ignore[import-untyped]
            generate_token,
        )

        client = self._new_client()
        code_verifier = generate_token(48)
        try:
            try:
                authorization_url, state = client.create_authorization_url(
                    self.config.authorization_endpoint,
                    code_verifier=code_verifier,
                )
                authorization_response = await authorize(authorization_url)
                if (
                    not isinstance(authorization_response, str)
                    or not authorization_response.strip()
                ):
                    raise InvalidCredentialError(
                        "OAuth authorization callback returned no redirect URL.",
                        provider=self.id,
                        details={"recovery": "login"},
                    )
                token = await client.fetch_token(
                    self.config.token_endpoint,
                    authorization_response=authorization_response,
                    code_verifier=code_verifier,
                    state=state,
                )
            except AuthError:
                raise
            except Exception as error:
                raise AuthError(
                    "OAuth login failed.",
                    provider=self.id,
                    details={
                        "cause": type(error).__name__,
                        "recovery": "login",
                    },
                ) from error
        finally:
            await client.aclose()
        return self.credential_from_token(token)

    async def refresh(self, credential: OAuthCredential) -> OAuthCredential:
        self._require_refresh_config()
        if credential.provider != self.id:
            raise InvalidCredentialError(
                "OAuth credential provider does not match the refresh adapter.",
                provider=self.id,
                details={
                    "credential_provider": credential.provider,
                    "recovery": "reconfigure",
                },
            )
        if credential.refresh_token is None:
            raise InvalidCredentialError(
                "OAuth credential has no refresh token.",
                provider=self.id,
                details={"recovery": "login"},
            )
        client = self._new_client(token=_oauth_token(credential))
        try:
            try:
                token = await client.refresh_token(
                    self.config.token_endpoint,
                    refresh_token=credential.refresh_token,
                )
            except AuthError:
                raise
            except Exception as error:
                raise RefreshFailedError(
                    "OAuth credential refresh failed.",
                    provider=self.id,
                    details={
                        "cause": type(error).__name__,
                        "recovery": "login",
                    },
                ) from error
        finally:
            await client.aclose()
        return self.credential_from_token(token, previous=credential)

    async def revoke(self, credential: OAuthCredential) -> None:
        if not self.config.revocation_endpoint:
            return
        self._require_client_id()
        client = self._new_client(token=_oauth_token(credential))
        try:
            await client.revoke_token(
                self.config.revocation_endpoint,
                token=credential.refresh_token or credential.access_token,
                token_type_hint=(
                    "refresh_token" if credential.refresh_token else "access_token"
                ),
            )
        finally:
            await client.aclose()

    def credential_from_token(
        self,
        token: Mapping[str, Any],
        *,
        previous: OAuthCredential | None = None,
    ) -> OAuthCredential:
        if not isinstance(token, Mapping):
            raise InvalidCredentialError(
                "OAuth token response must be a mapping.",
                provider=self.id,
                details={"recovery": "login"},
            )
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise InvalidCredentialError(
                "OAuth token response is missing access_token.",
                provider=self.id,
                details={"recovery": "login"},
            )
        refresh_token = token.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            refresh_token = previous.refresh_token if previous is not None else None
        token_type = token.get("token_type", "Bearer")
        if not isinstance(token_type, str) or not token_type.strip():
            token_type = "Bearer"
        expires_at = _expires_at_from_token(token)
        if expires_at is None and previous is not None:
            expires_at = previous.expires_at
        extra_headers = self.extra_headers_from_token(token, previous=previous) or (
            previous.extra_headers if previous is not None else {}
        )
        return OAuthCredential(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            token_type=token_type,
            provider=self.id,
            extra_headers=extra_headers,
        )

    def extra_headers_from_token(
        self,
        token: Mapping[str, Any],
        *,
        previous: OAuthCredential | None,
    ) -> Mapping[str, str]:
        del token, previous
        return {}

    def _new_client(
        self,
        *,
        token: Mapping[str, object] | None = None,
        redirect_uri: str | None = None,
    ):
        from authlib.integrations.httpx_client import (  # type: ignore[import-untyped]
            AsyncOAuth2Client,
        )

        return AsyncOAuth2Client(
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            redirect_uri=redirect_uri or self.config.redirect_uri,
            scope=" ".join(self.config.scopes) or None,
            token=token,
            token_endpoint_auth_method=self.config.token_endpoint_auth_method,
            code_challenge_method="S256",
        )

    def _require_client_id(self) -> None:
        if not self.config.client_id:
            raise OAuthProviderNotConfiguredError(
                "OAuth provider has no authorized client_id.",
                provider=self.id,
                details={"recovery": "configure_client"},
            )

    def _require_login_config(self, *, allow_default_redirect: bool = False) -> None:
        self._require_client_id()
        missing = [
            name
            for name in ("authorization_endpoint", "token_endpoint")
            if not getattr(self.config, name)
        ]
        if not allow_default_redirect and not self.config.redirect_uri:
            missing.append("redirect_uri")
        if missing:
            raise OAuthProviderNotConfiguredError(
                "OAuth provider login configuration is incomplete.",
                provider=self.id,
                details={
                    "missing": list(missing),
                    "recovery": "configure_client",
                },
            )

    def _require_refresh_config(self) -> None:
        self._require_client_id()
        if not self.config.token_endpoint:
            raise OAuthProviderNotConfiguredError(
                "OAuth provider has no token endpoint for refresh.",
                provider=self.id,
                details={"recovery": "configure_client"},
            )


class _LoopbackOAuthCallback:
    def __init__(
        self,
        *,
        expected_path: str,
        redirect_uri: str,
        response: asyncio.Future[str],
    ) -> None:
        self.expected_path = expected_path
        self.redirect_uri = redirect_uri
        self._response = response
        self._server: asyncio.Server | None = None

    @classmethod
    async def start(cls, configured_redirect_uri: str) -> "_LoopbackOAuthCallback":
        parsed = urlsplit(configured_redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise OAuthProviderNotConfiguredError(
                "OAuth login redirect_uri must be an HTTP loopback address.",
                details={
                    "redirect_uri": configured_redirect_uri,
                    "recovery": "configure_client",
                },
            )
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise OAuthProviderNotConfiguredError(
                "OAuth login redirect_uri must not include credentials, query, or fragment.",
                details={"recovery": "configure_client"},
            )
        path = parsed.path or "/callback"
        try:
            port = parsed.port if parsed.port is not None else 80
        except ValueError as error:
            raise OAuthProviderNotConfiguredError(
                "OAuth login redirect_uri has an invalid port.",
                details={"recovery": "configure_client"},
            ) from error
        response: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        instance = cls(expected_path=path, redirect_uri="", response=response)
        try:
            server = await asyncio.start_server(
                instance._handle_request,
                host="127.0.0.1",
                port=port,
            )
        except OSError as error:
            raise OAuthProviderNotConfiguredError(
                "OAuth login could not bind the configured loopback redirect.",
                details={
                    "cause": type(error).__name__,
                    "recovery": "configure_client",
                },
            ) from error
        socket = next(iter(server.sockets or ()), None)
        if socket is None:
            server.close()
            await server.wait_closed()
            raise OAuthProviderNotConfiguredError(
                "OAuth login callback listener did not expose a socket.",
                details={"recovery": "configure_client"},
            )
        actual_port = socket.getsockname()[1]
        host = parsed.hostname
        instance.redirect_uri = urlunsplit(
            (parsed.scheme, f"{host}:{actual_port}", path, "", "")
        )
        instance._server = server
        return instance

    async def wait(self) -> str:
        return await self._response

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if not self._response.done():
            self._response.cancel()

    async def _handle_request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        status = "400 Bad Request"
        body = b"OAuth callback was invalid."
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            request_line = request.split(b"\r\n", 1)[0].decode("ascii")
            method, target, _version = request_line.split(" ", 2)
            parsed_target = urlsplit(target)
            if method == "GET" and parsed_target.path == self.expected_path:
                status = "200 OK"
                body = b"Authentication complete. You can close this window."
                if not self._response.done():
                    self._response.set_result(f"{self.redirect_uri}?{parsed_target.query}")
        except (UnicodeError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        writer.write(
            f"HTTP/1.1 {status}\r\n".encode("ascii")
            + b"Content-Type: text/plain; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

def _expires_at_from_token(token: Mapping[str, Any]) -> float | int | None:
    expires_at = token.get("expires_at")
    if (
        not isinstance(expires_at, bool)
        and isinstance(expires_at, int | float)
        and expires_at > 0
    ):
        return expires_at
    expires_in = token.get("expires_in")
    if (
        not isinstance(expires_in, bool)
        and isinstance(expires_in, int | float)
        and expires_in > 0
    ):
        return time.time() + expires_in
    return None


def _oauth_token(credential: OAuthCredential) -> dict[str, object]:
    token: dict[str, object] = {
        "access_token": credential.access_token,
        "token_type": credential.token_type,
    }
    if credential.refresh_token is not None:
        token["refresh_token"] = credential.refresh_token
    if credential.expires_at is not None:
        token["expires_at"] = credential.expires_at
    return token


__all__ = ["AuthlibOAuthProvider", "OAuthClientConfig", "OAuthLoginSession"]
