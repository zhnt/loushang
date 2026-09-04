from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest

from loushang.hosting import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting._win32_process import (
    _PROCESS_INFORMATION,
    _CtypesWin32Api,
    _Win32AttributeList,
    _Win32SpawnHandles,
)


def _request(tmp_path: Path) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(sys.executable, "-c", "pass"),
        cwd=str(tmp_path.resolve()),
        effective_environment=tuple(os.environ.items()),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.PIPE,
            stdout=ProcessStdoutMode.PIPE,
            stderr=ProcessStderrMode.CAPTURE_TAIL,
        ),
    )


class _FaultingRawApi(_CtypesWin32Api):
    def __init__(self, failure_stage: str | None) -> None:
        self.failure_stage = failure_stage
        self.closed: list[int] = []
        self.deleted_attributes = 0
        self._failed_close_once = False
        self.inherited_handles: tuple[int, int, int] | None = None
        self._DeleteProcThreadAttributeList = self._delete_attributes
        self._CreateProcessW = self._create_process

    def _create_job(self) -> int:
        self._fail("job")
        return 1

    def _stdin_handles(
        self, request: ProcessLaunchRequest
    ) -> tuple[int, int | None]:
        self._fail("stdin")
        return 2, 3

    def _stdout_handles(
        self, request: ProcessLaunchRequest
    ) -> tuple[int, int | None]:
        self._fail("stdout")
        return 4, 5

    def _stderr_handles(
        self, request: ProcessLaunchRequest
    ) -> tuple[int, int | None]:
        self._fail("stderr")
        return 6, 7

    def _attribute_list(
        self, job: int, inherited_handles: tuple[int, int, int]
    ) -> _Win32AttributeList:
        self.inherited_handles = inherited_handles
        if self.failure_stage == "attributes":
            # This helper owns and deletes a partially initialized list before
            # it reports failure to the outer acquisition transaction.
            self.deleted_attributes += 1
            raise OSError("attributes")
        storage = ctypes.create_string_buffer(8)
        jobs = (ctypes.c_void_p * 1)(job)
        handles = (ctypes.c_void_p * 3)(*inherited_handles)
        return _Win32AttributeList(
            storage=storage,
            pointer=ctypes.cast(storage, ctypes.c_void_p),
            jobs=jobs,
            handles=handles,
        )

    def _create_process(self, *arguments: object) -> int:
        if self.failure_stage == "create_process":
            return 0
        information_pointer = arguments[-1]
        information = ctypes.cast(
            information_pointer,
            ctypes.POINTER(_PROCESS_INFORMATION),
        ).contents
        information.hProcess = 8
        information.hThread = 9
        return 1

    def close_handle(self, handle: int) -> None:
        if (
            self.failure_stage == "post_create_close"
            and handle == 2
            and not self._failed_close_once
        ):
            self._failed_close_once = True
            raise OSError("post-create child handle close")
        self.closed.append(handle)

    def _delete_attributes(self, pointer: ctypes.c_void_p) -> None:
        self.deleted_attributes += 1

    def _raise_last_error(self, operation: str) -> None:
        raise OSError(operation)

    def _fail(self, stage: str) -> None:
        if self.failure_stage == stage:
            raise OSError(stage)


@pytest.mark.parametrize(
    ("stage", "closed", "deleted"),
    (
        ("job", set(), 0),
        ("stdin", {1}, 0),
        ("stdout", {1, 2, 3}, 0),
        ("stderr", {1, 2, 3, 4, 5}, 0),
        ("attributes", {1, 2, 3, 4, 5, 6, 7}, 1),
        ("create_process", {1, 2, 3, 4, 5, 6, 7}, 1),
        ("post_create_close", set(range(1, 10)), 1),
    ),
)
def test_win32_spawn_fault_matrix_closes_every_acquired_handle(
    tmp_path: Path,
    stage: str,
    closed: set[int],
    deleted: int,
) -> None:
    api = _FaultingRawApi(stage)

    with pytest.raises(OSError):
        api.spawn(_request(tmp_path))

    assert set(api.closed) == closed
    assert api.deleted_attributes == deleted


def test_win32_success_transfers_only_parent_owner_handles(tmp_path: Path) -> None:
    api = _FaultingRawApi(None)

    handles = api.spawn(_request(tmp_path))

    assert handles.process == 8
    assert handles.job == 1
    assert handles.stdin_write == 3
    assert handles.stdout_read == 5
    assert handles.stderr_read == 7
    assert api.closed == [9, 2, 4, 6]
    assert api.deleted_attributes == 1


def test_win32_inherited_endpoint_handles_are_allowlisted_but_not_owned(
    tmp_path: Path,
) -> None:
    api = _FaultingRawApi(None)

    handles = api.spawn(_request(tmp_path), endpoint_handles=(20, 21))

    assert api.inherited_handles == (20, 21, 6)
    assert handles == _Win32SpawnHandles(8, 1, None, None, 7)
    assert api.closed == [9, 6]


def test_win32_failed_spawn_does_not_close_caller_owned_endpoint_handles(
    tmp_path: Path,
) -> None:
    api = _FaultingRawApi("create_process")

    with pytest.raises(OSError):
        api.spawn(_request(tmp_path), endpoint_handles=(20, 21))

    assert api.inherited_handles == (20, 21, 6)
    assert set(api.closed) == {1, 6, 7}


def test_win32_job_limit_failure_closes_new_job() -> None:
    api = _CtypesWin32Api.__new__(_CtypesWin32Api)
    closed: list[int] = []
    api._CreateJobObjectW = lambda security, name: 41
    api._SetInformationJobObject = lambda *arguments: 0
    api.close_handle = closed.append  # type: ignore[method-assign]

    with pytest.raises(OSError, match="SetInformationJobObject"):
        api._create_job()

    assert closed == [41]


def test_win32_pipe_allowlist_failure_closes_both_pipe_ends() -> None:
    api = _CtypesWin32Api.__new__(_CtypesWin32Api)
    closed: list[int] = []

    def create_pipe(
        read: object,
        write: object,
        security: object,
        size: int,
    ) -> int:
        del security, size
        ctypes.cast(read, ctypes.POINTER(ctypes.c_void_p)).contents.value = 51
        ctypes.cast(write, ctypes.POINTER(ctypes.c_void_p)).contents.value = 52
        return 1

    api._CreatePipe = create_pipe
    api._SetHandleInformation = lambda *arguments: 0
    api.close_handle = closed.append  # type: ignore[method-assign]

    with pytest.raises(OSError, match="SetHandleInformation"):
        api._pipe(child_reads=True)

    assert closed == [51, 52]
