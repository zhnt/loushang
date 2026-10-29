from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import threading

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.transcript import ProductTranscriptSession
from loushang.harness.transcript.source_reader import (
    TranscriptSourceError,
    TranscriptSourceReader,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_owned_session_factory import factory, new

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux admitted source reader")


async def source(tmp_path):
    state, root = tmp_path / "state/session-stores", tmp_path / "data/sessions"
    selected = factory(store_state_root=state)
    session = await new(selected, root)
    product = ProductTranscriptSession(lifecycle_session=session)
    first = await product.append_message(
        UserMessage(role="user", content="original", timestamp=1)
    )
    second = await product.append_message(
        UserMessage(role="user", content="follow-up", timestamp=2)
    )
    reader = TranscriptSourceReader(
        session_file=session.context.session_file,
        conversation_id="conversation-1",
        store_state_root=state,
    )
    return selected, session, product, reader, (first, second)


def test_live_writer_and_cold_reader_preserve_fixed_branch(tmp_path):
    async def scenario():
        owner, session, product, reader, ids = await source(tmp_path)
        before = await reader.read(ids)
        assert len(before.records) == 2 and before.ancestors_hashed == 2
        await product.append_message(
            UserMessage(role="user", content="new head", timestamp=3)
        )
        after = await reader.read(ids)
        assert (
            after.records == before.records
            and after.store_identity == before.store_identity
        )
        await session.dispose()
        await owner.close()
        await reader.aclose()
        cold = TranscriptSourceReader(
            session_file=reader.session_file,
            conversation_id=reader.conversation_id,
            store_state_root=reader.store_state_root,
        )
        try:
            assert (await cold.read(ids)).records == before.records
            with pytest.raises(TranscriptSourceError, match="not committed"):
                await cold.read(["runtime-event-id"])
        finally:
            await cold.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutation", ["unknown_envelope", "whitespace", "ancestor", "crlf"]
)
def test_digest_covers_original_bytes_and_ancestors(tmp_path, mutation):
    async def scenario():
        owner, session, _, reader, ids = await source(tmp_path)
        before = await reader.read(ids)
        await session.dispose()
        await owner.close()
        content = reader.session_file.read_bytes()
        lines = content.splitlines()
        if mutation == "unknown_envelope":
            entry = json.loads(lines[1])
            entry["futureEnvelope"] = {"x": 1}
            lines[1] = json.dumps(entry).encode()
        elif mutation == "whitespace":
            lines[1] += b" "
        elif mutation == "ancestor":
            lines[1] = lines[1].replace(b"original", b"changed!")
        separator = b"\r\n" if mutation == "crlf" else b"\n"
        reader.session_file.write_bytes(separator.join(lines) + separator)
        after = await reader.read(ids)
        assert before.records[-1].branch_digest != after.records[-1].branch_digest
        # A separate, direct calculation fixes the v1 wire digest algorithm.
        raw = reader.session_file.read_bytes().split(b"\n")[:-1]
        h = hashlib.sha256(b"loushang.transcript.branch/v1\0" + raw[0]).digest()
        for line in raw[1:]:
            h = hashlib.sha256(
                b"loushang.transcript.record/v1\0" + h + hashlib.sha256(line).digest()
            ).digest()
        assert after.records[-1].branch_digest == h.hex()
        await reader.aclose()

    asyncio.run(scenario())


def test_partial_tail_bare_cr_wrong_session_and_unknown_store(tmp_path):
    async def scenario():
        owner, session, _, reader, ids = await source(tmp_path)
        await session.dispose()
        await owner.close()
        content = reader.session_file.read_bytes()
        reader.session_file.write_bytes(content + b'{"recordId":"unfinished"')
        assert len((await reader.read(ids)).records) == 2
        with pytest.raises(TranscriptSourceError):
            await reader.read(["unfinished"])
        reader.session_file.write_bytes(content.replace(b"\n", b"\r"))
        with pytest.raises(TranscriptSourceError, match="LF"):
            await reader.read(ids)
        reader.session_file.write_bytes(content)
        wrong = TranscriptSourceReader(
            session_file=reader.session_file,
            conversation_id="wrong",
            store_state_root=reader.store_state_root,
        )
        with pytest.raises(TranscriptSourceError, match="conversation"):
            await wrong.read(ids)
        await wrong.aclose()
        await reader.aclose()
        absent = tmp_path / "absent"
        unknown = TranscriptSourceReader(
            session_file=absent / "sessions/a.jsonl",
            conversation_id="a",
            store_state_root=tmp_path / "unknown-state",
        )
        with pytest.raises((TranscriptSourceError, TranscriptWriterError)):
            await unknown.read()
        await unknown.aclose()
        assert not absent.exists() and not (tmp_path / "unknown-state").exists()

    asyncio.run(scenario())


def test_reader_cancel_settles_native_and_retains_cleanup_debt(tmp_path, monkeypatch):
    from loushang.harness.transcript import source_reader as module

    async def scenario():
        owner, session, _, reader, ids = await source(tmp_path)
        started, release = threading.Event(), threading.Event()
        original = module.RootedFileIO.read_bytes

        def blocked(io, path, **kwargs):
            if path == reader.session_file:
                started.set()
                assert release.wait(5)
            return original(io, path, **kwargs)

        monkeypatch.setattr(module.RootedFileIO, "read_bytes", blocked)
        task = asyncio.create_task(reader.read(ids))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        closing = asyncio.create_task(reader.aclose())
        await asyncio.sleep(0)
        assert not task.done() and not closing.done() and reader._owner is not None
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await closing
        assert reader._owner is None
        await session.dispose()
        await owner.close()

    asyncio.run(scenario())


def test_cleanup_failure_keeps_borrowed_owner_for_retry(tmp_path, monkeypatch):
    from loushang.harness.transcript import source_reader as module

    async def scenario():
        owner, session, _, reader, ids = await source(tmp_path)
        original = module._ReadOwner.close

        def fail_close(self):
            raise OSError("injected cleanup failure")

        monkeypatch.setattr(module._ReadOwner, "close", fail_close)
        with pytest.raises(OSError, match="injected"):
            await reader.read(ids)
        assert reader._owner is not None and reader._owner.admission.cleanup_pending
        with pytest.raises(TranscriptSourceError, match="cleanup pending"):
            await reader.read(ids)
        monkeypatch.setattr(module._ReadOwner, "close", original)
        await reader.aclose()
        assert reader._owner is None
        await session.dispose()
        await owner.close()

    asyncio.run(scenario())


def test_identity_binding_does_not_materialize_lazy_session_file(tmp_path):
    async def scenario():
        owner = factory(store_state_root=tmp_path / "state/session-stores")
        session = await new(owner, tmp_path / "data/sessions")
        reader = TranscriptSourceReader(
            session_file=session.context.session_file,
            conversation_id="conversation-1",
            store_state_root=tmp_path / "state/session-stores",
        )
        # Factories may eagerly materialize a header in some profiles; identity
        # inspection must also work for an absent configured Session file.
        lazy = TranscriptSourceReader(
            session_file=reader.session_file.with_name("lazy.jsonl"),
            conversation_id="expected-lazy",
            store_state_root=reader.store_state_root,
        )
        identity = await lazy.inspect_identity()
        assert identity.conversation_id == "expected-lazy"
        assert not lazy.session_file.exists()
        with pytest.raises(FileNotFoundError):
            await lazy.read(["not-yet-committed"])
        await lazy.aclose()
        await reader.aclose()
        await session.dispose()
        await owner.close()

    asyncio.run(scenario())
