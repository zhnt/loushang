"""Reusable lifecycle primitives for injected Product-facing hosts.

The standard Channel protocol host owns its operation frames in
``loushang.channel.host``. This Harness module is deliberately lower level: it owns
the line-input lifecycle, background task tracking, and a small lifecycle
action contract that Product-specific RPC, terminal, or embedded hosts can
adopt without sharing a wire schema.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TextIO, TypeAlias, TypeVar, cast, get_args

from .stdout_guard import stdout_guard

ProductHostActionType: TypeAlias = Literal[
    "start",
    "stop",
    "submit_input",
    "render_event",
    "get_state",
    "wait_for_idle",
    "rebind_session",
    "dispose",
]
ProductHostState: TypeAlias = Mapping[str, object]
ProductHostInputHandler = Callable[[str], Awaitable[None] | None]
ProductHostFailureHandler = Callable[[Exception], Awaitable[None] | None]
ProductHostStateReader = Callable[["ProductHostAdapter"], ProductHostState]
TaskT = TypeVar("TaskT")
TurnT = TypeVar("TurnT")


@dataclass(frozen=True)
class ProductHostStreams:
    """Resolved stdio streams for a Product-owned process host."""

    stdin: TextIO
    stdout: TextIO
    stderr: TextIO

    @classmethod
    def resolve(
        cls,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> "ProductHostStreams":
        """Bind injected streams, falling back to the process standard streams."""

        return cls(
            stdin=sys.stdin if stdin is None else stdin,
            stdout=sys.stdout if stdout is None else stdout,
            stderr=sys.stderr if stderr is None else stderr,
        )


@dataclass(frozen=True)
class ProductHostLifecycle:
    """Shared stdio and shutdown lifecycle for product CLI hosts.

    The product still decides when structured output needs protection. Channel
    owns stream binding, stdout takeover, and disposal fallback.
    """

    streams: ProductHostStreams

    @classmethod
    def resolve(
        cls,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> "ProductHostLifecycle":
        return cls(ProductHostStreams.resolve(stdin=stdin, stdout=stdout, stderr=stderr))

    def output_guard(self, *, enabled: bool) -> AbstractContextManager[None]:
        if not enabled:
            from contextlib import nullcontext

            return nullcontext()
        return stdout_guard(
            stdout=self.streams.stdout,
            stderr=self.streams.stderr,
        )

    async def dispose(self, *candidates: object) -> bool:
        return await dispose_product_host(*candidates)

    async def run_turns(
        self,
        turns: Sequence[TurnT],
        *,
        run_turn: Callable[[TurnT, bool, bool], Awaitable[int]],
        dispose_candidates: Sequence[object] = (),
    ) -> int:
        """Run ordered product turns and dispose after an intermediate failure.

        The helper owns only ordering and lifecycle cleanup.  Products provide
        the turn runner, so prompt preparation, output shape, and command
        semantics remain outside Channel.
        """

        for index, turn in enumerate(turns):
            is_first = index == 0
            is_last = index == len(turns) - 1
            exit_code = await run_turn(turn, is_first, is_last)
            if exit_code != 0:
                if not is_last:
                    await self.dispose(*dispose_candidates)
                return exit_code
        return 0


@dataclass(frozen=True)
class ProductHostAction:
    """One lifecycle action for a Product-owned host adapter."""

    type: ProductHostActionType
    payload: object | None = None


class ProductHostAdapter(Protocol):
    """Common lifecycle contract for a Product-specific host adapter.

    Products define their transport schema and state projection separately.
    This protocol intentionally does not assume an Agent session, a work run,
    JSON, or any Product command vocabulary.
    """

    async def start(self, *args: Any, **kwargs: Any) -> int: ...

    async def stop(self) -> int: ...

    async def submit_input(self, input_payload: object) -> int: ...

    async def wait_for_idle(self) -> int: ...

    def rebind_session(self, session: object | None = None) -> int: ...

    async def dispose(self) -> int: ...

    def render_event(self, event: object) -> None: ...


_SUPPORTED_PRODUCT_HOST_ACTION_TYPES = frozenset(get_args(ProductHostActionType))


def normalize_product_host_action(
    action: ProductHostAction | Mapping[str, object],
    *,
    action_name: str = "Product host action",
) -> ProductHostAction:
    """Normalize one strict lifecycle action without choosing Product fields."""

    if isinstance(action, ProductHostAction):
        return action
    if not isinstance(action, Mapping):
        raise TypeError(f"{action_name} must be an action or mapping payload.")
    raw_type = action.get("type")
    if not isinstance(raw_type, str) or not raw_type:
        raise ValueError(f"{action_name} requires string type.")
    if raw_type not in _SUPPORTED_PRODUCT_HOST_ACTION_TYPES:
        raise ValueError(f"Unsupported {action_name.lower()}: {raw_type}")
    return ProductHostAction(
        cast(ProductHostActionType, raw_type),
        action.get("payload"),
    )


async def dispatch_product_host_action(
    adapter: ProductHostAdapter,
    action: ProductHostAction | Mapping[str, object],
    *,
    get_state: ProductHostStateReader,
) -> int | ProductHostState:
    """Dispatch a generic lifecycle action through an injected state reader."""

    action = normalize_product_host_action(action)
    if action.type == "start":
        if isinstance(action.payload, tuple):
            return await adapter.start(*action.payload)
        if action.payload is None:
            return await adapter.start()
        return await adapter.start(action.payload)
    if action.type == "stop":
        return await adapter.stop()
    if action.type == "submit_input":
        return await adapter.submit_input(action.payload)
    if action.type == "render_event":
        adapter.render_event(action.payload)
        return 0
    if action.type == "get_state":
        return get_state(adapter)
    if action.type == "wait_for_idle":
        return await adapter.wait_for_idle()
    if action.type == "rebind_session":
        return adapter.rebind_session(action.payload)
    if action.type == "dispose":
        return await adapter.dispose()
    raise ValueError(f"Unsupported product host action: {action.type}")


class ProductHostRuntime:
    """Run an injected line-input handler until EOF, failure, or stop.

    The runtime only owns read scheduling and lifecycle.  Input parsing,
    output, error representation, and Product disposal remain injected.
    """

    def __init__(self, *, stdin: TextIO) -> None:
        self._stdin = stdin
        self._stdin_uses_thread = _stream_supports_fileno(stdin)
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(
        self,
        handle_input: ProductHostInputHandler,
        *,
        handle_failure: ProductHostFailureHandler,
    ) -> int:
        """Dispatch non-empty input lines and report one terminal failure."""

        self._running = True
        try:
            while self._running:
                line = await self._read_line()
                if line == "":
                    break
                if not line.strip():
                    continue
                await _resolve(handle_input(line))
            return 0
        except Exception as error:
            await _resolve(handle_failure(error))
            return 1
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop after the current input handler returns."""

        self._running = False

    async def _read_line(self) -> str:
        if self._stdin_uses_thread:
            return await asyncio.to_thread(self._stdin.readline)
        return self._stdin.readline()


