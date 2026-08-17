from __future__ import annotations

import asyncio


def test_compaction_coordinator_compacts_session_and_tracks_status() -> None:
    from loushang.harness.context import CompactionCoordinator

    async def scenario() -> None:
        coordinator = CompactionCoordinator()
        calls: list[str] = []

        async def compact() -> str:
            calls.append("compact")
            return "summary"

        result = await coordinator.run(compact, reason="manual")

        assert result == "summary"
        assert calls == ["compact"]
        status = coordinator.get_status()
        assert status.is_compacting is False
        assert status.last_reason == "manual"
        assert status.last_result == result
        assert status.last_error is None

    asyncio.run(scenario())


def test_compaction_coordinator_maybe_compacts_after_turn() -> None:
    from loushang.harness.context import CompactionCoordinator

    async def scenario() -> None:
        coordinator = CompactionCoordinator()
        calls: list[str] = []

        async def compact() -> str:
            calls.append("threshold")
            return "threshold summary"

        result = await coordinator.run(compact, reason="threshold")

        assert result == "threshold summary"
        assert calls == ["threshold"]
        status = coordinator.get_status()
        assert status.is_compacting is False
        assert status.last_reason == "threshold"
        assert status.last_result == result

    asyncio.run(scenario())


def test_compaction_coordinator_records_errors() -> None:
    import pytest

    from loushang.harness.context import CompactionCoordinator

    async def scenario() -> None:
        coordinator = CompactionCoordinator()

        async def compact() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await coordinator.run(compact, reason="manual")

        status = coordinator.get_status()
        assert status.is_compacting is False
        assert status.last_reason == "manual"
        assert status.last_error == "boom"

    asyncio.run(scenario())
