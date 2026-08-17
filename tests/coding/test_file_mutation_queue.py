import asyncio

import pytest

import loushang.harness.workspace.mutation_queue as file_mutation_queue
from loushang.harness.workspace.mutation_queue import (
    run_with_file_mutation_queue,
    with_file_mutation_queue,
)


def test_mutation_queue_serializes_same_file_operations(tmp_path) -> None:
    path = tmp_path / "note.txt"
    events: list[str] = []

    async def first() -> None:
        async with with_file_mutation_queue(str(path)):
            events.append("first-start")
            await asyncio.sleep(0.01)
            events.append("first-end")

    async def second() -> None:
        async with with_file_mutation_queue(str(path)):
            events.append("second")

    async def run_both() -> None:
        await asyncio.gather(first(), second())

    asyncio.run(run_both())
    assert events == ["first-start", "first-end", "second"]


def test_mutation_queue_uses_canonical_same_file_identity(tmp_path) -> None:
    path = tmp_path / "dir" / "note.txt"
    path.parent.mkdir()
    path.write_text("x", encoding="utf-8")
    spelling_a = str(path)
    spelling_b = str(path.parent / "." / ".." / "dir" / "note.txt")
    events: list[str] = []

    async def first() -> None:
        async with with_file_mutation_queue(spelling_a):
            events.append("first-start")
            await asyncio.sleep(0.01)
            events.append("first-end")

    async def second() -> None:
        async with with_file_mutation_queue(spelling_b):
            events.append("second")

    async def run_both() -> None:
        await asyncio.gather(first(), second())

    asyncio.run(run_both())
    assert events == ["first-start", "first-end", "second"]


def test_mutation_queue_allows_different_files_to_progress_independently(
    tmp_path,
) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    entered_first = asyncio.Event()
    second_finished = asyncio.Event()
    release_first = asyncio.Event()
    events: list[str] = []

    async def hold_first() -> None:
        async with with_file_mutation_queue(str(first)):
            events.append("first-start")
            entered_first.set()
            await release_first.wait()
            events.append("first-end")

    async def run_second() -> None:
        await entered_first.wait()
        async with with_file_mutation_queue(str(second)):
            events.append("second")
            second_finished.set()

    async def run_both() -> None:
        first_task = asyncio.create_task(hold_first())
        second_task = asyncio.create_task(run_second())
        await asyncio.wait_for(second_finished.wait(), timeout=0.1)
        release_first.set()
        await asyncio.gather(first_task, second_task)

    asyncio.run(run_both())
    assert events == ["first-start", "second", "first-end"]


def test_mutation_queue_rejects_relative_paths() -> None:
    async def run_queue() -> None:
        async with with_file_mutation_queue("note.txt"):
            pass

    with pytest.raises(ValueError, match="path must be absolute"):
        asyncio.run(run_queue())


def test_mutation_queue_cleans_up_lock_entries_after_use(tmp_path) -> None:
    path = tmp_path / "note.txt"

    async def run_queue() -> None:
        async with with_file_mutation_queue(str(path)):
            assert str(path.resolve()) in file_mutation_queue._mutation_locks

    asyncio.run(run_queue())
    assert file_mutation_queue._mutation_locks == {}


def test_run_with_file_mutation_queue_serializes_callback_operations(tmp_path) -> None:
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

    async def run_both() -> tuple[str, str]:
        first_task = asyncio.create_task(run_with_file_mutation_queue(str(path), first))
        await entered_first.wait()
        second_task = asyncio.create_task(
            run_with_file_mutation_queue(str(path), second)
        )
        await asyncio.sleep(0.01)
        release_first.set()
        first_result, second_result = await asyncio.gather(first_task, second_task)
        return first_result, second_result

    assert asyncio.run(run_both()) == ("first-result", "second-result")
    assert events == ["first-start", "first-end", "second"]


def test_run_with_file_mutation_queue_accepts_sync_callback(tmp_path) -> None:
    path = tmp_path / "note.txt"

    result = asyncio.run(run_with_file_mutation_queue(str(path), lambda: "sync-result"))

    assert result == "sync-result"


def test_mutation_queue_uses_its_direct_harness_owner(tmp_path) -> None:
    from loushang.harness.workspace.mutation_queue import (
        run_with_file_mutation_queue as exported_runner,
    )
    from loushang.harness.workspace.mutation_queue import (
        with_file_mutation_queue as exported_context_manager,
    )

    path = tmp_path / "note.txt"

    assert exported_context_manager is with_file_mutation_queue
    assert (
        asyncio.run(exported_runner(str(path), lambda: "direct-result"))
        == "direct-result"
    )


def test_run_with_file_mutation_queue_cleans_up_after_callback_error(tmp_path) -> None:
    path = tmp_path / "note.txt"

    async def fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run_with_file_mutation_queue(str(path), fail))

    assert file_mutation_queue._mutation_locks == {}
