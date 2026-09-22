"""Local capture ownership ports, implemented by the composing storage owner.

These objects are never wire credentials or authority to delete a path. The
original lease owns all native work, including work whose waiter was cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .capture import ExecCaptureSink


class CapturePreparation(Enum):
    READY = "ready"
    # Only a settled, zero-effect logical capacity refusal permits this result.
    RETENTION_UNAVAILABLE = "retention_unavailable"


class SealedExecSource(Protocol):
    @property
    def size_bytes(self) -> int:
        """Immutable byte length recorded when the original lease was sealed."""
        ...

    async def read_bytes(self, *, max_bytes: int) -> bytes:
        """Read the original identity within the limit, verifying final length.

        Admit at most one read at a time per source. The lease retains native
        work on cancellation and rejects new reads once closing has started.
        """
        ...


@dataclass(frozen=True, slots=True)
class SealedExecCapture:
    """Both complete streams, including empty streams, from the same lease."""

    stdout: SealedExecSource
    stderr: SealedExecSource


class ExecCaptureLease(ExecCaptureSink, Protocol):
    async def prepare(self) -> CapturePreparation:
        """Join original preparation; unknown effects raise, never downgrade."""
        ...

    async def seal(self) -> SealedExecCapture | None:
        """Fence writes and settle native work; None means known retention loss.

        Repeated calls join the original seal, not another scan or publication.
        """
        ...

    @property
    def cleanup_pending(self) -> bool:
        """Whether original native work, deletion or reservation debt remains."""
        ...

    async def close(self) -> None:
        """Fence reads/writes, join admitted work and settle original cleanup.

        Never replay completed or unknown deletion. Success alone is not release:
        the caller must also observe cleanup_pending=False before dropping us.
        """
        ...


class ExecCaptureFactory(Protocol):
    def new_capture(self) -> ExecCaptureLease:
        """Allocate a fresh owner without IO, before the caller enrolls it."""
        ...
