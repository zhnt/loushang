"""Explicit local failed-handoff contract checks; excluded from default PR routes."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path

import pytest

import loushang.harness.session._cleanup as product
from loushang.harness.session._cleanup import (
    SessionConstructionCleanupAttachmentError,
    get_session_construction_cleanup,
    retain_session_construction_failure,
)
from loushang.harness.session.lifecycle import SessionLifecycleTransition
from loushang.harness.session.multiagent import SessionMultiAgentRuntime
from loushang.harness.session.transcript_lifecycle import (
    ProductTranscriptSessionLifecycleStore,
)
from tests.harness.session.test_transcript_lifecycle import _ProductPorts


class Tree(SessionMultiAgentRuntime):
    def __init__(self, events):
        self.events = events
        self.closed = False
        self.fail = False

    async def dispose(self):
        if self.closed:
            return
        self.events.append("tree")
        if self.fail:
            raise OSError("tree close failed")
        self.closed = True


class Session:
    def __init__(self, events):
        self.events = events
        self.multiagent_runtime = Tree(events)
        self.closed = False
        self.fail = False
        self.entered = None
        self.release = None

    async def dispose(self):
        if self.closed:
            return
        self.events.append("session")
        if self.entered is not None:
            self.entered.set()
            await self.release.wait()
        if self.fail:
            raise OSError("session close failed")
        self.closed = True


@pytest.mark.parametrize("failure", ["none", "tree", "session", "transcript"])
def test_original_store_orders_actual_pending_resources(failure):
    expected = Path(
        os.environ.get(
            "LOUSHANG_CONSTRUCTION_TEST_SOURCE_ROOT",
            str(Path(__file__).resolve().parents[2] / "src"),
        )
    ).resolve()
    assert Path(product.__file__).resolve().is_relative_to(expected)

    async def scenario():
        events = []
        ports = _ProductPorts()
        session = Session(events)
        primary = ValueError("builder failed")
        broken = True
        session.multiagent_runtime.fail = failure == "tree"
        session.fail = failure == "session"

        async def discard(transcript):
            events.append("transcript")
            if failure == "transcript" and broken:
                raise OSError("transcript close failed")
            await ports.dispose(transcript)

        def build(*args):
            raise retain_session_construction_failure(primary, session)

        store = ProductTranscriptSessionLifecycleStore(
            ports=replace(ports.lifecycle_ports(), dispose_transcript=discard),
            build_session=build,
        )
        with pytest.raises(ValueError) as caught:
            await store.create(
                None,
                SessionLifecycleTransition("new"),
                cwd="/project",
                parent_session_ref=None,
            )
        assert caught.value is primary
        expected = {
            "none": ["tree", "session", "transcript"],
            "tree": ["tree"],
            "session": ["tree", "session"],
            "transcript": ["tree", "session", "transcript"],
        }[failure]
        assert events == expected
        if failure == "none":
            assert not store.pending_transcripts
        else:
            assert len(store.pending_transcripts) == 1 and not ports.disposed
        session.multiagent_runtime.fail = False
        session.fail = False
        broken = False
        await store.close()
        assert session.closed and session.multiagent_runtime.closed
        assert ports.disposed == ["new.jsonl"] and not store.pending_transcripts
        await store.close()
        assert ports.disposed == ["new.jsonl"]

    asyncio.run(scenario())


def test_same_transcript_reentry_cannot_replace_old_session_debt():
    async def scenario():
        events = []
        ports = _ProductPorts()
        transcript = await ports.create("/project", None)
        session = Session(events)
        session.fail = True
        builds = []
        primary = ValueError("original failure")

        def build(*args):
            builds.append(1)
            raise retain_session_construction_failure(primary, session)

        store = ProductTranscriptSessionLifecycleStore(
            ports=replace(
                ports.lifecycle_ports(), create_transcript=lambda *args: transcript
            ),
            build_session=build,
        )
        with pytest.raises(ValueError):
            await store.create(
                None,
                SessionLifecycleTransition("new"),
                cwd="/project",
                parent_session_ref=None,
            )
        assert store.pending_transcripts == (transcript,)
        with pytest.raises(RuntimeError, match="pending Session construction cleanup"):
            await store.create(
                None,
                SessionLifecycleTransition("new"),
                cwd="/project",
                parent_session_ref=None,
            )
        assert (
            builds == [1]
            and store.pending_transcripts == (transcript,)
            and not ports.disposed
        )
        session.fail = False
        await store.close()
        assert ports.disposed == ["new.jsonl"] and session.closed

    asyncio.run(scenario())


def test_cancelled_waiter_joins_cleanup_then_keeps_transcript_for_close():
    async def scenario():
        events = []
        ports = _ProductPorts()
        session = Session(events)
        session.entered = asyncio.Event()
        session.release = asyncio.Event()
        primary = ValueError("build failed")

        def build(*args):
            raise retain_session_construction_failure(primary, session)

        store = ProductTranscriptSessionLifecycleStore(
            ports=ports.lifecycle_ports(), build_session=build
        )
        caller = asyncio.create_task(
            store.create(
                None,
                SessionLifecycleTransition("new"),
                cwd="/project",
                parent_session_ref=None,
            )
        )
        try:
            await asyncio.wait_for(session.entered.wait(), 5)
            caller.cancel()
            await asyncio.sleep(0)
            assert not caller.done() and not session.closed and not ports.disposed
            session.release.set()
            with pytest.raises(ValueError) as caught:
                await caller
            assert caught.value is primary and session.closed and not ports.disposed
            assert len(store.pending_transcripts) == 1
            await store.close()
            assert ports.disposed == ["new.jsonl"]
        finally:
            session.release.set()
            await asyncio.gather(caller, return_exceptions=True)
            await store.close()

    asyncio.run(scenario())


def test_shared_exception_keeps_independent_failed_sessions_independent():
    async def scenario():
        a, b = Session([]), Session([])
        primary = ValueError("shared source failure")
        first = retain_session_construction_failure(primary, a)
        second = retain_session_construction_failure(primary, b)
        assert first is primary and second is not primary
        one, two = (
            get_session_construction_cleanup(first),
            get_session_construction_cleanup(second),
        )
        assert one is not None and two is not None and one is not two
        await one.retry_cleanup()
        assert a.closed and not b.closed
        await two.retry_cleanup()
        assert b.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("slot", ["foreign", "malformed-wrapper", "hostile-attributes"])
def test_typed_lookup_and_collision_preserve_reachable_real_owner(slot):
    class Hostile(ValueError):
        def __getattribute__(self, name):
            if name in {
                "__dict__",
                "cleanup",
                "_loushang_session_construction_cleanup",
            }:
                raise AssertionError("untrusted attribute invoked")
            return super().__getattribute__(name)

        def __setattr__(self, name, value):
            raise AssertionError("untrusted setter invoked")

    async def scenario():
        session = Session([])
        original = (
            Hostile("original")
            if slot == "hostile-attributes"
            else ValueError("original")
        )
        if slot == "foreign":
            vars(original)["_loushang_session_construction_cleanup"] = object()
        if slot == "malformed-wrapper":
            original = SessionConstructionCleanupAttachmentError(original, object())
        failure = retain_session_construction_failure(original, session)
        cleanup = get_session_construction_cleanup(failure)
        assert cleanup is not None
        if slot == "hostile-attributes":
            assert failure is original
        else:
            assert failure.original_error is original
        await cleanup.retry_cleanup()
        assert session.closed

    asyncio.run(scenario())


def test_task_factory_failure_closes_unsubmitted_coroutine_and_keeps_owner():
    async def scenario():
        session = Session([])
        error = retain_session_construction_failure(ValueError("failed"), session)
        cleanup = get_session_construction_cleanup(error)
        loop = asyncio.get_running_loop()
        old = loop.get_task_factory()
        seen = []

        def reject(loop, operation, **kwargs):
            seen.append(operation)
            raise OSError("submission refused")

        try:
            loop.set_task_factory(reject)
            with pytest.raises(OSError, match="submission refused"):
                await cleanup.retry_cleanup()
        finally:
            loop.set_task_factory(old)
        assert seen[0].cr_frame is None and not session.closed
        await cleanup.retry_cleanup()
        assert session.closed

    asyncio.run(scenario())


def test_two_cleanup_waiters_use_one_original_disposal():
    async def scenario():
        events = []
        session = Session(events)
        session.entered = asyncio.Event()
        session.release = asyncio.Event()
        cleanup = get_session_construction_cleanup(
            retain_session_construction_failure(ValueError("failed"), session)
        )
        a = asyncio.create_task(cleanup.retry_cleanup())
        await asyncio.wait_for(session.entered.wait(), 5)
        b = asyncio.create_task(cleanup.retry_cleanup())
        await asyncio.sleep(0)
        session.release.set()
        await asyncio.gather(a, b)
        assert events == ["tree", "session"] and session.closed

    asyncio.run(scenario())
