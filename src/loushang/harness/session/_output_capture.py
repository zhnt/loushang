"""Session-owned bounded capture admission and durable publication."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, replace

from loushang.harness.artifacts import (
    ArtifactStoreError,
    SessionBlobRef,
    SessionBlobStore,
)
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic
from loushang.harness.workspace.exec import (
    CapturedExecExecutor,
    CapturePreparation,
    ExecCaptureFactory,
    ExecCaptureLease,
    ExecRequest,
    ExecResult,
    ExecUpdateCallback,
    SealedExecCapture,
)

MAX_PENDING_CAPTURES = 8
MAX_PUBLICATION_BYTES = 128 * 1024 * 1024


@dataclass(eq=False)
class _PendingCapture:
    lease: ExecCaptureLease
    cleanup: asyncio.Task[None] | None = None


class SessionOutputCapture:
    def __init__(
        self, executor: CapturedExecExecutor, factory: ExecCaptureFactory,
        store: SessionBlobStore,
    ) -> None:
        self._executor = executor
        self._factory = factory
        self._store = store
        self._pending: list[_PendingCapture] = []
        self._active: set[asyncio.Task[object]] = set()
        self._idle = asyncio.Event()
        self._idle.set()
        self._closing = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def _require_loop(self) -> None:
        current = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = current
        elif self._loop is not current:
            raise RuntimeError("Session output capture belongs to another event loop")

    async def _cleanup(self, pending: _PendingCapture) -> None:
        task = pending.cleanup
        if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
            # Keep the original task even when a caller is cancelled. Bypass
            # external task factories at this resource-ownership boundary.
            task = asyncio.Task(pending.lease.close(), loop=asyncio.get_running_loop())
            pending.cleanup = task
        await _await_cancellation_atomic(task)
        if pending not in self._pending:
            return
        if pending.cleanup is not task:
            # A late waiter has no authority over another cleanup phase, even
            # if that phase has cleared its debt flag before returning a receipt.
            raise RuntimeError("temporary cleanup remains pending")
        if pending.lease.cleanup_pending:
            # A successful phase can still leave debt; a later close may
            # continue only through the original lease.
            if pending.cleanup is task:
                pending.cleanup = None
            raise RuntimeError("temporary cleanup remains pending")
        if pending in self._pending:
            self._pending.remove(pending)

    def fence(self) -> None:
        self._require_loop()
        self._closing = True

    @property
    def cleanup_pending(self) -> bool:
        self._require_loop()
        return bool(self._pending or self._active)

    async def close(self) -> None:
        if asyncio.current_task() in self._active:
            raise RuntimeError("capture cannot close from its own execution")
        self.fence()
        await self._idle.wait()
        failures: list[Exception] = []
        for pending in tuple(self._pending):
            try:
                await self._cleanup(pending)
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]

    async def execute(
        self, request: ExecRequest, *, signal: object | None,
        on_update: ExecUpdateCallback | None,
    ) -> ExecResult:
        self._require_loop()
        if self._closing:
            raise RuntimeError("Session output capture is closing")
        if len(self._pending) >= MAX_PENDING_CAPTURES:
            raise RuntimeError("Session output capture capacity exhausted")
        task = asyncio.current_task()
        assert task is not None
        if task in self._active:
            raise RuntimeError("recursive Session output capture is unavailable")
        pending = _PendingCapture(self._factory.new_capture())
        self._pending.append(pending)
        self._active.add(task)
        self._idle.clear()
        result: ExecResult | None = None
        try:
            prepared = await pending.lease.prepare()
            if not isinstance(prepared, CapturePreparation):
                raise TypeError("invalid capture preparation result")
            if self._closing:
                raise RuntimeError("Session output capture is closing")
            result = await self._executor.execute(
                request, capture=pending.lease, signal=signal, on_update=on_update,
            )
            result = replace(result, stdout_artifact_path=None, stderr_artifact_path=None,
                             stdout_artifact_ref=None, stderr_artifact_ref=None)
            sealed = await pending.lease.seal()
            if (prepared is CapturePreparation.READY and sealed is not None
                    and result.stdio_complete and not result.cancelled
                    and result.artifact_retention_error is None):
                try:
                    stdout, stderr = await self._publish(sealed)
                except (ArtifactStoreError, OSError, ValueError):
                    result = replace(result, artifact_retention_error="command output was not retained")
                else:
                    result = replace(result, stdout_artifact_ref=stdout, stderr_artifact_ref=stderr)
            else:
                result = replace(result, artifact_retention_error="command output was not retained")
        finally:
            try:
                await self._cleanup(pending)
            except Exception:
                if result is not None:
                    result = replace(result, artifact_cleanup_error="temporary_cleanup_pending")
            finally:
                self._active.remove(task)
                if not self._active:
                    self._idle.set()
        assert result is not None
        return result

    async def _publish(self, sealed: SealedExecCapture) -> tuple[SessionBlobRef, SessionBlobRef]:
        sources = (sealed.stdout, sealed.stderr)
        sizes = tuple(source.size_bytes for source in sources)
        limit = self._store.policy.max_blob_bytes
        if (any(type(size) is not int or size < 0 or size > limit for size in sizes)
                or sum(sizes) > MAX_PUBLICATION_BYTES):
            raise ArtifactStoreError("sealed output exceeds publication limit")
        blobs: list[tuple[SessionBlobRef, bytes]] = []
        for role, source, size in zip(("stdout", "stderr"), sources, sizes, strict=True):
            payload = await source.read_bytes(max_bytes=min(size, limit))
            if not isinstance(payload, bytes) or len(payload) != size:
                raise ArtifactStoreError("sealed output size changed")
            digest = hashlib.sha256(payload).hexdigest()
            blobs.append((SessionBlobRef(
                session_id=self._store.session_id, blob_id=digest,
                logical_name=f"command-output/{role}-{digest[:16]}.log",
                kind=f"command-{role}", media_type="text/plain; charset=utf-8",
                disclosure="private", size_bytes=size, sha256=digest,
                created_at=time.time(), source=f"command-output:{role}",
            ), payload))
        publication = self._store.import_blobs(blobs)
        stdout, stderr = publication.references
        return stdout, stderr
