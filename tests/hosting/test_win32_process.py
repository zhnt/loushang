from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

import loushang.hosting._win32_process as win32_process
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


def test_win32_named_job_collision_refuses_before_mutating_existing_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _CtypesWin32Api.__new__(_CtypesWin32Api)
    closed: list[int] = []
    name = "Global\\LoushangWorker-" + "a" * 64
    api._CreateJobObjectW = lambda security, observed: 41 if observed == name else 0
    api._SetInformationJobObject = lambda *arguments: pytest.fail(
        "Existing Job limits must not be changed"
    )
    api.close_handle = closed.append  # type: ignore[method-assign]
    monkeypatch.setattr(win32_process, "_last_error", lambda: 183)

    with pytest.raises(OSError, match="already exists"):
        api._create_job(name=name)

    assert closed == [41]


def test_win32_named_job_absence_is_read_only_and_denials_are_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _CtypesWin32Api.__new__(_CtypesWin32Api)
    name = "Global\\LoushangWorker-" + "b" * 64
    closed: list[int] = []
    observed: list[tuple[int, bool, str]] = []

    def open_job(access: int, inherited: bool, observed_name: str) -> int:
        observed.append((access, inherited, observed_name))
        return 0

    api._OpenJobObjectW = open_job
    api.close_handle = closed.append  # type: ignore[method-assign]
    monkeypatch.setattr(win32_process, "_last_error", lambda: 2)
    assert api.named_worker_job_absent(name)
    assert observed == [(4, False, name)]
    assert closed == []

    monkeypatch.setattr(win32_process, "_last_error", lambda: 5)
    with pytest.raises(OSError):
        api.named_worker_job_absent(name)
    assert closed == []

    api._OpenJobObjectW = lambda access, inherited, observed_name: 42
    assert not api.named_worker_job_absent(name)
    assert closed == [42]


@pytest.mark.skipif(os.name != "nt", reason="Windows-native Job contract")
def test_win32_native_named_worker_job_observation_and_collision() -> None:
    api = _CtypesWin32Api()
    name = "Global\\LoushangWorker-" + hashlib.sha256(os.urandom(32)).hexdigest()
    assert api.named_worker_job_absent(name)
    job = api._create_job(name=name)
    try:
        assert not api.named_worker_job_absent(name)
        with pytest.raises(OSError, match="already exists"):
            api._create_job(name=name)
        assert not api.named_worker_job_absent(name)
    finally:
        api.close_handle(job)
    assert api.named_worker_job_absent(name)


@pytest.mark.skipif(os.name != "nt", reason="Windows-native Job contract")
def test_win32_native_named_worker_job_disappears_after_owner_crash() -> None:
    api = _CtypesWin32Api()
    name = "Global\\LoushangWorker-" + hashlib.sha256(os.urandom(32)).hexdigest()
    script = (
        "import os, sys\n"
        "from loushang.hosting._win32_process import _CtypesWin32Api\n"
        "_CtypesWin32Api()._create_job(name=sys.argv[1])\n"
        "print('created', flush=True)\n"
        "sys.stdin.buffer.read(1)\n"
        "os._exit(7)\n"
    )
    process = subprocess.Popen(
        (sys.executable, "-c", script, name),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdin is not None
        assert process.stderr is not None
        assert process.stdout.readline() == "created\n", process.stderr.read()
        assert not api.named_worker_job_absent(name)
        process.stdin.write("x")
        process.stdin.flush()
        assert process.wait(timeout=20) == 7, process.stderr.read()
        assert api.named_worker_job_absent(name)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=20)


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
