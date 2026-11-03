from __future__ import annotations

import asyncio

import pytest


def test_mutation_queue_serializes_canonical_same_path(tmp_path) -> None:
    from loushang.harness.workspace.mutation_queue import with_file_mutation_queue

    path = tmp_path / "dir" / "note.txt"
    path.parent.mkdir()
    spelling_a = path
    spelling_b = path.parent / "." / ".." / "dir" / "note.txt"
    events: list[str] = []

    async def first() -> None:
        async with with_file_mutation_queue(spelling_a):
            events.append("first-start")
            await asyncio.sleep(0.01)
            events.append("first-end")

    async def second() -> None:
        async with with_file_mutation_queue(spelling_b):
            events.append("second")

    async def run() -> None:
        await asyncio.gather(first(), second())

    asyncio.run(run())

    assert events == ["first-start", "first-end", "second"]


def test_mutation_queue_allows_different_paths_to_progress(tmp_path) -> None:
    from loushang.harness.workspace.mutation_queue import with_file_mutation_queue

    entered_first = asyncio.Event()
    release_first = asyncio.Event()
    events: list[str] = []

    async def run() -> None:
        async def first() -> None:
            async with with_file_mutation_queue(tmp_path / "first.txt"):
                events.append("first-start")
                entered_first.set()
                await release_first.wait()
                events.append("first-end")

        async def second() -> None:
            await entered_first.wait()
            async with with_file_mutation_queue(tmp_path / "second.txt"):
                events.append("second")
                release_first.set()

        await asyncio.gather(first(), second())

    asyncio.run(run())

    assert events == ["first-start", "second", "first-end"]


def test_mutation_queue_rejects_relative_paths() -> None:
    from loushang.harness.workspace.mutation_queue import with_file_mutation_queue

    async def run() -> None:
        async with with_file_mutation_queue("relative.txt"):
            pass

    with pytest.raises(ValueError, match="path must be absolute"):
        asyncio.run(run())


def test_mutation_queue_context_tracks_and_releases_active_path(tmp_path) -> None:
    from loushang.harness.workspace import mutation_queue

    path = tmp_path / "note.txt"

    async def run() -> None:
        async with mutation_queue.with_file_mutation_queue(path):
            assert str(path.resolve()) in mutation_queue._mutation_locks

    asyncio.run(run())
    assert mutation_queue._mutation_locks == {}


def test_mutation_queue_runner_serializes_callbacks_and_returns_results(tmp_path) -> None:
    from loushang.harness.workspace.mutation_queue import (
        run_with_file_mutation_queue,
    )

    path = tmp_path / "note.txt"
    entered_first = asyncio.Event()
    release_first = asyncio.Event()
    events: list[str] = []

    async def first() -> str:
        events.append("first-start")
        entered_first.set()
        await release_first.wait()
        events.append("first-end")
        return "first-result"

    async def second() -> str:
        events.append("second")
        return "second-result"

    async def run() -> tuple[str, str]:
        first_task = asyncio.create_task(run_with_file_mutation_queue(path, first))
        await entered_first.wait()
        second_task = asyncio.create_task(run_with_file_mutation_queue(path, second))
        await asyncio.sleep(0.01)
        release_first.set()
        first_result, second_result = await asyncio.gather(first_task, second_task)
        return first_result, second_result

    assert asyncio.run(run()) == ("first-result", "second-result")
    assert events == ["first-start", "first-end", "second"]


def test_mutation_queue_runner_accepts_sync_results_and_cleans_up(tmp_path) -> None:
    from loushang.harness.workspace import mutation_queue

    path = tmp_path / "note.txt"

    assert asyncio.run(mutation_queue.run_with_file_mutation_queue(path, lambda: "done")) == "done"
    assert mutation_queue._mutation_locks == {}


def test_mutation_queue_cleans_up_after_callback_failure(tmp_path) -> None:
    from loushang.harness.workspace import mutation_queue

    async def fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(mutation_queue.run_with_file_mutation_queue(tmp_path / "note.txt", fail))

    assert mutation_queue._mutation_locks == {}
