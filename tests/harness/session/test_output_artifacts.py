from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.artifacts import ArtifactRef, SessionBlobRef, SessionBlobStore
from loushang.harness.session.output_artifacts import (
    SessionOutputPersistingExecService,
)
from loushang.harness.tools.workspace import create_bash_tool_definition
from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
from loushang.harness.workspace.exec import ExecRequest, ExecResult, ExecService


class _CapturedOutputService(ExecService):
    def __init__(
        self,
        *,
        outside_path: Path | None = None,
        exit_code: int = 0,
        timed_out: bool = False,
        cancelled: bool = False,
    ) -> None:
        super().__init__()
        self.outside_path = outside_path
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.cancelled = cancelled
        self.seen_artifact_dir: Path | None = None

    async def execute(self, request, *, signal=None, on_update=None):
        del signal, on_update
        assert request.artifact_dir is not None
        self.seen_artifact_dir = Path(request.artifact_dir)
        stdout_path = self.outside_path or self.seen_artifact_dir / "stdout.log"
        stderr_path = self.seen_artifact_dir / "stderr.log"
        stdout_path.write_bytes(b"complete stdout\n")
        stderr_path.write_bytes(b"complete stderr\n")
        return ExecResult(
            exit_code=self.exit_code,
            timed_out=self.timed_out,
            cancelled=self.cancelled,
            stdout="stdout preview\n",
            stderr="stderr preview\n",
            stdout_truncated=True,
            stderr_truncated=True,
            stdout_artifact_path=str(stdout_path),
            stderr_artifact_path=str(stderr_path),
        )


class _ReferencedOutputService(ExecService):
    def __init__(
        self,
        *,
        stdout_ref: ArtifactRef | SessionBlobRef | None = None,
        stderr_ref: ArtifactRef | SessionBlobRef | None = None,
    ) -> None:
        super().__init__()
        self.stdout_ref = stdout_ref
        self.stderr_ref = stderr_ref

    async def execute(self, request, *, signal=None, on_update=None):
        del signal, on_update
        assert request.artifact_dir is not None
        scratch = Path(request.artifact_dir)
        stdout_path = scratch / "stdout.log"
        stderr_path = scratch / "stderr.log"
        stdout_path.write_bytes(b"new stdout\n")
        stderr_path.write_bytes(b"new stderr\n")
        return ExecResult(
            exit_code=0,
            stdout_artifact_path=str(stdout_path),
            stderr_artifact_path=str(stderr_path),
            stdout_artifact_ref=self.stdout_ref,
            stderr_artifact_ref=self.stderr_ref,
        )


def test_session_output_service_promotes_both_streams_without_paths(
    tmp_path,
) -> None:
    delegate = _CapturedOutputService()
    service = SessionOutputPersistingExecService(
        delegate,
        session_dir=tmp_path / "data" / "sessions",
        session_id="session-output",
        temporary_root=tmp_path / "runtime" / "tmp",
    )

    result = asyncio.run(service.execute(ExecRequest(command=("echo", "hello"))))

    assert result.stdout_artifact_path is None
    assert result.stderr_artifact_path is None
    assert result.artifact_retention_error is None
    assert result.stdout_artifact_ref is not None
    assert result.stderr_artifact_ref is not None
    store = SessionBlobStore(tmp_path / "data", "session-output")
    assert store.read_bytes(result.stdout_artifact_ref) == b"complete stdout\n"
    assert store.read_bytes(result.stderr_artifact_ref) == b"complete stderr\n"
    assert delegate.seen_artifact_dir is not None
    assert not delegate.seen_artifact_dir.exists()


def test_session_output_service_rejects_a_path_outside_bound_scratch(
    tmp_path,
) -> None:
    outside = tmp_path / "outside.log"
    service = SessionOutputPersistingExecService(
        _CapturedOutputService(outside_path=outside),
        session_dir=tmp_path / "data" / "sessions",
        session_id="session-output",
        temporary_root=tmp_path / "runtime" / "tmp",
    )

    result = asyncio.run(service.execute(ExecRequest(command=("echo", "hello"))))

    assert result.stdout_artifact_ref is None
    assert result.stderr_artifact_ref is None
    assert result.stdout_artifact_path is None
    assert result.stderr_artifact_path is None
    assert result.artifact_retention_error == (
        "command output was not retained (ArtifactSourceRejected)"
    )
    assert not SessionBlobStore(tmp_path / "data", "session-output").root.exists()


@pytest.mark.parametrize("existing_role", ["stdout", "stderr"])
def test_session_output_service_completes_mixed_current_session_refs(
    tmp_path,
    existing_role,
) -> None:
    store = SessionBlobStore(tmp_path / "data", "session-output")
    existing = store.put_bytes(
        b"existing stream\n",
        logical_name=f"command-output/{existing_role}-existing.log",
        kind=f"command-{existing_role}",
        media_type="text/plain",
    )
    service = SessionOutputPersistingExecService(
        _ReferencedOutputService(
            stdout_ref=existing if existing_role == "stdout" else None,
            stderr_ref=existing if existing_role == "stderr" else None,
        ),
        session_dir=tmp_path / "data" / "sessions",
        session_id="session-output",
        temporary_root=tmp_path / "runtime" / "tmp",
    )

    result = asyncio.run(service.execute(ExecRequest(command=("true",))))

    assert result.artifact_retention_error is None
    assert result.stdout_artifact_ref is not None
    assert result.stderr_artifact_ref is not None
    assert result.stdout_artifact_path is None
    assert result.stderr_artifact_path is None
    expected_stdout = (
        b"existing stream\n" if existing_role == "stdout" else b"new stdout\n"
    )
    expected_stderr = (
        b"existing stream\n" if existing_role == "stderr" else b"new stderr\n"
    )
    assert store.read_bytes(result.stdout_artifact_ref) == expected_stdout
    assert store.read_bytes(result.stderr_artifact_ref) == expected_stderr


