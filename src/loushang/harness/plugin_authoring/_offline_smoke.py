"""Disposable Product state and offline model transport for authoring checks."""

from __future__ import annotations

import os
import stat
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.protocol import ProviderRequest
from loushang.harness.resources.packages._file_consumption import (
    borrowed_binary_stream,
    closing_descriptor,
)


def capture_authoring_input(
    path: Path,
    *,
    maximum_bytes: int,
    invalid_input: str,
    changed_before_read: str,
    changed_during_read: str,
    require_visible_source: bool = False,
) -> bytes:
    """Capture one bounded regular file before opening a disposable workspace."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum_bytes:
        raise ValueError(invalid_input)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with (
        closing_descriptor(os.open(path, flags)) as descriptor,
        borrowed_binary_stream(descriptor, "rb") as stream,
    ):
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ) != (before.st_dev, before.st_ino, before.st_size):
            raise ValueError(changed_before_read)
        body = stream.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
    if (
        not 0 < len(body) <= maximum_bytes
        or _file_revision(opened) != _file_revision(after)
    ):
        raise ValueError(changed_during_read)
    if require_visible_source and (
        len(body) != before.st_size or path.stat().st_ino != before.st_ino
    ):
        raise ValueError(changed_during_read)
    return body


def _file_revision(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


@contextmanager
def hold_authoring_home(path: Path) -> Iterator[None]:
    previous = os.environ.get("LOUSHANG_HOME")
    path.mkdir(mode=0o700)
    os.environ["LOUSHANG_HOME"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LOUSHANG_HOME", None)
        else:
            os.environ["LOUSHANG_HOME"] = previous


class OfflineAuthoringAdapter:
    """Prepare real model input and hand it to an in-process response script."""

    def __init__(self, api: str) -> None:
        self.api = api

    @contextmanager
    def registered(self) -> Iterator[None]:
        registry = get_default_api_registry()
        registry.register_api_adapter(self, source_id=self.api)
        try:
            yield
        finally:
            registry.unregister_api_adapters(self.api)

    def model(self, *, model_id: str, name: str, endpoint: str) -> Model:
        return Model(
            id=model_id,
            name=name,
            provider="test",
            endpoint=endpoint,
            api=self.api,
            base_url="https://provider.invalid/v1",
            auth=Auth(kind="none"),
            capabilities=Capabilities(
                input=("text",),
                output=("text",),
                context_window=128000,
                stream=True,
                tool_use=True,
            ),
        )

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": request.context.system_prompt,
                "messages": [
                    serialize_message(item) for item in request.context.messages
                ],
                "model": request.model.id,
            },
        )

    def invoke_prepared_raw(
        self, request: ProviderRequest, prepared: PreparedModelRequest
    ) -> AsyncIterator[RawPart]:
        raise NotImplementedError

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        prepared = self.prepare_request(request)
        async for part in self.invoke_prepared_raw(request, prepared):
            yield part
