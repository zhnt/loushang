from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Generic, Literal, Protocol, Self, TextIO, TypeVar

from loushang.harnesstui.conversation.screen_runner import (
    AbortHandler,
    ConversationInputRouterFactoryPort,
    ConversationScreenPort,
    LocalCommandPredicate,
    PromptHandler,
    ShouldExit,
    SurfaceIntentHandler,
    TerminalModeFactory,
    TerminalSizeProvider,
    TextHandler,
    run_conversation_screen,
)
from loushang.harnesstui.testing.input_playback import (
    default_conversation_state_snapshot,
)
from loushang.harnesstui.testing.ports import (
    ConversationLoopResultPayloadPort,
    ConversationPlaybackAppFactoryPort,
    ConversationStateSnapshotPort,
)
from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.playback import playback_artifacts_directory_from_env
from loushang.tui.terminal import TerminalOperation, TerminalSize
from loushang.tui.terminal_input import InputChunkReader

ScreenAppT = TypeVar("ScreenAppT", bound=ConversationScreenPort)


class ConversationScreenLoopRunnerPort(Protocol):
    """Async conversation runner invoked by screen-loop playback."""

    def __call__(
        self,
        *,
        app: ConversationScreenPort,
        stdin: TextIO,
        stdout: TextIO,
        handle_prompt: PromptHandler,
        handle_local: TextHandler | None,
        handle_steer: TextHandler | None,
        handle_followup: TextHandler | None,
        handle_surface_intent: SurfaceIntentHandler | None,
        on_abort: AbortHandler,
        should_exit: ShouldExit,
        is_local_command: LocalCommandPredicate | None,
        terminal_mode_factory: TerminalModeFactory | None,
        terminal_size_provider: TerminalSizeProvider,
        interruption_message: str,
        cancellation_message: str,
        input_router_factory: ConversationInputRouterFactoryPort | None,
        input_chunk_reader: InputChunkReader | None,
    ) -> Coroutine[object, object, int]: ...


@dataclass(frozen=True, slots=True)
class ScriptedInputChunk:
    """One raw terminal input chunk emitted relative to playback start."""

    at_seconds: float
    data: str

    def __post_init__(self) -> None:
        if self.at_seconds < 0:
            raise ValueError("scripted input time must be non-negative")


