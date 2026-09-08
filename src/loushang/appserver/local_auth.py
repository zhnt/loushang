"""G16 mutual authentication and integrity, not encryption or endpoint discovery.

Authentication borrows an already admitted byte transport. Its caller retains
cleanup ownership on failure/cancellation; success returns the authenticated
stream for that same transport. No semantic client is constructed here.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from dataclasses import dataclass, field
from secrets import token_bytes

from .framing import (
    AppByteTransportV1,
    AppConnectionClosedError,
    AppConnectionEOFError,
    _SizedFramedStream,
    require_timeout,
)
from .protocol import APP_PROTOCOL_VERSION
from .protocol.codec import MAX_MESSAGE_BYTES
from .protocol.connection_profile import LOCAL_HELLO_V1, LOCAL_PROFILE_V1

_AUTH_FRAME_BYTES = 2048
_ENVELOPE_BYTES = 40
_MAX_SEQUENCE = (1 << 64) - 1
_CHANNEL_TOKEN = object()


class LocalAuthenticationError(AppConnectionClosedError):
    """One redacted failure for authentication or authenticated-frame faults."""


@dataclass(frozen=True, slots=True)
class LocalAuthenticationV1:
    """Material derived from one validated private connection record.

    record_digest is SHA-256 of its canonical public record, excluding the key.
    Construction alone is not file admission and grants no filesystem authority.
    """

    instance: str
    record_digest: bytes = field(repr=False)
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not _hex(self.instance, 32)
            or type(self.record_digest) is not bytes or len(self.record_digest) != 32
            or type(self.key) is not bytes or len(self.key) != 32
        ):
            raise ValueError("invalid local authentication material")


def _hex(value: object, length: int = 64) -> bool:
    return (
        type(value) is str and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LocalAuthenticationError()
        result[key] = value
    return result


def _decode(payload: bytes, fields: frozenset[str]) -> dict[str, str]:
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=_object)
    if (
        type(value) is not dict or set(value) != fields
        or any(type(item) is not str for item in value.values())
    ):
        raise LocalAuthenticationError()
    return value


def _encode(value: dict[str, str]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")


def _transcript(
    credentials: LocalAuthenticationV1, server_nonce: bytes, client_nonce: bytes
) -> bytes:
    return (
        LOCAL_PROFILE_V1.encode("ascii") + b"\0"
        + APP_PROTOCOL_VERSION.encode("ascii") + b"\0"
        + credentials.record_digest + server_nonce + client_nonce
    )


def _proof(key: bytes, role: bytes, transcript: bytes) -> bytes:
    return hmac.digest(key, role + b"\0" + transcript, "sha256")


def _auth_frames(
    transport: AppByteTransportV1, credentials: LocalAuthenticationV1, timeout: float
) -> _SizedFramedStream:
    if type(credentials) is not LocalAuthenticationV1:
        raise TypeError("invalid local authentication material")
    require_timeout(timeout)
    if timeout > 5:
        raise ValueError("local authentication timeout exceeds profile bound")
    return _SizedFramedStream(
        transport, max_payload=_AUTH_FRAME_BYTES, io_timeout=timeout
    )


async def authenticate_local_server(
    transport: AppByteTransportV1,
    credentials: LocalAuthenticationV1,
    *, timeout: float = 5.0,
) -> AuthenticatedLocalStreamV1:
    frames = _auth_frames(transport, credentials, timeout)
    try:
        async with asyncio.timeout(timeout):
            server_nonce = token_bytes(32)
            await frames.send(_encode({
                "profile": LOCAL_PROFILE_V1, "protocol": APP_PROTOCOL_VERSION,
                "instance": credentials.instance, "server_nonce": server_nonce.hex(),
            }))
            response = _decode(
                await frames.receive(), frozenset({"client_nonce", "proof"})
            )
            if not _hex(response["client_nonce"]) or not _hex(response["proof"]):
                raise LocalAuthenticationError()
            transcript = _transcript(
                credentials, server_nonce, bytes.fromhex(response["client_nonce"])
            )
            if not hmac.compare_digest(
                _proof(credentials.key, b"client", transcript),
                bytes.fromhex(response["proof"]),
            ):
                raise LocalAuthenticationError()
            await frames.send(_encode({
                "proof": _proof(credentials.key, b"server", transcript).hex()
            }))
            return _channel(transport, credentials, transcript, server=True)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise LocalAuthenticationError() from None


async def authenticate_local_client(
    transport: AppByteTransportV1,
    credentials: LocalAuthenticationV1,
    *, timeout: float = 5.0,
) -> AuthenticatedLocalStreamV1:
    frames = _auth_frames(transport, credentials, timeout)
    try:
        async with asyncio.timeout(timeout):
            challenge = _decode(await frames.receive(), frozenset({
                "profile", "protocol", "instance", "server_nonce"
            }))
            if (
                challenge["profile"] != LOCAL_PROFILE_V1
                or challenge["protocol"] != APP_PROTOCOL_VERSION
                or challenge["instance"] != credentials.instance
                or not _hex(challenge["server_nonce"])
            ):
                raise LocalAuthenticationError()
            client_nonce = token_bytes(32)
            transcript = _transcript(
                credentials, bytes.fromhex(challenge["server_nonce"]), client_nonce
            )
            await frames.send(_encode({
                "client_nonce": client_nonce.hex(),
                "proof": _proof(credentials.key, b"client", transcript).hex(),
            }))
            response = _decode(await frames.receive(), frozenset({"proof"}))
            if not _hex(response["proof"]) or not hmac.compare_digest(
                _proof(credentials.key, b"server", transcript),
                bytes.fromhex(response["proof"]),
            ):
                raise LocalAuthenticationError()
            return _channel(transport, credentials, transcript, server=False)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise LocalAuthenticationError() from None


def _channel(
    transport: AppByteTransportV1,
    credentials: LocalAuthenticationV1,
    transcript: bytes,
    *, server: bool,
) -> AuthenticatedLocalStreamV1:
    c2s = _proof(credentials.key, b"c2s", transcript)
    s2c = _proof(credentials.key, b"s2c", transcript)
    return AuthenticatedLocalStreamV1(
        transport, receive_key=c2s if server else s2c,
        send_key=s2c if server else c2s, _token=_CHANNEL_TOKEN,
    )


class AuthenticatedLocalStreamV1:
    """Integrity-protected frames; a failed/uncertain frame fences this channel."""

    def __init__(
        self, transport: AppByteTransportV1, *, receive_key: bytes, send_key: bytes,
        _token: object,
    ) -> None:
        if _token is not _CHANNEL_TOKEN:
            raise TypeError("authenticated streams require a completed handshake")
        self._frames = _SizedFramedStream(
            transport, max_payload=MAX_MESSAGE_BYTES + _ENVELOPE_BYTES
        )
        self._receive_key = receive_key
        self._send_key = send_key
        self._receive_sequence = 1
        self._send_sequence = 1
        self._writer = asyncio.Lock()
        self._receiving = False
        self._closed = False

    async def receive(self) -> bytes:
        if self._closed or self._receiving:
            self._closed = True
            raise LocalAuthenticationError()
        self._receiving = True
        try:
            envelope = await self._frames.receive()
            if self._closed or len(envelope) <= _ENVELOPE_BYTES:
                raise LocalAuthenticationError()
            sequence, tag, payload = envelope[:8], envelope[8:40], envelope[40:]
            if (
                int.from_bytes(sequence, "big") != self._receive_sequence
                or self._receive_sequence > _MAX_SEQUENCE
                or not hmac.compare_digest(
                    hmac.digest(self._receive_key, sequence + payload, "sha256"), tag
                )
            ):
                raise LocalAuthenticationError()
            self._receive_sequence += 1
            return payload
        except (asyncio.CancelledError, AppConnectionEOFError):
            self._closed = True
            raise
        except Exception:
            self._closed = True
            raise LocalAuthenticationError() from None
        finally:
            self._receiving = False

    async def send(self, payload: bytes) -> None:
        try:
            if type(payload) is not bytes or not 1 <= len(payload) <= MAX_MESSAGE_BYTES:
                raise LocalAuthenticationError()
            async with asyncio.timeout(10.0):
                async with self._writer:
                    if self._closed or self._send_sequence > _MAX_SEQUENCE:
                        raise LocalAuthenticationError()
                    sequence = self._send_sequence.to_bytes(8, "big")
                    tag = hmac.digest(self._send_key, sequence + payload, "sha256")
                    self._send_sequence += 1
                    await self._frames.send(sequence + tag + payload)
        except asyncio.CancelledError:
            self._closed = True
            raise
        except Exception:
            self._closed = True
            raise LocalAuthenticationError() from None

    async def close(self) -> None:
        self._closed = True
        await self._frames.close()


__all__ = [
    "AuthenticatedLocalStreamV1", "LOCAL_HELLO_V1", "LOCAL_PROFILE_V1",
    "LocalAuthenticationError", "LocalAuthenticationV1",
    "authenticate_local_client", "authenticate_local_server",
]
