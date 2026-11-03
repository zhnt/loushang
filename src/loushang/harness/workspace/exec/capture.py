"""Trusted local capture ports; no paths, storage authority or wire fields."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from .types import ExecOutputChunk, ExecRequest, ExecResult, ExecUpdateCallback

CAPTURE_BUFFER_BYTES = 100 * 1024
CAPTURE_READ_BYTES = 16 * 1024


class ExecCaptureSink(Protocol):
    async def append(self, chunk: ExecOutputChunk) -> None:
        """Accept ordered per-stream chunks, retaining native work on cancellation."""
        ...

    def stop_accepting(self) -> None:
        """Synchronously close write admission; do not close or refund storage."""
        ...


class CapturedExecExecutor(Protocol):
    async def execute(
        self, request: ExecRequest, *, capture: ExecCaptureSink,
        signal: object | None = None, on_update: ExecUpdateCallback | None = None,
    ) -> ExecResult: ...


class _CaptureSinkBorrow:
    """Close local admission even if the borrowed sink's callback is broken."""

    def __init__(self, sink: ExecCaptureSink) -> None:
        self._sink = sink
        self._stopped = False
        self.stop_error: BaseException | None = None

    async def append(self, chunk: ExecOutputChunk) -> None:
        if self._stopped:
            return
        try:
            await self._sink.append(chunk)
        except BaseException as error:
            self.stop_accepting()
            self.annotate(error)
            raise

    def stop_accepting(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            self._sink.stop_accepting()
        except BaseException as error:
            self.stop_error = error

    def annotate(self, primary: BaseException) -> None:
        if self.stop_error is not None and self.stop_error is not primary:
            primary.add_note(f"Capture admission close also failed: {self.stop_error!r}")


def bounded_capture_request(request: ExecRequest) -> ExecRequest:
    return replace(
        request, capture_full_output=False, retain_output_artifacts=False,
        artifact_dir=None,
        rolling_max_bytes=min(request.rolling_max_bytes, CAPTURE_BUFFER_BYTES),
        preview_max_bytes=max(1, min(request.preview_max_bytes, CAPTURE_BUFFER_BYTES)),
    )


def validate_capture(capture: ExecCaptureSink) -> None:
    if not callable(getattr(capture, "append", None)) or not callable(getattr(capture, "stop_accepting", None)):
        raise TypeError("execution requires an explicit capture sink")