class ProductHostTaskTracker:
    """Track Product-started background tasks until a host shuts down."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def track(self, task: asyncio.Task[TaskT]) -> asyncio.Task[TaskT]:
        self._tasks.add(cast(asyncio.Task[Any], task))

        def cleanup(done: asyncio.Task[Any]) -> None:
            self._tasks.discard(done)

        task.add_done_callback(cleanup)
        return task

    async def drain(self) -> None:
        """Await all tasks, allowing task failures to remain Product-owned."""

        while self._tasks:
            await asyncio.sleep(0)
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


async def dispose_product_host(*candidates: object) -> bool:
    """Dispose the first candidate that exposes an async or sync ``dispose`` hook.

    A Product decides which runtime object owns shutdown. This helper only
    centralizes the common fallback needed by CLI and embedded hosts.
    """

    for candidate in candidates:
        disposer = getattr(candidate, "dispose", None)
        if not callable(disposer):
            continue
        result = disposer()
        if inspect.isawaitable(result):
            await result
        return True
    return False


async def _resolve(value: Awaitable[None] | None) -> None:
    if value is not None:
        await value


def _stream_supports_fileno(stream: TextIO) -> bool:
    fileno = getattr(stream, "fileno", None)
    if not callable(fileno):
        return False
    try:
        fileno()
    except (io.UnsupportedOperation, OSError, ValueError):
        return False
    return True


def stream_is_tty(stream: TextIO) -> bool:
    """Return whether an injected stream represents an interactive terminal."""

    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError:
        return False


__all__ = [
    "ProductHostAction",
    "ProductHostActionType",
    "ProductHostAdapter",
    "ProductHostLifecycle",
    "ProductHostRuntime",
    "ProductHostStreams",
    "ProductHostState",
    "ProductHostStateReader",
    "ProductHostTaskTracker",
    "dispose_product_host",
    "dispatch_product_host_action",
    "normalize_product_host_action",
    "stream_is_tty",
]
