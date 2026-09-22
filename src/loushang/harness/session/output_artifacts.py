"""Session composition adapter for durable command-output artifacts."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AbstractContextManager, nullcontext
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.harness.artifacts import (
    ArtifactStoreError,
    SessionBlobRef,
    SessionBlobStore,
    prepare_private_artifact_directory,
    read_stable_artifact_source,
    resolve_session_blob_data_root,
    session_blob_authority_id,
)
from loushang.harness.workspace.exec import (
    ExecCaptureFactory,
    ExecRequest,
    ExecResult,
    ExecService,
    ExecUpdateCallback,
)

from ._output_capture import SessionOutputCapture

if TYPE_CHECKING:
    from loushang.harness.journal._rooted_io import RootedFileIO


class SessionOutputPersistingExecService(ExecService):
    """Capture full stream output into one durable Session authority.

    The delegate may expose temporary file paths in ``ExecResult``. This
    adapter binds their creation to a private scratch root, verifies and
    publishes the bytes, then clears every physical path before the result can
    cross the Session boundary.
    """

    def __init__(
        self,
        delegate: ExecService,
        *,
        session_dir: str | Path,
        session_id: str,
        temporary_root: str | Path | None = None,
        file_io: RootedFileIO | None = None,
        operation_scope: Callable[[], AbstractAsyncContextManager[None]] | None = None,
        initialization_scope: Callable[[], AbstractContextManager[None]] | None = None,
        capture_factory: ExecCaptureFactory | None = None,
    ) -> None:
        if isinstance(delegate, SessionOutputPersistingExecService):
            raise TypeError("session output persistence cannot wrap itself")
        if file_io is not None and (operation_scope is None or initialization_scope is None):
            raise ValueError("owned output persistence requires original operation scopes")
        super().__init__(execution_profile=getattr(delegate, "execution_profile", None))
        self._delegate = delegate
        self._capture_factory = capture_factory
        captured = delegate.capture_executor() if capture_factory is not None else None
        if capture_factory is not None and captured is None:
            raise TypeError("managed output persistence requires captured execution")
        self._file_io = file_io
        self._operation_scope = nullcontext if operation_scope is None else operation_scope
        with nullcontext() if initialization_scope is None else initialization_scope():
            self._store = SessionBlobStore(
                Path(session_dir).parent if file_io is not None else resolve_session_blob_data_root(session_dir),
                session_id, file_io=file_io,
            )
        self._capture = (
            SessionOutputCapture(captured, capture_factory, self._store)
            if captured is not None and capture_factory is not None else None
        )
        self._temporary_root = None if self._capture is not None else prepare_private_artifact_directory(
            temporary_root or resolve_platform_paths().temporary
        )

    def fence(self) -> None:
        if self._capture is not None:
            self._capture.fence()

    @property
    def cleanup_pending(self) -> bool:
        return self._capture is not None and self._capture.cleanup_pending

    async def close(self) -> None:
        if self._capture is not None:
            await self._capture.close()

    async def execute(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> ExecResult:
        async with self._operation_scope():
            if self._capture is not None:
                return await self._capture.execute(request, signal=signal, on_update=on_update)
            return await self._execute(request, signal=signal, on_update=on_update)

    async def _execute(
        self, request: ExecRequest, *, signal: object | None, on_update: ExecUpdateCallback | None,
    ) -> ExecResult:
        with TemporaryDirectory(
            prefix="session-output-",
            dir=self._temporary_root,
        ) as scratch_value:
            scratch = Path(scratch_value)
            result = await self._delegate.execute(
                replace(
                    request,
                    artifact_dir=str(scratch),
                    retain_output_artifacts=True,
                ),
                signal=signal,
                on_update=on_update,
            )
            try:
                stdout_ref, stderr_ref = self._publish_outputs(result, scratch)
            except (ArtifactStoreError, OSError, ValueError) as error:
                return replace(
                    result,
                    stdout_artifact_path=None,
                    stderr_artifact_path=None,
                    stdout_artifact_ref=None,
                    stderr_artifact_ref=None,
                    artifact_retention_error=(
                        f"command output was not retained ({error.__class__.__name__})"
                    ),
                )
            return replace(
                result,
                stdout_artifact_path=None,
                stderr_artifact_path=None,
                stdout_artifact_ref=stdout_ref,
                stderr_artifact_ref=stderr_ref,
            )

    def _publish_outputs(
        self,
        result: ExecResult,
        scratch: Path,
    ) -> tuple[SessionBlobRef | None, SessionBlobRef | None]:
        prepared: list[tuple[SessionBlobRef, bytes]] = []
        roles: list[str] = []
        retained: dict[str, SessionBlobRef] = {}
        for role, source_path, existing_reference in (
            (
                "stdout",
                result.stdout_artifact_path,
                result.stdout_artifact_ref,
            ),
            (
                "stderr",
                result.stderr_artifact_path,
                result.stderr_artifact_ref,
            ),
        ):
            if existing_reference is not None:
                if not isinstance(existing_reference, SessionBlobRef):
                    raise ArtifactStoreError(
                        "command output reference is not Session-owned"
                    )
                self._store.read_bytes(existing_reference)
                retained[role] = existing_reference
                continue
            if source_path is None:
                continue
            payload = read_stable_artifact_source(
                source_path,
                allowed_roots=(scratch,),
                max_bytes=self._store.policy.max_blob_bytes,
            )
            digest = hashlib.sha256(payload).hexdigest()
            prepared.append(
                (
                    SessionBlobRef(
                        session_id=self._store.session_id,
                        blob_id=digest,
                        logical_name=f"command-output/{role}-{digest[:16]}.log",
                        kind=f"command-{role}",
                        media_type="text/plain; charset=utf-8",
                        disclosure="private",
                        size_bytes=len(payload),
                        sha256=digest,
                        created_at=time.time(),
                        source=f"command-output:{role}",
                    ),
                    payload,
                )
            )
            roles.append(role)
        if not prepared:
            return retained.get("stdout"), retained.get("stderr")
        publication = self._store.import_blobs(prepared)
        by_role = {
            **retained,
            **dict(zip(roles, publication.references, strict=True)),
        }
        return by_role.get("stdout"), by_role.get("stderr")


def persist_session_command_outputs(
    delegate: ExecService,
    *,
    session_dir: str | Path,
    session_id: str,
    persist: bool,
    temporary_root: str | Path | None = None,
    file_io: RootedFileIO | None = None,
    operation_scope: Callable[[], AbstractAsyncContextManager[None]] | None = None,
    initialization_scope: Callable[[], AbstractContextManager[None]] | None = None,
    capture_factory: ExecCaptureFactory | None = None,
) -> ExecService:
    """Bind output persistence only for durable Product sessions."""

    if capture_factory is not None and not persist:
        raise ValueError("managed output persistence requires a durable Session")
    if (isinstance(delegate, SessionOutputPersistingExecService)
            and capture_factory is not None and delegate._capture_factory is not capture_factory):
        raise ValueError("command output adapter belongs to another capture authority")
    if (isinstance(delegate, SessionOutputPersistingExecService) and file_io is not None
            and (delegate._file_io is not file_io
                 or delegate._store.session_id != session_blob_authority_id(session_id))):
        raise ValueError("command output adapter belongs to another Session authority")
    if not persist or isinstance(delegate, SessionOutputPersistingExecService):
        return delegate
    return SessionOutputPersistingExecService(
        delegate,
        session_dir=session_dir,
        session_id=session_id,
        temporary_root=temporary_root,
        file_io=file_io, operation_scope=operation_scope, initialization_scope=initialization_scope,
        capture_factory=capture_factory,
    )


__all__ = [
    "SessionOutputPersistingExecService",
    "persist_session_command_outputs",
]