class NoTerminalMode:
    """Context manager used when playback does not exercise terminal setup."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> Literal[False]:
        return False


class TimedInputChunkReader:
    """Async test input source that emits chunks relative to its first read."""

    def __init__(
        self,
        chunks: Sequence[ScriptedInputChunk],
    ) -> None:
        self._chunks = tuple(chunks)
        self._index = 0
        self._started_at: float | None = None

    async def __call__(self, _stdin: TextIO) -> str:
        if self._index >= len(self._chunks):
            return ""
        loop = asyncio.get_running_loop()
        if self._started_at is None:
            self._started_at = loop.time()
        chunk = self._chunks[self._index]
        delay = chunk.at_seconds - (loop.time() - self._started_at)
        if delay > 0:
            await asyncio.sleep(delay)
        self._index += 1
        return chunk.data


@dataclass(frozen=True, slots=True)
class ConversationScreenLoopArtifacts:
    raw: Path
    text: Path
    state: Path


@dataclass(frozen=True, slots=True)
class ConversationScreenLoopPlaybackResult(Generic[ScreenAppT]):
    """Captured process output and neutral state from one screen-loop run."""

    exit_code: int
    output: str
    app: ScreenAppT
    state_snapshot: dict[str, object]
    result_payload: dict[str, object] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return strip_control_sequences(self.output)

    def assert_exit_code(self, expected: int) -> None:
        assert self.exit_code == expected

    def assert_text_contains(self, expected: str) -> None:
        assert expected in self.text

    def assert_text_not_contains(self, unexpected: str) -> None:
        assert unexpected not in self.text

    def assert_idle(self) -> None:
        assert self.app.state.running is False

    def assert_running(self) -> None:
        assert self.app.state.running is True

    def assert_pending_steers(self, *expected: str) -> None:
        assert self.app.state.pending_steers == list(expected)

    def assert_pending_followups(self, *expected: str) -> None:
        assert self.app.state.pending_followups == list(expected)

    def assert_composer_text(self, expected: str) -> None:
        assert self.app.composer.value == expected

    def assert_no_clear_screen(self) -> None:
        assert TerminalOperation.clear_screen().serialize() not in self.output
        assert TerminalOperation.clear_scrollback().serialize() not in self.output

    def write_artifacts(
        self,
        directory: str | Path,
        *,
        basename: str = "conversation-screen-loop",
    ) -> ConversationScreenLoopArtifacts:
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_path = output_dir / f"{basename}-raw.txt"
        text_path = output_dir / f"{basename}-text.txt"
        state_path = output_dir / f"{basename}-state.json"
        raw_path.write_text(self.output, encoding="utf-8")
        text_path.write_text(self.text, encoding="utf-8")
        state_path.write_text(
            json.dumps(self._artifact_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return ConversationScreenLoopArtifacts(
            raw=raw_path,
            text=text_path,
            state=state_path,
        )

    @contextmanager
    def write_artifacts_on_failure(
        self,
        directory: str | Path,
        *,
        basename: str = "conversation-screen-loop",
    ) -> Iterator[None]:
        try:
            yield
        except Exception:
            self.write_artifacts(directory, basename=basename)
            raise

    @contextmanager
    def write_artifacts_on_failure_from_env(
        self,
        *,
        basename: str = "conversation-screen-loop",
        env: Mapping[str, str] | None = None,
    ) -> Iterator[None]:
        try:
            yield
        except Exception:
            if directory := playback_artifacts_directory_from_env(env):
                self.write_artifacts(directory, basename=basename)
            raise

    def _artifact_payload(self) -> dict[str, object]:
        return {
            "exit_code": self.exit_code,
            "conversation": self.state_snapshot,
            **self.result_payload,
        }


class ConversationScreenLoopPlayback(Generic[ScreenAppT]):
    """Run a real conversation screen loop against scripted TTY chunks."""

    def __init__(
        self,
        *,
        app_factory: ConversationPlaybackAppFactoryPort[ScreenAppT],
        interruption_message: str,
        cancellation_message: str,
        width: int = 80,
        height: int = 24,
        now: float = 0.0,
        runner: ConversationScreenLoopRunnerPort = run_conversation_screen,
        input_router_factory: ConversationInputRouterFactoryPort | None = None,
        state_snapshot: ConversationStateSnapshotPort[ScreenAppT] | None = None,
        result_payload: ConversationLoopResultPayloadPort[ScreenAppT] | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.now = now
        self.interruption_message = interruption_message
        self.cancellation_message = cancellation_message
        self._runner = runner
        self._input_router_factory = input_router_factory
        self._state_snapshot = state_snapshot or default_conversation_state_snapshot
        self._result_payload = result_payload
        self.app = app_factory(now=lambda: self.now)

    def advance_time(self, seconds: float) -> Self:
        self.now += max(0.0, seconds)
        return self

    def run(
        self,
        *chunks: ScriptedInputChunk | tuple[float, str],
        handle_prompt: PromptHandler | None = None,
        handle_local: TextHandler | None = None,
        handle_steer: TextHandler | None = None,
        handle_followup: TextHandler | None = None,
        handle_surface_intent: SurfaceIntentHandler | None = None,
        on_abort: AbortHandler | None = None,
        should_exit: ShouldExit | None = None,
        is_local_command: LocalCommandPredicate | None = None,
        terminal_mode_factory: TerminalModeFactory | None = None,
    ) -> ConversationScreenLoopPlaybackResult[ScreenAppT]:
        scripted_chunks = tuple(_coerce_chunk(chunk) for chunk in chunks)
        stdout = StringIO()
        stdin = StringIO("")
        input_chunk_reader = (
            TimedInputChunkReader(scripted_chunks) if scripted_chunks else None
        )
        exit_code: int = asyncio.run(
            self._runner(
                app=self.app,
                stdin=stdin,
                stdout=stdout,
                handle_prompt=handle_prompt or _ignore_text,
                handle_local=handle_local,
                handle_steer=handle_steer,
                handle_followup=handle_followup,
                handle_surface_intent=handle_surface_intent,
                on_abort=on_abort or _ignore_abort,
                should_exit=should_exit or (lambda _text: False),
                is_local_command=is_local_command,
                terminal_mode_factory=terminal_mode_factory
                or (lambda _stdin, _stdout: NoTerminalMode()),
                terminal_size_provider=lambda: TerminalSize(
                    columns=self.width,
                    rows=self.height,
                ),
                interruption_message=self.interruption_message,
                cancellation_message=self.cancellation_message,
                input_router_factory=self._input_router_factory,
                input_chunk_reader=input_chunk_reader,
            )
        )
        state = dict(self._state_snapshot(self.app))
        payload = (
            dict(self._result_payload(exit_code, self.app))
            if self._result_payload is not None
            else {}
        )
        return ConversationScreenLoopPlaybackResult(
            exit_code=exit_code,
            output=stdout.getvalue(),
            app=self.app,
            state_snapshot=state,
            result_payload=payload,
        )


@dataclass(slots=True)
class ConversationScreenLoopScenario(Generic[ScreenAppT]):
    """Fluent timed-input recipe around a configured loop playback."""

    playback: ConversationScreenLoopPlayback[ScreenAppT]
    _time: float = 0.0
    _chunks: list[ScriptedInputChunk] = field(default_factory=list)

    @property
    def app(self) -> ScreenAppT:
        return self.playback.app

    def with_pending_steers(self, *texts: str) -> Self:
        for text in texts:
            self.app.queue_steer(text)
        return self

    def with_pending_followups(self, *texts: str) -> Self:
        for text in texts:
            self.app.queue_followup(text)
        return self

    def with_composer_text(self, text: str) -> Self:
        self.app.composer.set_text(text)
        return self

    def type_text(self, text: str) -> Self:
        self._chunks.append(ScriptedInputChunk(self._time, text))
        return self

    def type_chars(self, text: str) -> Self:
        for character in text:
            self._chunks.append(ScriptedInputChunk(self._time, character))
        return self

    def enter(self) -> Self:
        return self.key("\r")

    def escape(self) -> Self:
        return self.key("\x1b")

    def ctrl_c(self) -> Self:
        return self.key("\x03")

    def key(self, raw: str) -> Self:
        self._chunks.append(ScriptedInputChunk(self._time, raw))
        return self

    def wait(self, seconds: float) -> Self:
        self._time += max(0.0, seconds)
        return self

    def end_input(self) -> Self:
        self._chunks.append(ScriptedInputChunk(self._time, ""))
        return self

    def run(
        self,
        *,
        handle_prompt: PromptHandler | None = None,
        handle_local: TextHandler | None = None,
        handle_steer: TextHandler | None = None,
        handle_followup: TextHandler | None = None,
        handle_surface_intent: SurfaceIntentHandler | None = None,
        on_abort: AbortHandler | None = None,
        should_exit: ShouldExit | None = None,
        is_local_command: LocalCommandPredicate | None = None,
        terminal_mode_factory: TerminalModeFactory | None = None,
    ) -> ConversationScreenLoopPlaybackResult[ScreenAppT]:
        return self.playback.run(
            *self._chunks,
            handle_prompt=handle_prompt,
            handle_local=handle_local,
            handle_steer=handle_steer,
            handle_followup=handle_followup,
            handle_surface_intent=handle_surface_intent,
            on_abort=on_abort,
            should_exit=should_exit,
            is_local_command=is_local_command,
            terminal_mode_factory=terminal_mode_factory,
        )


def _coerce_chunk(
    chunk: ScriptedInputChunk | tuple[float, str],
) -> ScriptedInputChunk:
    if isinstance(chunk, ScriptedInputChunk):
        return chunk
    at_seconds, data = chunk
    return ScriptedInputChunk(at_seconds=at_seconds, data=data)


def _ignore_text(_text: str) -> None:
    return None


def _ignore_abort() -> None:
    return None


__all__ = [
    "ConversationScreenLoopArtifacts",
    "ConversationScreenLoopPlayback",
    "ConversationScreenLoopPlaybackResult",
    "ConversationScreenLoopRunnerPort",
    "ConversationScreenLoopScenario",
    "NoTerminalMode",
    "ScriptedInputChunk",
    "TimedInputChunkReader",
]
