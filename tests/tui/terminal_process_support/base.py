from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from .protocol import TerminalProcessDiagnostics
from .query_responder import TerminalQueryResponder


class BufferedTerminalDriver:
    backend_name = "unknown"
    _output_limit = 1_000_000

    def __init__(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        columns: int,
        rows: int,
    ) -> None:
        self._args = tuple(str(arg) for arg in args)
        self._cwd = cwd
        self._env = dict(env)
        self._columns = columns
        self._rows = rows
        self._condition = threading.Condition()
        self._output = ""
        self._last_output_at = time.monotonic()
        self._reader_error: BaseException | None = None
        self._reader_done = False
        self._closed = False
        self._close_lock = threading.Lock()
        self._writer_lock = threading.Lock()
        self._termination: str | None = None
        self._responder = TerminalQueryResponder(
            rows=rows,
            columns=columns,
            respond_to_cell_size=_env_flag(env, "LOUSHANG_TEST_RESPOND_CELL_SIZE"),
        )

    def __enter__(self):
        return self

    def __exit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> Literal[False]:
        del exc_type, exc, traceback
        self.close()
        return False

    @property
    def raw_output(self) -> str:
        with self._condition:
            return self._output

    def read_until(
        self, predicate: Callable[[str], bool], *, timeout: float
    ) -> str:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                output = self._output
                self._raise_reader_or_query_error()
                if predicate(output):
                    return output
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "terminal output predicate timed out:\n"
                        f"{self.diagnostics}"
                    )
                self._condition.wait(min(0.05, remaining))

    def _record_output(self, text: str) -> None:
        if not text:
            return
        with self._condition:
            self._output = (self._output + text)[-self._output_limit :]
            self._last_output_at = time.monotonic()
            self._condition.notify_all()
        for response in self._responder.feed(text):
            self.write(response)

    def _record_reader_error(self, error: BaseException) -> None:
        with self._condition:
            self._reader_error = error
            self._condition.notify_all()

    def _record_reader_done(self) -> None:
        with self._condition:
            self._reader_done = True
            self._condition.notify_all()

    def _wait_for_idle_output(self, *, timeout: float, idle: float = 0.1) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                self._raise_reader_or_query_error()
                now = time.monotonic()
                if self._reader_done or now - self._last_output_at >= idle:
                    return
                remaining = deadline - now
                if remaining <= 0:
                    raise TimeoutError(f"terminal tail drain timed out:\n{self.diagnostics}")
                self._condition.wait(min(idle, remaining))

    def _raise_reader_or_query_error(self) -> None:
        if self._reader_error is not None:
            raise RuntimeError("terminal reader failed") from self._reader_error
        if self._responder.unknown_queries:
            raise RuntimeError(
                "unsupported blocking terminal query: "
                + ", ".join(repr(item) for item in self._responder.unknown_queries)
            )

    def _base_diagnostics(
        self,
        *,
        pid: int | None,
        exit_status: int | None,
        reader_alive: bool,
    ) -> TerminalProcessDiagnostics:
        return TerminalProcessDiagnostics(
            backend=self.backend_name,
            pid=pid,
            argv=self._args,
            cwd=self._cwd,
            columns=self._columns,
            rows=self._rows,
            exit_status=exit_status,
            reader_alive=reader_alive,
            reader_error=(
                None
                if self._reader_error is None
                else f"{type(self._reader_error).__name__}: {self._reader_error}"
            ),
            unknown_queries=tuple(self._responder.unknown_queries),
            output_tail=self.raw_output[-4000:],
            termination=self._termination,
        )


def _env_flag(env: Mapping[str, str], name: str) -> bool:
    for key, value in env.items():
        if key.casefold() == name.casefold():
            return value == "1"
    return False
