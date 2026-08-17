from __future__ import annotations

import asyncio


def _item(item_id: str, tokens: int, *, pinned: bool = False):
    from loushang.harness.context import ContextItem

    return ContextItem(
        item_id=item_id,
        kind="message",
        content=item_id,
        estimated_tokens=tokens,
        pinned=pinned,
    )


def test_recent_window_compacts_without_reducer() -> None:
    from loushang.harness.context import (
        CompactionRequest,
        ContextBundle,
        ContextCompactionCoordinator,
        RecentWindowStrategy,
    )

    async def scenario() -> None:
        request = CompactionRequest(
            bundle=ContextBundle(items=(_item("old", 5), _item("new", 5))),
            target_tokens=5,
        )
        result = await ContextCompactionCoordinator[str]().compact(
            request,
            strategy=RecentWindowStrategy(),
        )

        assert result.outcome == "completed"
        assert tuple(item.item_id for item in result.bundle.items) == ("new",)
        assert result.artifact is None

    asyncio.run(scenario())


def test_rolling_summary_reserves_output_and_returns_product_artifact() -> None:
    from loushang.harness.context import (
        CompactionRequest,
        ContextBundle,
        ContextCompactionCoordinator,
        RollingSummaryStrategy,
    )

    class Reducer:
        def __init__(self) -> None:
            self.request = None

        async def reduce(self, request):
            self.request = request
            return _item("summary", 3)

    async def scenario() -> None:
        reducer = Reducer()
        request = CompactionRequest(
            bundle=ContextBundle(
                items=(_item("old-a", 4), _item("old-b", 4), _item("new", 4))
            ),
            target_tokens=8,
            summary_reserve_tokens=4,
            previous_summary=_item("previous-summary", 2),
        )
        result = await ContextCompactionCoordinator[str]().compact(
            request,
            strategy=RollingSummaryStrategy(),
            reducer=reducer,
        )

        assert reducer.request is not None
        assert reducer.request.max_output_tokens == 4
        assert tuple(item.item_id for item in reducer.request.items) == (
            "previous-summary",
            "old-a",
            "old-b",
        )
        assert tuple(item.item_id for item in result.bundle.items) == (
            "summary",
            "new",
        )
        assert result.artifact is not None
        assert result.artifact.summary.item_id == "summary"
        assert result.artifact.summarized_item_ids == (
            "previous-summary",
            "old-a",
            "old-b",
        )

    asyncio.run(scenario())


def test_cancellation_retains_original_bundle_without_calling_reducer() -> None:
    from loushang.harness.context import (
        CompactionRequest,
        ContextBundle,
        ContextCompactionCoordinator,
        RollingSummaryStrategy,
    )

    class Reducer:
        async def reduce(self, request):
            raise AssertionError("reducer should not run")

    async def scenario() -> None:
        signal = asyncio.Event()
        signal.set()
        bundle = ContextBundle(items=(_item("old", 5), _item("new", 5)))
        result = await ContextCompactionCoordinator[str]().compact(
            CompactionRequest(
                bundle=bundle,
                target_tokens=5,
                summary_reserve_tokens=2,
                cancellation=signal,
            ),
            strategy=RollingSummaryStrategy(),
            reducer=Reducer(),
        )

        assert result.outcome == "aborted"
        assert result.bundle is bundle
        assert result.artifact is None

    asyncio.run(scenario())


def test_failed_reducer_can_keep_original_bundle() -> None:
    from loushang.harness.context import (
        CompactionRequest,
        ContextBundle,
        ContextCompactionCoordinator,
        RollingSummaryStrategy,
    )

    class Reducer:
        async def reduce(self, request):
            raise RuntimeError("summary unavailable")

    async def scenario() -> None:
        bundle = ContextBundle(items=(_item("old", 5), _item("new", 5)))
        result = await ContextCompactionCoordinator[str]().compact(
            CompactionRequest(
                bundle=bundle,
                target_tokens=5,
                summary_reserve_tokens=2,
                failure_behavior="keep_original",
            ),
            strategy=RollingSummaryStrategy(),
            reducer=Reducer(),
        )

        assert result.outcome == "failed"
        assert result.bundle is bundle
        assert result.error == "summary unavailable"

    asyncio.run(scenario())


def test_compaction_lifecycle_is_single_flight_and_abortable() -> None:
    from loushang.harness.context import CompactionCoordinator

    async def scenario() -> None:
        coordinator = CompactionCoordinator[str]()
        coordinator.abort()
        assert coordinator.get_status().aborted is False
        started = asyncio.Event()
        release = asyncio.Event()
        aborted: list[bool] = []

        async def operation() -> str:
            started.set()
            await release.wait()
            return "done"

        task = asyncio.create_task(
            coordinator.run(
                operation,
                reason="threshold",
                abort_driver=lambda: aborted.append(True),
            )
        )
        await started.wait()
        assert coordinator.is_compacting is True
        coordinator.abort()
        assert aborted == [True]
        release.set()
        assert await task == "done"
        assert coordinator.get_status().aborted is True

    asyncio.run(scenario())
