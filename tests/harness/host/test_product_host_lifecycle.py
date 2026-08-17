from __future__ import annotations

import asyncio
from io import StringIO

from loushang.harness.host.product_host import ProductHostLifecycle, stream_is_tty


def test_product_host_lifecycle_resolves_injected_streams() -> None:
    stdin = StringIO("input\n")
    stdout = StringIO()
    stderr = StringIO()

    lifecycle = ProductHostLifecycle.resolve(
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )

    assert lifecycle.streams.stdin is stdin
    assert lifecycle.streams.stdout is stdout
    assert lifecycle.streams.stderr is stderr


def test_product_host_lifecycle_output_guard_is_optional() -> None:
    lifecycle = ProductHostLifecycle.resolve(
        stdout=StringIO(),
        stderr=StringIO(),
    )

    with lifecycle.output_guard(enabled=False):
        assert lifecycle.streams.stdout.getvalue() == ""


def test_product_host_lifecycle_runs_turns_and_disposes_after_intermediate_failure() -> None:
    class _Runtime:
        def __init__(self) -> None:
            self.dispose_calls = 0

        async def dispose(self) -> None:
            self.dispose_calls += 1

    async def scenario() -> None:
        lifecycle = ProductHostLifecycle.resolve(
            stdin=StringIO(), stdout=StringIO(), stderr=StringIO()
        )
        runtime = _Runtime()
        calls: list[tuple[str, bool, bool]] = []

        async def run_turn(turn: str, is_first: bool, is_last: bool) -> int:
            calls.append((turn, is_first, is_last))
            return 7 if turn == "failed" else 0

        assert (
            await lifecycle.run_turns(
                ("first", "failed", "unreached"),
                run_turn=run_turn,
                dispose_candidates=(runtime,),
            )
            == 7
        )
        assert calls == [("first", True, False), ("failed", False, False)]
        assert runtime.dispose_calls == 1

    asyncio.run(scenario())


def test_product_host_lifecycle_does_not_dispose_after_final_turn_failure() -> None:
    class _Runtime:
        def __init__(self) -> None:
            self.dispose_calls = 0

        async def dispose(self) -> None:
            self.dispose_calls += 1

    async def scenario() -> None:
        lifecycle = ProductHostLifecycle.resolve(
            stdin=StringIO(), stdout=StringIO(), stderr=StringIO()
        )
        runtime = _Runtime()

        async def run_turn(_turn: str, _is_first: bool, _is_last: bool) -> int:
            return 9

        assert (
            await lifecycle.run_turns(
                ("only",),
                run_turn=run_turn,
                dispose_candidates=(runtime,),
            )
            == 9
        )
        assert runtime.dispose_calls == 0

    asyncio.run(scenario())


def test_stream_is_tty_handles_injected_non_tty_and_os_error_streams() -> None:
    class _BrokenStream:
        def isatty(self) -> bool:
            raise OSError("closed")

    assert stream_is_tty(StringIO()) is False
    assert stream_is_tty(_BrokenStream()) is False
