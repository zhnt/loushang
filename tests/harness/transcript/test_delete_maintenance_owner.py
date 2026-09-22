import asyncio
import sys
from pathlib import Path

import pytest

from loushang.harness.transcript import delete_agent_transcript_jsonl
from loushang.harness.transcript.product_session import ProductTranscriptSession
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_owned_session_factory import factory, new
from .test_writer_images import message


@pytest.mark.skipif(sys.platform != "linux", reason="Linux shared writer admission")
@pytest.mark.parametrize("entry", [delete_agent_transcript_jsonl, ProductTranscriptSession.delete_session])
def test_unowned_delete_rejects_before_any_path_access(monkeypatch, entry):
    monkeypatch.setattr(Path, "expanduser", lambda *_: pytest.fail("unowned path access"))
    with pytest.raises(ValueError, match="retained maintenance_owner"):
        asyncio.run(entry("missing.jsonl"))


@pytest.mark.parametrize("entry", [delete_agent_transcript_jsonl, ProductTranscriptSession.delete_session])
@pytest.mark.parametrize("failure", [False, True])
def test_public_delete_delegates_to_original_retained_owner(entry, failure, monkeypatch):
    calls = []
    error = OSError("cleanup pending")

    class Owner:
        async def delete_transcript(self, path, *, current_session_file):
            calls.append((path, current_session_file))
            if failure:
                raise error
            return True

    monkeypatch.setattr(Path, "expanduser", lambda *_: pytest.fail("facade must not access paths"))
    operation = entry("session.jsonl", current_session_file="active.jsonl", maintenance_owner=Owner())
    if failure:
        with pytest.raises(OSError) as caught:
            asyncio.run(operation)
        assert caught.value is error
    else:
        assert asyncio.run(operation) is True
    assert calls == [("session.jsonl", "active.jsonl")]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux shared writer admission")
@pytest.mark.parametrize("entry", [delete_agent_transcript_jsonl, ProductTranscriptSession.delete_session])
def test_public_delete_obeys_live_writer_and_preserves_recoverable_blobs(tmp_path, entry):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        writer, maintenance = factory(), factory()
        session = await new(writer, root)
        try:
            await ProductTranscriptSession(lifecycle_session=session).append_message(message())
            path = session.context.session_file
            assets = tmp_path / "session-assets" / session.context.header.conversation_id
            before = {item.relative_to(assets): item.read_bytes() for item in assets.rglob("*") if item.is_file()}
            assert before
            with pytest.raises(TranscriptWriterError, match="busy"):
                await entry(path, maintenance_owner=maintenance)
            assert path.is_file()
            await session.dispose()
            assert await entry(path, maintenance_owner=maintenance)
            assert not path.exists()
            assert before == {item.relative_to(assets): item.read_bytes() for item in assets.rglob("*") if item.is_file()}
        finally:
            await session.dispose()
            await writer.close()
            await maintenance.close()

    asyncio.run(scenario())
