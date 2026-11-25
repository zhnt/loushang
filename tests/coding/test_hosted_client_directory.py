import asyncio
from types import SimpleNamespace

import pytest

from loushang.apphost.integrations import (
    _resource_client_reference as client_references,
)
from loushang.appserver.execution.model import ResourceRefV1
from loushang.appserver.execution.resources import SessionResourceQueryV1
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.coding.hosted.resources import HostedResourceAccess


def test_client_directory_is_scoped_and_pending_requests_settle(tmp_path, monkeypatch):
    records = []
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    access = HostedResourceAccess("session", sessions, lambda: records)
    key = "a" * 64
    ref, = access.exchange(SessionResourceQueryV1(
        "clientReference", name="shared folder", proxy_key=key,
    )).resources
    assert ref.source == "client_reference" and ref.kind == "directory"
    assert not access.associated()
    ref_input = ResourceRefV1(ref.id, ref.id)
    records.append(SimpleNamespace(metadata=access.input_metadata((ref_input,)), payload=None))
    assert access.associated() == (ref,)

    async def scenario():
        task = asyncio.create_task(access.read_client_directory(ref.id, "read", "hello.txt", 0))
        await asyncio.sleep(0)
        with pytest.raises(AppServiceError) as denied:
            access.exchange(SessionResourceQueryV1("proxyPoll", ref.id, proxy_key="b" * 64))
        assert denied.value.code is AppErrorCodeV1.PERMISSION_DENIED
        requested = access.exchange(SessionResourceQueryV1("proxyPoll", ref.id, proxy_key=key)).proxy_request
        assert requested is not None and requested.path == "hello.txt"
        access.exchange(SessionResourceQueryV1(
            "proxyComplete", ref.id, proxy_key=key, request_id="unknown", data='{"text":"bad","nextOffset":null}',
        ))
        assert not task.done()
        access.exchange(SessionResourceQueryV1(
            "proxyComplete", ref.id, proxy_key=key, request_id=requested.id, data='{"text":"witness","nextOffset":null}',
        ))
        assert await task == {"text": "witness", "nextOffset": None}

        pending = asyncio.create_task(access.read_client_directory(ref.id, "list", ".", 0))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert access.exchange(SessionResourceQueryV1("proxyPoll", ref.id, proxy_key=key)).proxy_request is None

        monkeypatch.setattr(client_references, "_TIMEOUT", 0.01)
        with pytest.raises(client_references.ClientDirectoryOffline):
            await access.read_client_directory(ref.id, "read", "hello.txt", 0)
        restored = HostedResourceAccess("session", sessions, lambda: records)
        assert restored.associated() == (ref,)

    asyncio.run(scenario())
