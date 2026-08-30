"""Session composition adapter for durable command-output artifacts."""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.harness.artifacts import (
    ArtifactStoreError,
    SessionBlobRef,
    SessionBlobStore,
    prepare_private_artifact_directory,
    read_stable_artifact_source,
    resolve_session_blob_data_root,
)
from loushang.harness.workspace.exec import (
    ExecRequest,
    ExecResult,
    ExecService,
    ExecUpdateCallback,
)


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
    ) -> None:
        if isinstance(delegate, SessionOutputPersistingExecService):
            raise TypeError("session output persistence cannot wrap itself")
        super().__init__(execution_profile=getattr(delegate, "execution_profile", None))
        self._delegate = delegate
        self._store = SessionBlobStore(
            resolve_session_blob_data_root(session_dir),
            session_id,
        )
        self._temporary_root = prepare_private_artifact_directory(
            temporary_root or resolve_platform_paths().temporary
        )

    async def execute(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
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
) -> ExecService:
    """Bind output persistence only for durable Product sessions."""

    if not persist or isinstance(delegate, SessionOutputPersistingExecService):
        return delegate
    return SessionOutputPersistingExecService(
        delegate,
        session_dir=session_dir,
        session_id=session_id,
        temporary_root=temporary_root,
    )


__all__ = [
    "SessionOutputPersistingExecService",
    "persist_session_command_outputs",
]
