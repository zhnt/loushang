from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.lsp.documents import LspDocumentManager


class _ObservingClient:
    def __init__(self, uri: str) -> None:
        self.manager: LspDocumentManager | None = None
        self.runtime_id = 3
        self.uri = uri
        self.observed_versions: list[int] = []
        self.fail_next = False

    async def notify(self, method: str, params: object) -> None:
        del method, params
        assert self.manager is not None
        snapshot = self.manager.snapshot_for_uri(self.runtime_id, self.uri)
        assert snapshot is not None
        self.observed_versions.append(snapshot.version)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("notify failed")


def test_document_snapshot_is_visible_during_notify_and_rolls_back_on_failure(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        source = tmp_path / "main.py"
        source.touch()
        contents = {source.resolve(): "value = 1\n"}
        client = _ObservingClient(source.resolve().as_uri())
        manager = LspDocumentManager(
            workspace_root=tmp_path,
            read_text=lambda path: contents[path],
        )
        client.manager = manager
        runtime = SimpleNamespace(runtime_id=client.runtime_id, client=client)

        opened = await manager.ensure_document(runtime, source, language_id="python")
        assert opened.version == 1
        assert client.observed_versions == [1]

        contents[source.resolve()] = "value = 2\n"
        client.fail_next = True
        with pytest.raises(RuntimeError, match="notify failed"):
            await manager.ensure_document(runtime, source, language_id="python")
        assert client.observed_versions == [1, 2]
        assert manager.snapshot_for_uri(client.runtime_id, source.as_uri()) == opened

    asyncio.run(scenario())
