from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from loushang.harness.capabilities.deferred_slot import (
    DeferredCapabilityDeclaration,
    DeferredCapabilitySlot,
)


@dataclass
class _Candidate:
    preparations: int = 0
    publications: int = 0
    disposals: int = 0
    fail_publication: bool = False
    fail_disposal: bool = False
    prepare_hook: Callable[[], Awaitable[None]] | None = None

    async def prepare(self) -> None:
        self.preparations += 1
        if self.prepare_hook is not None:
            await self.prepare_hook()

    def publish(self) -> None:
        self.publications += 1
        if self.fail_publication:
            raise ValueError("publication failed")

    async def dispose(self) -> None:
        self.disposals += 1
        if self.fail_disposal:
            raise ValueError("disposal failed")


def _declaration() -> DeferredCapabilityDeclaration:
    return DeferredCapabilityDeclaration(
        capability_id="coding.lsp",
        facet_ids=("semantic", "tool-runtime"),
        tool_names=("inspect_symbol", "document_outline"),
    )


def test_deferred_slot_is_dormant_until_explicit_demand_and_single_flight() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        candidate = _Candidate()
        async def prepare() -> None:
            entered.set()
            await release.wait()

        candidate.prepare_hook = prepare
        slot = DeferredCapabilitySlot(_declaration(), lambda: candidate)
        assert slot.state == "dormant"
        assert slot.active is None
        assert candidate.preparations == 0

        callers = [asyncio.create_task(slot.activate()) for _ in range(100)]
        await entered.wait()
        assert candidate.preparations == 1
        assert slot.state == "activating"
        callers[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await callers[0]
        assert slot.state == "activating"
        release.set()
        assert all(value is candidate for value in await asyncio.gather(*callers[1:]))
        assert candidate.publications == 1
        assert slot.active is candidate
        assert await slot.activate() is candidate
        assert candidate.preparations == 1

        await slot.close()
        assert slot.state == "closed"
        assert candidate.disposals == 1
        with pytest.raises(RuntimeError, match="closing"):
            await slot.activate()

    asyncio.run(scenario())


def test_deferred_slot_close_during_preparation_skips_publication() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        candidate = _Candidate()

        async def prepare() -> None:
            entered.set()
            await release.wait()

        candidate.prepare_hook = prepare
        slot = DeferredCapabilitySlot(_declaration(), lambda: candidate)
        activating = asyncio.create_task(slot.activate())
        await entered.wait()
        closing = asyncio.create_task(slot.close())
        await asyncio.sleep(0)
        assert slot.state == "closing"
        release.set()
        with pytest.raises(RuntimeError, match="closed during preparation"):
            await activating
        await closing
        assert candidate.publications == 0
        assert candidate.disposals == 1
        assert slot.state == "closed"

    asyncio.run(scenario())


def test_deferred_slot_publication_failure_requires_fresh_explicit_retry() -> None:
    async def scenario() -> None:
        first = _Candidate(fail_publication=True)
        second = _Candidate()
        prepared = iter((first, second))
        slot = DeferredCapabilitySlot(_declaration(), lambda: next(prepared))
        with pytest.raises(ValueError, match="publication failed"):
            await slot.activate()
        assert slot.state == "failed"
        assert first.disposals == 1
        with pytest.raises(RuntimeError, match="activation failed"):
            await slot.activate()
        assert first.preparations == 1
        assert second.preparations == 0
        assert await slot.activate(retry=True) is second
        assert second.preparations == 1
        await slot.close()
        assert second.disposals == 1

    asyncio.run(scenario())


def test_deferred_slot_retains_failed_cleanup_for_close_retry() -> None:
    async def scenario() -> None:
        candidate = _Candidate(fail_publication=True, fail_disposal=True)

        slot = DeferredCapabilitySlot(_declaration(), lambda: candidate)
        with pytest.raises(ValueError, match="publication failed"):
            await slot.activate()
        with pytest.raises(RuntimeError, match="cleanup is pending"):
            await slot.activate(retry=True)
        with pytest.raises(ValueError, match="disposal failed"):
            await slot.close()
        assert slot.state == "closing"
        candidate.fail_disposal = False
        await slot.close()
        assert slot.state == "closed"
        assert candidate.disposals == 3

    asyncio.run(scenario())


def test_deferred_slot_retains_candidate_after_partial_preparation_failure() -> None:
    async def scenario() -> None:
        candidate = _Candidate(fail_disposal=True)

        async def fail_after_acquiring_resources() -> None:
            raise ValueError("preparation failed after acquisition")

        candidate.prepare_hook = fail_after_acquiring_resources
        slot = DeferredCapabilitySlot(_declaration(), lambda: candidate)
        with pytest.raises(ValueError, match="after acquisition"):
            await slot.activate()
        assert candidate.preparations == 1
        assert candidate.disposals == 1
        assert slot.state == "failed"
        with pytest.raises(RuntimeError, match="cleanup is pending"):
            await slot.activate(retry=True)
        candidate.fail_disposal = False
        await slot.close()
        assert candidate.disposals == 2
        assert slot.state == "closed"

    asyncio.run(scenario())


def test_deferred_slot_close_joins_cleanup_after_caller_cancellation() -> None:
    async def scenario() -> None:
        disposal_started = asyncio.Event()
        finish_disposal = asyncio.Event()

        class SlowCandidate(_Candidate):
            async def dispose(self) -> None:
                disposal_started.set()
                await finish_disposal.wait()
                await super().dispose()

        candidate = SlowCandidate()

        slot = DeferredCapabilitySlot(_declaration(), lambda: candidate)
        await slot.activate()
        closing = asyncio.create_task(slot.close())
        await disposal_started.wait()
        closing.cancel()
        assert slot.state == "closing"
        finish_disposal.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert slot.state == "closed"
        assert candidate.disposals == 1

    asyncio.run(scenario())
