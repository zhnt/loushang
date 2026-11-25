"""Session-owned bounded requests to an explicitly granted client directory."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from secrets import compare_digest, token_hex
from typing import Literal

from loushang.appserver.execution.resources import ClientResourceRequestV1, ResourceV1
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.foundation.json import JSONValue
from loushang.harness.artifacts import SessionBlobRef, SessionBlobStore

CLIENT_REFERENCE = "client-reference"
_TIMEOUT = 8.0


@dataclass(frozen=True, slots=True)
class ClientReference:
    name: str
    key_digest: str

    def descriptor(self) -> bytes:
        return json.dumps([self.name, self.key_digest], ensure_ascii=True, separators=(",", ":")).encode("ascii")

    @classmethod
    def load(cls, store: SessionBlobStore, blob: SessionBlobRef) -> ClientReference:
        name, digest = json.loads(store.read_bytes(blob))
        if type(name) is not str or type(digest) is not str:
            raise ValueError("invalid client directory metadata")
        return cls(name, digest)

    def require_key(self, key: str) -> None:
        if not compare_digest(key_digest(key), self.key_digest):
            raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)

    def resource(self, blob: SessionBlobRef) -> ResourceV1:
        return ResourceV1(blob.sha256, "directory", "client_reference", "", 0, self.name)


def key_digest(key: str) -> str:
    return sha256(key.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Pending:
    request: ClientResourceRequestV1
    future: asyncio.Future[str]


class ClientDirectoryOffline(Exception):
    pass


class ClientDirectoryBroker:
    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}

    async def request(
        self, resource_id: str, operation: Literal["list", "read"], path: str, offset: int,
    ) -> dict[str, JSONValue]:
        if resource_id in self._pending or len(self._pending) >= 8:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        request = ClientResourceRequestV1(token_hex(16), operation, path, offset)
        future = asyncio.get_running_loop().create_future()
        self._pending[resource_id] = _Pending(request, future)
        try:
            try:
                data = await asyncio.wait_for(future, _TIMEOUT)
            except TimeoutError as exc:
                raise ClientDirectoryOffline from exc
            return _result(request, data)
        finally:
            self._pending.pop(resource_id, None)

    def poll(self, resource_id: str) -> ClientResourceRequestV1 | None:
        pending = self._pending.get(resource_id)
        return pending.request if pending is not None and not pending.future.done() else None

    def complete(self, resource_id: str, request_id: str, data: str) -> None:
        pending = self._pending.get(resource_id)
        if pending is not None and pending.request.id == request_id and not pending.future.done():
            pending.future.set_result(data)

    def close(self) -> None:
        for pending in self._pending.values():
            pending.future.cancel()
        self._pending.clear()


def _result(request: ClientResourceRequestV1, data: str) -> dict[str, JSONValue]:
    with suppress(ValueError, TypeError, RecursionError):
        result = json.loads(data)
        if type(result) is dict:
            if request.operation == "list" and set(result) == {"entries", "truncated"}:
                names, truncated = result["entries"], result["truncated"]
                if (type(truncated) is bool and type(names) is list and len(names) <= 100
                        and all(type(name) is str and 0 < len(name) <= 256 and name not in {".", ".."}
                                and not any(char in name for char in "/\\\x00:") for name in names)):
                    return {"entries": names, "truncated": truncated}
            if request.operation == "read" and set(result) == {"text", "nextOffset"}:
                text, offset = result["text"], result["nextOffset"]
                if (type(text) is str and len(text.encode("utf-8")) <= 8192 and (
                    offset is None or type(offset) is int and request.offset < offset <= 1024 * 1024
                )):
                    return {"text": text, "nextOffset": offset}
    raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE)
