from __future__ import annotations

import asyncio
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.conversation import ConversationKey
from loushang.harness.transcript import (
    AgentTranscriptFileLayout,
    AgentTranscriptLifecycle,
    AgentTranscriptProfile,
    AgentTranscriptRuntimeBinding,
    create_agent_transcript_file_store,
    load_agent_transcript_file,
    write_agent_transcript_export,
)
from loushang.harness.transcript.writer_lease import (
    TranscriptWriterError,
    TranscriptWriterLease,
)

from .test_lifecycle import _header, _record

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux writer")


class Binding:
    def __init__(self) -> None:
        self.binds = 0
        self.disposals = 0
        self.inputs = []
        self.bind_entered = asyncio.Event()
        self.bind_release = asyncio.Event()
        self.bind_release.set()
        self.dispose_entered = asyncio.Event()
        self.dispose_release = asyncio.Event()
        self.dispose_release.set()
        self.fail_dispose = False
        self.fail_bind = False
        self.wrong_key = False

    async def bind(self, context, value):
        self.binds += 1
        self.inputs.append(value)
        self.bind_entered.set()
        await self.bind_release.wait()
        if self.fail_bind:
            raise RuntimeError("binding failed")
        layout = AgentTranscriptFileLayout(context.session_dir)
        key = layout.key(context.header.conversation_id)
        layout.bind_create_path(key, context.session_file)
        return AgentTranscriptRuntimeBinding(
            store=create_agent_transcript_file_store(layout),
            key=ConversationKey("wrong", key.conversation_id) if self.wrong_key else key,
            profile=AgentTranscriptProfile.default(),
            product_binding=value,
            dispose=self.dispose,
        )

    async def dispose(self):
        self.disposals += 1
        self.dispose_entered.set()
        await self.dispose_release.wait()
        if self.fail_dispose:
            self.fail_dispose = False
            raise RuntimeError("retry cleanup")


def setup(root, binding):
    lifecycle = AgentTranscriptLifecycle(bind_runtime=binding.bind)
    header = _header()
    context = lifecycle.new_context(
        session_dir=root, cwd="/workspace", persist=True, header=header,
        session_file=lifecycle.default_jsonl_session_file(root, header),
    )
    writer = TranscriptWriterLease(root, "coding", header.conversation_id)
    writer.acquire()
    return lifecycle, context, writer


def assert_busy(root):
    other = TranscriptWriterLease(root, "coding", _header().conversation_id)
    try:
        with pytest.raises(TranscriptWriterError, match="busy"):
            other.acquire()
    finally:
        other.close()


def assert_available(root):
    other = TranscriptWriterLease(root, "coding", _header().conversation_id)
    try:
        other.acquire()
    finally:
        other.close()


def test_create_restore_and_frozen_claim(tmp_path: Path):
    async def scenario():
        binding = Binding()
        lifecycle, context, writer = setup(tmp_path, binding)
        value = {"options": ["original"]}
        records = [_record("first")]
        owner = lifecycle.prepare_writer(
            context, value, writer=writer, product_id="coding", records=records,
        )
        assert writer.claimed_owner is owner
        value["options"].append("changed")
        records.clear()
        with pytest.raises(TranscriptWriterError, match="closed"):
            lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        with pytest.raises(TranscriptWriterError, match="busy"):
            writer.close()
        one, two = await asyncio.gather(owner.create(), owner.create())
        assert one is two and binding.binds == 1
        assert binding.inputs == [{"options": ["original"]}]
        assert [r.record_id for r in one.transcript.records] == ["first"]
        assert_busy(tmp_path)
        await owner.dispose()
        assert not owner.cleanup_pending and binding.disposals == 1
        assert_available(tmp_path)

        writer2 = TranscriptWriterLease(tmp_path, "coding", context.header.conversation_id)
        writer2.acquire()
        restored = lifecycle.prepare_writer(context, {}, writer=writer2, product_id="coding")
        session = await restored.restore()
        assert [r.record_id for r in session.transcript.records] == ["first"]
        with pytest.raises(TranscriptWriterError, match="conflict"):
            await restored.create()
        await session.dispose()
        assert not restored.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["path", "root", "product", "conversation", "persist"])
