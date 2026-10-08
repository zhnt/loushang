from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.harness.session import (
    ProductTranscriptSessionLifecycleStore,
    SessionLifecycleTransition,
)

from .test_transcript_lifecycle import _ProductPorts, _Session


@pytest.mark.parametrize("operation", ["create", "restore", "fork", "validate"])
def test_failed_construction_keeps_exact_transcript_and_primary_error(operation):
    async def scenario():
        ports = _ProductPorts()
        pending = []
        failed = True
        primary = ValueError("construction failed")

        async def dispose(transcript):
            pending.append(transcript)
            if failed:
                raise OSError("cleanup pending")

        def build(*args):
            raise primary

        def validate(transcript):
            raise primary

        store = ProductTranscriptSessionLifecycleStore(
            ports=replace(ports.lifecycle_ports(), dispose_transcript=dispose),
            build_session=build,
            validate_restored_transcript=validate if operation == "validate" else None,
        )
        transition = SessionLifecycleTransition(reason="new")
        try:
            with pytest.raises(ValueError) as result:
                if operation == "create":
                    await store.create(None, transition, cwd="/project", parent_session_ref=None)
                elif operation in {"restore", "validate"}:
                    await store.restore(None, transition, "saved.jsonl")
                else:
                    await store.fork(_Session("source.jsonl", "/project"), transition, "leaf")
            assert result.value is primary and "cleanup retained" in primary.__notes__[0]
            retained, = store.pending_transcripts
            assert pending == [retained]
            with pytest.raises(OSError, match="cleanup pending"):
                await store.close()
            assert store.pending_transcripts == (retained,)
            before = tuple(ports.actions)
            with pytest.raises(RuntimeError, match="closed"):
                await store.create(None, transition, cwd="/project", parent_session_ref=None)
            assert tuple(ports.actions) == before
            failed = False
            await store.close()
            assert not store.pending_transcripts and pending == [retained] * 3
            await store.close()
            assert pending == [retained] * 3
        finally:
            failed = False
            await store.close()

    asyncio.run(scenario())


def test_close_waits_for_late_transcript_then_disposes_without_building():
    async def scenario():
        ports = _ProductPorts()
        entered, release = asyncio.Event(), asyncio.Event()
        built = []

        async def create(cwd, parent):
            entered.set()
            await release.wait()
            return await ports.create(cwd, parent)

        store = ProductTranscriptSessionLifecycleStore(
            ports=replace(ports.lifecycle_ports(), create_transcript=create),
            build_session=lambda *args: built.append(args),
        )
        caller = asyncio.create_task(store.create(
            None, SessionLifecycleTransition(reason="new"), cwd="/project", parent_session_ref=None,
        ))
        closer = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            closer = asyncio.create_task(store.close())
            await asyncio.sleep(0)
            assert not closer.done() and not ports.disposed
            release.set()
            with pytest.raises(RuntimeError, match="closed"):
                await caller
            await asyncio.wait_for(closer, 5)
            assert ports.disposed == ["new.jsonl"] and not built
            assert not store.pending_transcripts
        finally:
            release.set()
            await asyncio.gather(caller, *([closer] if closer else []), return_exceptions=True)
            await store.close()

    asyncio.run(scenario())


def test_cancelled_cleanup_waiter_keeps_original_transcript_for_retry():
    async def scenario():
        ports = _ProductPorts()
        entered, release = asyncio.Event(), asyncio.Event()
        count = 0

        async def dispose(transcript):
            nonlocal count
            count += 1
            entered.set()
            await release.wait()

        def build(*args):
            raise ValueError("construction failed")

        store = ProductTranscriptSessionLifecycleStore(
            ports=replace(ports.lifecycle_ports(), dispose_transcript=dispose), build_session=build,
        )
        caller = asyncio.create_task(store.create(
            None, SessionLifecycleTransition(reason="new"), cwd="/project", parent_session_ref=None,
        ))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            caller.cancel()
            with pytest.raises(ValueError) as result:
                await caller
            assert "CancelledError" in result.value.__notes__[0]
            retained, = store.pending_transcripts
            release.set()
            await store.close()
            assert not store.pending_transcripts and count == 2
            assert retained.ref == "new.jsonl"
        finally:
            release.set()
            await asyncio.gather(caller, return_exceptions=True)
            await store.close()

    asyncio.run(scenario())


def test_close_attempts_independent_pending_transcripts_after_one_failure():
    async def scenario():
        ports = _ProductPorts()
        failing = {"one.jsonl", "two.jsonl"}
        disposed = []

        async def dispose(transcript):
            if transcript.ref in failing:
                raise OSError("cleanup pending")
            disposed.append(transcript.ref)

        def build(*args):
            raise ValueError("construction failed")

        store = ProductTranscriptSessionLifecycleStore(
            ports=replace(ports.lifecycle_ports(), dispose_transcript=dispose), build_session=build,
        )
        transition = SessionLifecycleTransition(reason="restore")
        try:
            for name in ("one.jsonl", "two.jsonl"):
                with pytest.raises(ValueError):
                    await store.restore(None, transition, name)
            assert len(store.pending_transcripts) == 2
            failing.remove("two.jsonl")
            with pytest.raises(OSError):
                await store.close()
            assert disposed == ["two.jsonl"]
            assert [item.ref for item in store.pending_transcripts] == ["one.jsonl"]
            failing.clear()
            await store.close()
            assert disposed == ["two.jsonl", "one.jsonl"]
        finally:
            failing.clear()
            await store.close()

    asyncio.run(scenario())