@pytest.mark.parametrize("reference_kind", ["run", "foreign"])
def test_session_output_service_rejects_non_owned_references(
    tmp_path,
    reference_kind,
) -> None:
    if reference_kind == "foreign":
        invalid_reference: ArtifactRef | SessionBlobRef = SessionBlobStore(
            tmp_path / "data", "other-session"
        ).put_bytes(
            b"foreign",
            logical_name="command-output/stdout.log",
            kind="command-stdout",
            media_type="text/plain",
        )
        expected_error = "ArtifactSourceRejected"
    else:
        invalid_reference = ArtifactRef(
            artifact_id="run-artifact",
            logical_name="command-output/stdout.log",
            kind="command-stdout",
            media_type="text/plain",
            disclosure="private",
            size_bytes=3,
            sha256="a" * 64,
            created_at=1.0,
        )
        expected_error = "ArtifactStoreError"
    service = SessionOutputPersistingExecService(
        _ReferencedOutputService(stdout_ref=invalid_reference),
        session_dir=tmp_path / "data" / "sessions",
        session_id="session-output",
        temporary_root=tmp_path / "runtime" / "tmp",
    )

    result = asyncio.run(service.execute(ExecRequest(command=("true",))))

    assert result.stdout_artifact_ref is None
    assert result.stderr_artifact_ref is None
    assert result.stdout_artifact_path is None
    assert result.stderr_artifact_path is None
    assert result.artifact_retention_error == (
        f"command output was not retained ({expected_error})"
    )


def test_session_output_service_retains_failed_command_output_without_paths(
    tmp_path,
) -> None:
    delegate = _CapturedOutputService(exit_code=7)
    service = SessionOutputPersistingExecService(
        delegate,
        session_dir=tmp_path / "data" / "sessions",
        session_id="session-output",
        temporary_root=tmp_path / "runtime" / "tmp",
    )

    result = asyncio.run(service.execute(ExecRequest(command=("false",))))

    assert result.exit_code == 7
    assert result.stdout_artifact_ref is not None
    assert result.stderr_artifact_ref is not None
    assert result.stdout_artifact_path is None
    assert result.stderr_artifact_path is None
    store = SessionBlobStore(tmp_path / "data", "session-output")
    assert store.read_bytes(result.stdout_artifact_ref) == b"complete stdout\n"
    assert store.read_bytes(result.stderr_artifact_ref) == b"complete stderr\n"


@pytest.mark.parametrize(
    ("state", "expected"),
    [("timed_out", (True, False)), ("cancelled", (False, True))],
)
def test_session_output_service_retains_timeout_and_cancel_results(
    tmp_path,
    state,
    expected,
) -> None:
    service = SessionOutputPersistingExecService(
        _CapturedOutputService(**{state: True}),
        session_dir=tmp_path / "data" / "sessions",
        session_id="session-output",
        temporary_root=tmp_path / "runtime" / "tmp",
    )

    result = asyncio.run(service.execute(ExecRequest(command=("slow",))))

    assert (result.timed_out, result.cancelled) == expected
    assert isinstance(result.stdout_artifact_ref, SessionBlobRef)
    assert isinstance(result.stderr_artifact_ref, SessionBlobRef)


def test_session_output_service_cleans_scratch_after_task_cancellation(tmp_path) -> None:
    class CancellingService(ExecService):
        scratch: Path | None = None

        async def execute(self, request, *, signal=None, on_update=None):
            del signal, on_update
            assert request.artifact_dir is not None
            self.scratch = Path(request.artifact_dir)
            (self.scratch / "stdout.log").write_bytes(b"partial")
            raise asyncio.CancelledError

    delegate = CancellingService()
    service = SessionOutputPersistingExecService(
        delegate,
        session_dir=tmp_path / "data" / "sessions",
        session_id="session-output",
        temporary_root=tmp_path / "runtime" / "tmp",
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.execute(ExecRequest(command=("cancel",))))

    assert delegate.scratch is not None
    assert not delegate.scratch.exists()
    assert not SessionBlobStore(tmp_path / "data", "session-output").root.exists()


def test_failed_bash_exposes_retained_stream_refs_as_pathless_error_details(
    tmp_path,
) -> None:
    service = SessionOutputPersistingExecService(
        _CapturedOutputService(exit_code=7),
        session_dir=tmp_path / "data" / "sessions",
        session_id="session-output",
        temporary_root=tmp_path / "runtime" / "tmp",
    )
    tool = wrap_tool_definition(create_bash_tool_definition(exec_service=service))

    with pytest.raises(RuntimeError, match="exited with code 7") as caught:
        asyncio.run(
            tool.execute(
                "failed-output",
                {"command": ["false"], "cwd": str(tmp_path)},
            )
        )

    details = caught.value.tool_result_details
    assert details["stdout_artifact_path"] is None
    assert details["stderr_artifact_path"] is None
    stdout_blob = details["stdout_blob"]
    stderr_blob = details["stderr_blob"]
    store = SessionBlobStore(tmp_path / "data", "session-output")
    assert store.read_bytes(store.records[0]) == b"complete stdout\n"
    assert store.read_bytes(store.records[1]) == b"complete stderr\n"
    assert stdout_blob["blobId"] == store.records[0].blob_id
    assert stderr_blob["blobId"] == store.records[1].blob_id