def test_invalid_preparation_does_not_claim(tmp_path: Path, change):
    binding = Binding()
    lifecycle, context, writer = setup(tmp_path, binding)
    kwargs = {"product_id": "coding"}
    if change == "path":
        context = replace(context, session_file=tmp_path.parent / "outside.jsonl")
    elif change == "root":
        context = replace(context, session_dir=tmp_path / "other", session_file=tmp_path / "other" / "one.jsonl")
    elif change == "product":
        kwargs["product_id"] = "work"
    elif change == "conversation":
        context = replace(context, header=_header("another"))
    else:
        context = replace(context, persist=False)
    try:
        with pytest.raises(TranscriptWriterError):
            lifecycle.prepare_writer(context, {}, writer=writer, **kwargs)
        assert writer.claimed_owner is None and binding.binds == 0
    finally:
        writer.close()


def test_cancelled_create_rejoins_original_construction(tmp_path: Path):
    async def scenario():
        binding = Binding()
        binding.bind_release.clear()
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        waiter = asyncio.create_task(owner.create())
        await asyncio.wait_for(binding.bind_entered.wait(), 5)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert_busy(tmp_path)
        binding.bind_release.set()
        session = await owner.create()
        assert binding.binds == 1
        await session.dispose()
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_dispose_during_construction_fences_late_delivery(tmp_path: Path):
    async def scenario():
        binding = Binding()
        binding.bind_release.clear()
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        waiter = asyncio.create_task(owner.create())
        await asyncio.wait_for(binding.bind_entered.wait(), 5)
        closing = asyncio.create_task(owner.dispose())
        await asyncio.sleep(0)
        assert owner.closing and not closing.done()
        assert_busy(tmp_path)
        binding.bind_release.set()
        with pytest.raises(TranscriptWriterError, match="closed"):
            await waiter
        await closing
        assert binding.disposals == 1 and not owner.cleanup_pending
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_graph_retains_writer_and_cleanup_retry_survives_cancellation(tmp_path: Path):
    async def scenario():
        binding = Binding()
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        session = await owner.create()
        session._begin_graph_construction()
        session._commit_graph_ownership()
        await owner.dispose()
        assert not owner.closing and binding.disposals == 0
        assert_busy(tmp_path)
        binding.fail_dispose = True
        with pytest.raises(RuntimeError, match="retry cleanup"):
            await session._dispose_graph_owned()
        assert_busy(tmp_path)
        assert owner.cleanup_pending
        binding.dispose_entered.clear()
        binding.dispose_release.clear()
        closing = asyncio.create_task(session._dispose_graph_owned())
        await asyncio.wait_for(binding.dispose_entered.wait(), 5)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert_busy(tmp_path)
        rejoin = asyncio.create_task(session._dispose_graph_owned())
        await asyncio.sleep(0)
        assert not rejoin.done() and binding.disposals == 2
        binding.dispose_release.set()
        await rejoin
        assert session.ownership_state == "disposed"
        assert not owner.cleanup_pending and binding.disposals == 2
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_closing_root_cannot_transfer_to_graph(tmp_path: Path):
    async def scenario():
        binding = Binding()
        binding.dispose_release.clear()
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        session = await owner.create()
        closing = asyncio.create_task(session.dispose())
        await asyncio.wait_for(binding.dispose_entered.wait(), 5)
        with pytest.raises(RuntimeError, match="not root-owned"):
            session._begin_graph_construction()
        binding.dispose_release.set()
        await closing
    asyncio.run(scenario())


def test_stale_restore_header_preserves_history_and_releases_on_dispose(tmp_path: Path):
    async def scenario():
        binding = Binding()
        lifecycle, context, writer = setup(tmp_path, binding)
        changed = replace(context.header, metadata={"cwd": "/changed"})
        write_agent_transcript_export(context.session_file, changed, [_record("history")])
        before = context.session_file.read_bytes()
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        with pytest.raises(TranscriptWriterError, match="conflict"):
            await owner.restore()
        assert binding.binds == 0
        assert_busy(tmp_path)
        await owner.dispose()
        assert_available(tmp_path)
        assert context.session_file.read_bytes() == before
        assert load_agent_transcript_file(context.session_file)[0] == changed
    asyncio.run(scenario())


