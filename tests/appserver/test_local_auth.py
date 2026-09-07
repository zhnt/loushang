from __future__ import annotations

import asyncio
import hmac
import json
from dataclasses import replace

import pytest

from loushang.appserver.framing import (
    AppConnectionClosedError,
    AppConnectionEOFError,
    AppFramedStreamV1,
)
from loushang.appserver.local_auth import (
    LocalAuthenticationError,
    LocalAuthenticationV1,
    authenticate_local_client,
    authenticate_local_server,
)
from loushang.appserver.protocol import InvalidAppMessageError
from loushang.appserver.protocol.codec import MAX_MESSAGE_BYTES

from .test_connection import _pair


def _credentials() -> LocalAuthenticationV1:
    return LocalAuthenticationV1("a" * 32, b"d" * 32, b"0123456789abcdef0123456789abcdef")


async def _authenticated_pair():
    left, right = _pair()
    credentials = _credentials()
    client, server = await asyncio.gather(
        authenticate_local_client(left, credentials, timeout=0.2),
        authenticate_local_server(right, credentials, timeout=0.2),
    )
    return client, server, left, right


def test_G16_LOCAL_AUTH_mutual_proof_and_bidirectional_frames() -> None:
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        await client.send(b"from client")
        assert await server.receive() == b"from client"
        await server.send(b"from server")
        assert await client.receive() == b"from server"
        assert _credentials().key.hex() not in repr(_credentials())
        assert _credentials().key.decode() not in repr(_credentials())
        await asyncio.gather(client.close(), server.close())
        assert left.closed and right.closed

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("changed", ["key", "record_digest", "instance"])
def test_G16_LOCAL_AUTH_wrong_material_cannot_admit_a_channel(changed: str) -> None:
    async def scenario() -> None:
        left, right = _pair()
        credentials = _credentials()
        wrong = replace(credentials, **{
            changed: "b" * 32 if changed == "instance" else b"x" * 32
        })
        results = await asyncio.gather(
            authenticate_local_client(left, wrong, timeout=0.01),
            authenticate_local_server(right, credentials, timeout=0.01),
            return_exceptions=True,
        )
        assert all(isinstance(result, LocalAuthenticationError) for result in results)
        assert all(str(result) == "service_closed" for result in results)
        await asyncio.gather(left.close(), right.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_BOUNDS_local_envelope_does_not_shrink_or_expand_semantic_limit() -> None:
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        # Use efficient reads for this maximum-size case, not the fragmentation
        # helper's intentionally tiny seven-byte reads.
        right.read = right.reader.read
        payload = b"x" * MAX_MESSAGE_BYTES
        await client.send(payload)
        assert await server.receive() == payload
        with pytest.raises(AppConnectionClosedError):
            await client.send(payload + b"x")
        await asyncio.gather(client.close(), server.close())
        legacy = AppFramedStreamV1(left)
        with pytest.raises(InvalidAppMessageError):
            await legacy.send(payload + b"x")

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_LOCAL_AUTH_idle_handshake_has_a_total_deadline() -> None:
    async def scenario() -> None:
        left, right = _pair()
        with pytest.raises(LocalAuthenticationError):
            await authenticate_local_client(left, _credentials(), timeout=0.01)
        await asyncio.gather(left.close(), right.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def _capture(pipe, *, forward=True):
    recorded = []
    original = pipe.write

    async def write(data):
        recorded.append(data)
        if forward:
            await original(data)

    pipe.write = write
    return recorded


def _body(frame):
    assert int.from_bytes(frame[:4], "big") == len(frame) - 4
    return frame[4:]


def test_G16_LOCAL_AUTH_transcript_roles_and_envelope_match_independent_vectors(
    monkeypatch,
) -> None:
    import loushang.appserver.local_auth as module

    async def scenario() -> None:
        left, right = _pair()
        client_writes, server_writes = _capture(left), _capture(right)
        nonces = iter((b"s" * 32, b"c" * 32))
        monkeypatch.setattr(module, "token_bytes", lambda size: next(nonces))
        credentials = _credentials()
        client, server = await asyncio.gather(
            authenticate_local_client(left, credentials),
            authenticate_local_server(right, credentials),
        )
        transcript = (
            b"local-detachable/v1\0loushang.app/v1\0"
            + b"d" * 32 + b"s" * 32 + b"c" * 32
        )

        def derive(role):
            return hmac.new(credentials.key, role + b"\0" + transcript, "sha256").digest()

        assert json.loads(_body(server_writes[0])) == {
            "profile": "local-detachable/v1", "protocol": "loushang.app/v1",
            "instance": "a" * 32, "server_nonce": (b"s" * 32).hex(),
        }
        assert json.loads(_body(client_writes[0])) == {
            "client_nonce": (b"c" * 32).hex(), "proof": derive(b"client").hex(),
        }
        assert json.loads(_body(server_writes[1])) == {
            "proof": derive(b"server").hex()
        }
        await client.send(b"payload")
        sequence = (1).to_bytes(8, "big")
        tag = hmac.new(derive(b"c2s"), sequence + b"payload", "sha256").digest()
        assert _body(client_writes[-1]) == sequence + tag + b"payload"
        assert await server.receive() == b"payload"
        for frame in (*client_writes, *server_writes):
            assert credentials.key not in frame
            assert credentials.key.hex().encode() not in frame
        await asyncio.gather(client.close(), server.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("field,value", [
    ("profile", "foreground-stdio/v1"),
    ("protocol", "loushang.app/v0"),
    ("instance", "b" * 32),
    ("server_nonce", "A" * 64),
    ("server_nonce", "0" * 63),
    ("server_nonce", True),
    ("extra", "not allowed"),
])
def test_G16_LOCAL_AUTH_challenge_is_a_closed_exact_profile(field, value) -> None:
    async def scenario() -> None:
        left, right = _pair()
        challenge = {
            "profile": "local-detachable/v1", "protocol": "loushang.app/v1",
            "instance": "a" * 32, "server_nonce": "0" * 64,
        }
        challenge[field] = value
        await AppFramedStreamV1(right).send(json.dumps(challenge).encode())
        with pytest.raises(LocalAuthenticationError):
            await authenticate_local_client(left, _credentials())
        assert not right.reader._buffer
        await asyncio.gather(left.close(), right.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("payload", [
    b'{"proof":"a","proof":"b"}', b'[]', b'null', b'{', b'\xff',
    b'{"proof":NaN}', b'{"proof":42}',
])
def test_G16_LOCAL_AUTH_rejects_nonobjects_duplicate_keys_and_malformed_json(payload):
    async def scenario() -> None:
        left, right = _pair()
        frames = AppFramedStreamV1(left)
        authenticating = asyncio.create_task(authenticate_local_server(right, _credentials()))
        await frames.receive()
        await frames.send(payload)
        with pytest.raises(LocalAuthenticationError) as failure:
            await authenticating
        assert str(failure.value) == "service_closed"
        await asyncio.gather(left.close(), right.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("length", [0, 2049, (1 << 32) - 1])
def test_G16_BOUNDS_handshake_rejects_length_before_requesting_body(length) -> None:
    async def scenario() -> None:
        left, right = _pair()
        sizes = []
        original = left.read

        async def read(size):
            sizes.append(size)
            return await original(size)

        left.read = read
        left.reader.feed_data(length.to_bytes(4, "big"))
        with pytest.raises(LocalAuthenticationError):
            await authenticate_local_client(left, _credentials())
        assert sizes == [1, 3]
        await asyncio.gather(left.close(), right.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_LOCAL_AUTH_client_rejects_reflected_client_proof() -> None:
    async def scenario() -> None:
        left, right = _pair()
        frames = AppFramedStreamV1(right)
        client = asyncio.create_task(authenticate_local_client(left, _credentials()))
        await frames.send(json.dumps({
            "profile": "local-detachable/v1", "protocol": "loushang.app/v1",
            "instance": "a" * 32, "server_nonce": "0" * 64,
        }).encode())
        response = json.loads(await frames.receive())
        await frames.send(json.dumps({"proof": response["proof"]}).encode())
        with pytest.raises(LocalAuthenticationError):
            await client
        await asyncio.gather(left.close(), right.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_LOCAL_AUTH_captured_client_proof_cannot_replay_on_fresh_challenge():
    async def scenario() -> None:
        left, right = _pair()
        writes = _capture(left)
        client, server = await asyncio.gather(
            authenticate_local_client(left, _credentials()),
            authenticate_local_server(right, _credentials()),
        )
        proof = _body(writes[0])
        await asyncio.gather(client.close(), server.close())
        left2, right2 = _pair()
        frames = AppFramedStreamV1(left2)
        authenticating = asyncio.create_task(authenticate_local_server(right2, _credentials()))
        await frames.receive()
        await frames.send(proof)
        with pytest.raises(LocalAuthenticationError):
            await authenticating
        await asyncio.gather(left2.close(), right2.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("fault", ["sequence", "tag", "payload", "direction"])
def test_G16_PROFILE_tampered_or_reflected_frame_fences_channel(fault):
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        writes = _capture(right if fault == "direction" else left, forward=False)
        await (server if fault == "direction" else client).send(b"protected")
        frame = bytearray(writes[0])
        if fault != "direction":
            index = {"sequence": 11, "tag": 12, "payload": 44}[fault]
            frame[index] ^= 1
        right.reader.feed_data(bytes(frame))
        with pytest.raises(LocalAuthenticationError):
            await server.receive()
        # Even a subsequent valid message cannot revive an uncertain stream.
        right.reader.feed_data(writes[0])
        with pytest.raises(LocalAuthenticationError):
            await server.receive()
        with pytest.raises(LocalAuthenticationError):
            await server.send(b"must not continue")
        await asyncio.gather(client.close(), server.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("fresh_channel", [False, True])
def test_G16_PROFILE_frame_replay_fails_within_and_across_connections(fresh_channel):
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        writes = _capture(left)
        await client.send(b"once")
        assert await server.receive() == b"once"
        replay = writes[0]
        if fresh_channel:
            await asyncio.gather(client.close(), server.close())
            client, server, left, right = await _authenticated_pair()
        right.reader.feed_data(replay)
        with pytest.raises(LocalAuthenticationError):
            await server.receive()
        await asyncio.gather(client.close(), server.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_PROFILE_concurrent_writers_serialize_sequence_and_bytes() -> None:
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        writes = _capture(left)
        await asyncio.gather(*(client.send(str(index).encode()) for index in range(32)))
        assert [int.from_bytes(_body(frame)[:8], "big") for frame in writes] == list(range(1, 33))
        assert [await server.receive() for _ in range(32)] == [
            str(index).encode() for index in range(32)
        ]
        await asyncio.gather(client.close(), server.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_PROFILE_sequence_exhaustion_never_wraps() -> None:
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        maximum = (1 << 64) - 1
        client._send_sequence = server._receive_sequence = maximum
        await client.send(b"last")
        assert await server.receive() == b"last"
        with pytest.raises(LocalAuthenticationError):
            await client.send(b"overflow")
        await asyncio.gather(client.close(), server.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_PROFILE_uncertain_write_cannot_reuse_channel_or_sequence() -> None:
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        original = left.write

        async def partial_failure(data):
            await original(data)
            raise OSError("private endpoint failure")

        left.write = partial_failure
        with pytest.raises(LocalAuthenticationError) as failed:
            await client.send(b"unknown delivery")
        assert str(failed.value) == "service_closed"
        assert await server.receive() == b"unknown delivery"
        with pytest.raises(LocalAuthenticationError):
            await client.send(b"must not replay")
        await asyncio.gather(client.close(), server.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_PROFILE_cancelled_partial_read_fences_channel() -> None:
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        waiting = asyncio.Event()
        original = right.read

        async def read(size):
            if not right.reader._buffer:
                waiting.set()
            return await original(size)

        right.read = read
        right.reader.feed_data(b"\0")
        receiving = asyncio.create_task(server.receive())
        await waiting.wait()
        receiving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await receiving
        with pytest.raises(LocalAuthenticationError):
            await server.receive()
        await asyncio.gather(client.close(), server.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_BOUNDS_authenticated_frame_rejects_oversize_before_body_read() -> None:
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        sizes = []
        original = right.read

        async def read(size):
            sizes.append(size)
            return await original(size)

        right.read = read
        right.reader.feed_data((MAX_MESSAGE_BYTES + 41).to_bytes(4, "big"))
        with pytest.raises(LocalAuthenticationError):
            await server.receive()
        assert sizes == [1, 3]
        await asyncio.gather(client.close(), server.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("field,value", [
    ("key", b"x" * 31), ("key", bytearray(32)),
    ("record_digest", b"x" * 33), ("instance", "A" * 32),
    ("instance", "a" * 31), ("instance", True),
])
def test_G16_LOCAL_AUTH_material_has_exact_types_and_sizes(field, value) -> None:
    with pytest.raises(ValueError, match="^invalid local authentication material$"):
        replace(_credentials(), **{field: value})


@pytest.mark.parametrize("timeout", [True, 0, -1, 5.01, float("inf"), float("nan")])
def test_G16_BOUNDS_handshake_cannot_expand_profile_timeout(timeout) -> None:
    async def scenario() -> None:
        left, right = _pair()
        with pytest.raises(ValueError):
            await authenticate_local_server(right, _credentials(), timeout=timeout)
        assert not left.reader._buffer
        await asyncio.gather(left.close(), right.close())

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_PROFILE_clean_eof_is_distinct_from_bad_authenticated_frame() -> None:
    async def scenario() -> None:
        client, server, left, right = await _authenticated_pair()
        await client.close()
        with pytest.raises(AppConnectionEOFError):
            await server.receive()
        with pytest.raises(LocalAuthenticationError):
            await server.receive()
        await server.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))