def test_failed_returned_binding_is_retained_and_disposed_once(tmp_path: Path):
    async def scenario():
        binding = Binding()
        binding.wrong_key = True
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        with pytest.raises(TranscriptWriterError, match="conflict"):
            await owner.create()
        assert_busy(tmp_path)
        await asyncio.gather(owner.dispose(), owner.dispose())
        assert binding.disposals == 1 and not owner.cleanup_pending
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_unreturned_binding_stays_unknown(tmp_path: Path):
    async def scenario():
        binding = Binding()
        binding.fail_bind = True
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        with pytest.raises(RuntimeError, match="binding failed"):
            await owner.create()
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            await owner.dispose()
        assert owner.cleanup_pending and binding.disposals == 0
        assert_busy(tmp_path)
        # Test-only: this injected binder has no native effects or resources.
        # Production cannot infer that from the generic exception.
        writer._close_claimed(owner)
    asyncio.run(scenario())


def test_loaded_header_is_rechecked_without_rewriting_history(tmp_path: Path):
    async def scenario():
        binding = Binding()
        lifecycle, context, writer = setup(tmp_path, binding)
        changed = replace(context.header, metadata={"cwd": "/changed"})
        write_agent_transcript_export(context.session_file, changed, [_record("history")])
        before = context.session_file.read_bytes()
        # Simulate a stale first read; the real Store still loads the disk header.
        lifecycle._header_loader = lambda _: context.header
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        with pytest.raises(TranscriptWriterError, match="conflict"):
            await owner.restore()
        assert binding.binds == 1 and binding.disposals == 0
        assert_busy(tmp_path)
        await owner.dispose()
        assert binding.disposals == 1 and not owner.cleanup_pending
        assert context.session_file.read_bytes() == before
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_private_runtime_task_cancel_keeps_writer_unknown(tmp_path: Path):
    async def scenario():
        binding = Binding()
        binding.dispose_release.clear()
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        session = await owner.create()
        closing = asyncio.create_task(session.dispose())
        await asyncio.wait_for(binding.dispose_entered.wait(), 5)
        owner._runtime_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert owner.cleanup_pending and session.ownership_state == "root_owned"
        assert_busy(tmp_path)
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            await session.dispose()
        assert binding.disposals == 1
        # This test disposer owns no external effects; production cannot infer it.
        writer._close_claimed(owner)
    asyncio.run(scenario())


def test_private_close_cancel_reports_debt_after_native_release(tmp_path: Path, monkeypatch):
    async def scenario():
        binding = Binding()
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        session = await owner.create()
        entered = threading.Event()
        release = threading.Event()
        calls = []
        original = writer._close_claimed

        def close(claimant):
            original(claimant)
            calls.append(1)
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test release")

        monkeypatch.setattr(writer, "_close_claimed", close)
        closing = asyncio.create_task(session.dispose())
        try:
            async with asyncio.timeout(5):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            owner._close_task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert not writer.cleanup_pending
            assert owner.cleanup_pending  # Debt survives even when all fds closed.
            assert session.ownership_state == "root_owned"
            with pytest.raises(TranscriptWriterError, match="unavailable"):
                await session.dispose()
            assert calls == [1] and binding.disposals == 1
        finally:
            release.set()
            await asyncio.gather(closing, return_exceptions=True)
    asyncio.run(scenario())


def test_unknown_native_close_never_repeats_runtime_or_closes_reused_fd(tmp_path: Path, monkeypatch):
    async def scenario():
        binding = Binding()
        lifecycle, context, writer = setup(tmp_path, binding)
        owner = lifecycle.prepare_writer(context, {}, writer=writer, product_id="coding")
        session = await owner.create()
        descriptor = writer._fds["lock"]
        original, replacements, calls = os.close, [], []

        def close(fd):
            original(fd)
            if fd == descriptor:
                calls.append(fd)
                replacement = os.open("/dev/null", os.O_RDONLY)
                assert replacement == fd
                replacements.append(replacement)
                raise OSError("test lost native close receipt")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, "close", close)
                for _ in range(2):
                    with pytest.raises(TranscriptWriterError, match="unavailable"):
                        await session.dispose()
                    assert owner.cleanup_pending
                    assert session.ownership_state == "root_owned"
                assert binding.disposals == 1 and calls == [descriptor]
                os.fstat(replacements[0])
        finally:
            for fd in replacements:
                original(fd)
    asyncio.run(scenario())
