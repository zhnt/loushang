from __future__ import annotations

import codecs
import ctypes
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path
from typing import Any, Self

from .base import BufferedTerminalDriver
from .protocol import TerminalProcessDiagnostics

_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_HANDLE_FLAG_INHERIT = 0x00000001
_STARTF_USESTDHANDLES = 0x00000100
_PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_STATUS_PENDING = 259
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_ERROR_BROKEN_PIPE = 109
_ERROR_OPERATION_ABORTED = 995
_ERROR_NO_DATA = 232


class _Coord(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _StartupInfo),
        ("lpAttributeList", wintypes.LPVOID),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class WindowsConPtyDriver(BufferedTerminalDriver):
    """Test-only ConPTY driver that owns every native handle and thread."""

    backend_name = "conpty"

    def __init__(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        columns: int,
        rows: int,
        api: _WindowsApi,
        pseudoconsole: wintypes.HANDLE,
        conpty_input_read: wintypes.HANDLE,
        conpty_output_write: wintypes.HANDLE,
        input_write: wintypes.HANDLE,
        output_read: wintypes.HANDLE,
        process_handle: wintypes.HANDLE,
        pid: int,
    ) -> None:
        super().__init__(
            args, cwd=cwd, env=env, columns=columns, rows=rows
        )
        self._api = api
        self._pseudoconsole: wintypes.HANDLE | None = pseudoconsole
        # CreatePseudoConsole borrows its pipe handles until ClosePseudoConsole.
        # They are distinct from the client-side handles used by write/read.
        self._conpty_input_read: wintypes.HANDLE | None = conpty_input_read
        self._conpty_output_write: wintypes.HANDLE | None = conpty_output_write
        self._input_write: wintypes.HANDLE | None = input_write
        self._output_read: wintypes.HANDLE | None = output_read
        self._process_handle: wintypes.HANDLE | None = process_handle
        self._pid = pid
        self._exit_status: int | None = None
        self._stop_reader = threading.Event()
        self._pseudoconsole_close_started = False
        self._pseudoconsole_close_error: BaseException | None = None
        self._pseudoconsole_close_thread: threading.Thread | None = None
        self._transport_finalized = False
        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"loushang-conpty-reader-{pid}",
            daemon=True,
        )
        self._reader.start()

    @classmethod
    def spawn(
        cls,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        columns: int,
        rows: int,
    ) -> Self:
        if os.name != "nt":
            raise RuntimeError("ConPTY is only available on Windows")
        if not args:
            raise ValueError("terminal argv must not be empty")
        if not cwd.is_dir():
            raise FileNotFoundError(f"terminal cwd was not found: {cwd}")
        if columns <= 0 or rows <= 0 or columns > 32767 or rows > 32767:
            raise ValueError("ConPTY dimensions must be between 1 and 32767")

        api = _WindowsApi()
        executable = _resolve_executable(str(args[0]), env)
        input_read, input_write = api.create_pipe()
        output_read, output_write = api.create_pipe()
        pseudoconsole = wintypes.HANDLE()
        process_info = _ProcessInformation()
        attribute_buffer: Any | None = None
        attribute_list: wintypes.LPVOID | None = None
        process_created = False
        try:
            api.create_pseudoconsole(
                columns=columns,
                rows=rows,
                input_read=input_read,
                output_write=output_write,
                result=pseudoconsole,
            )
            attribute_buffer, attribute_list = api.create_attribute_list(
                pseudoconsole
            )
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline(
                    [str(executable), *(str(arg) for arg in args[1:])]
                )
            )
            environment = ctypes.create_unicode_buffer(_environment_block(env))
            startup = _StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoEx)
            # Windows 7+ may inherit the parent's standard handles even when
            # bInheritHandles is false. Hosted CI redirects those handles to its
            # own pipes, so explicitly invalidate them and let ConPTY supply the
            # console endpoints to the child.
            startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = _INVALID_HANDLE_VALUE
            startup.StartupInfo.hStdOutput = _INVALID_HANDLE_VALUE
            startup.StartupInfo.hStdError = _INVALID_HANDLE_VALUE
            startup.lpAttributeList = attribute_list
            api.create_process(
                executable=executable,
                command_line=command_line,
                cwd=cwd,
                environment=environment,
                startup=startup,
                process_info=process_info,
            )
            process_created = True
        finally:
            if attribute_list is not None:
                api.delete_attribute_list(attribute_list)
            del attribute_buffer
            if process_info.hThread:
                api.close_handle(process_info.hThread)
            if not process_created:
                api.close_handle(input_write)
                api.close_handle(output_read)
                if pseudoconsole:
                    api.close_pseudoconsole(pseudoconsole)
                api.close_handle(input_read)
                api.close_handle(output_write)
                if process_info.hProcess:
                    api.close_handle(process_info.hProcess)

        return cls(
            args,
            cwd=cwd,
            env=env,
            columns=columns,
            rows=rows,
            api=api,
            pseudoconsole=pseudoconsole,
            conpty_input_read=input_read,
            conpty_output_write=output_write,
            input_write=input_write,
            output_read=output_read,
            process_handle=process_info.hProcess,
            pid=int(process_info.dwProcessId),
        )

    def write(self, text: str) -> None:
        data = text.encode("utf-8")
        with self._writer_lock:
            handle = self._input_write
            if self._closed or handle is None:
                raise RuntimeError("terminal driver is closed")
            offset = 0
            while offset < len(data):
                offset += self._api.write_file(handle, data[offset:])

    def resize(self, *, columns: int, rows: int) -> None:
        pseudoconsole = self._pseudoconsole
        if pseudoconsole is None or self._pseudoconsole_close_started:
            raise RuntimeError("terminal driver is closed")
        self._api.resize_pseudoconsole(pseudoconsole, columns, rows)
        self._columns = columns
        self._rows = rows
        self._responder.columns = columns
        self._responder.rows = rows

    def is_alive(self) -> bool:
        handle = self._process_handle
        if handle is None:
            return False
        result = self._api.wait_for_single_object(handle, 0)
        if result == _WAIT_TIMEOUT:
            return True
        if result == _WAIT_OBJECT_0:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, *, timeout: float) -> int:
        deadline = time.monotonic() + max(0.0, timeout)
        while self.is_alive():
            self._raise_reader_or_query_error()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"ConPTY process wait timed out:\n{self.diagnostics}")
            handle = self._process_handle
            assert handle is not None
            self._api.wait_for_single_object(
                handle, max(1, min(50, int(remaining * 1000)))
            )
        self._capture_exit_status()
        self._finalize_transport(deadline=deadline)
        return 0 if self._exit_status is None else self._exit_status

    def terminate_tree(self, *, timeout: float) -> None:
        if not self.is_alive():
            return
        deadline = time.monotonic() + max(0.0, timeout)
        taskkill = _trusted_taskkill_path(self._env)
        try:
            completed = subprocess.run(
                [str(taskkill), "/PID", str(self._pid), "/T", "/F"],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=max(0.01, deadline - time.monotonic()),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(f"taskkill timed out:\n{self.diagnostics}") from error
        self._termination = (
            f"taskkill rc={completed.returncode}; "
            f"stdout={completed.stdout[-500:]!r}; stderr={completed.stderr[-500:]!r}"
        )
        while self.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if self.is_alive():
            raise TimeoutError(f"ConPTY process tree remained alive:\n{self.diagnostics}")
        self._capture_exit_status()

    def close(self, *, timeout: float = 5.0) -> None:
        with self._close_lock:
            if self._closed:
                return
            deadline = time.monotonic() + max(0.0, timeout)
            failure: BaseException | None = None
            try:
                if self.is_alive():
                    self.terminate_tree(timeout=max(0.01, deadline - time.monotonic()))
                self._capture_exit_status()
                self._finalize_transport(deadline=deadline)
            except BaseException as error:
                failure = error
            finally:
                self._stop_reader.set()
                if self._output_read is not None:
                    with suppress(BaseException):
                        self._api.cancel_io(self._output_read)
                self._reader.join(timeout=max(0.0, deadline - time.monotonic()))
                self._close_output_handle()
                if self._process_handle is not None:
                    self._api.close_handle(self._process_handle)
                    self._process_handle = None
                self._closed = True
            if failure is not None:
                raise failure
            if self._reader.is_alive():
                raise TimeoutError(f"ConPTY reader did not stop:\n{self.diagnostics}")

    @property
    def diagnostics(self) -> TerminalProcessDiagnostics:
        base = self._base_diagnostics(
            pid=self._pid,
            exit_status=self._exit_status,
            reader_alive=self._reader.is_alive(),
        )
        close_error = self._pseudoconsole_close_error
        if close_error is None:
            return base
        return replace(
            base,
            reader_error=(
                f"ConPTY close {type(close_error).__name__}: {close_error}"
            ),
        )

    def _read_loop(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while not self._stop_reader.is_set():
                handle = self._output_read
                if handle is None:
                    break
                data = self._api.read_file(handle, 32768)
                if not data:
                    break
                text = decoder.decode(data, final=False)
                if text:
                    self._record_output(text)
            tail = decoder.decode(b"", final=True)
            if tail:
                self._record_output(tail)
        except BaseException as error:
            if not self._stop_reader.is_set():
                self._record_reader_error(error)
        finally:
            self._record_reader_done()

    def _capture_exit_status(self) -> None:
        if self._exit_status is not None or self._process_handle is None:
            return
        status = self._api.get_exit_code(self._process_handle)
        if status != _STATUS_PENDING:
            self._exit_status = status

    def _finalize_transport(self, *, deadline: float) -> None:
        if self._transport_finalized:
            return
        self._close_input_handle()
        self._start_pseudoconsole_close()
        self._reader.join(timeout=max(0.0, deadline - time.monotonic()))
        closer = self._pseudoconsole_close_thread
        if closer is not None:
            closer.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._reader.is_alive() or (closer is not None and closer.is_alive()):
            raise TimeoutError(
                "ConPTY output/close lifecycle exceeded its deadline:\n"
                f"{self.diagnostics}"
            )
        if self._pseudoconsole_close_error is not None:
            raise RuntimeError("ClosePseudoConsole failed") from self._pseudoconsole_close_error
        self._close_output_handle()
        self._transport_finalized = True

    def _start_pseudoconsole_close(self) -> None:
        if self._pseudoconsole_close_started:
            return
        self._pseudoconsole_close_started = True
        pseudoconsole = self._pseudoconsole
        if pseudoconsole is None:
            return

        def close_pseudoconsole() -> None:
            try:
                self._api.close_pseudoconsole(pseudoconsole)
            except BaseException as error:
                self._pseudoconsole_close_error = error
            finally:
                self._pseudoconsole = None
                try:
                    self._close_conpty_pipe_handles()
                except BaseException as error:
                    if self._pseudoconsole_close_error is None:
                        self._pseudoconsole_close_error = error

        self._pseudoconsole_close_thread = threading.Thread(
            target=close_pseudoconsole,
            name=f"loushang-conpty-close-{self._pid}",
            daemon=True,
        )
        self._pseudoconsole_close_thread.start()

    def _close_conpty_pipe_handles(self) -> None:
        first_error: BaseException | None = None
        if self._conpty_input_read is not None:
            try:
                self._api.close_handle(self._conpty_input_read)
            except BaseException as error:
                first_error = error
            self._conpty_input_read = None
        if self._conpty_output_write is not None:
            try:
                self._api.close_handle(self._conpty_output_write)
            except BaseException as error:
                if first_error is None:
                    first_error = error
            self._conpty_output_write = None
        if first_error is not None:
            raise first_error

    def _close_input_handle(self) -> None:
        with self._writer_lock:
            if self._input_write is not None:
                self._api.close_handle(self._input_write)
                self._input_write = None

    def _close_output_handle(self) -> None:
        if self._output_read is not None:
            self._api.close_handle(self._output_read)
            self._output_read = None


class _WindowsApi:
    def __init__(self) -> None:
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self.CreatePseudoConsole = kernel32.CreatePseudoConsole
            self.ResizePseudoConsole = kernel32.ResizePseudoConsole
            self.ClosePseudoConsole = kernel32.ClosePseudoConsole
        except (AttributeError, OSError) as error:
            raise RuntimeError(
                "ConPTY requires Windows 10 1809/build 17763 or newer"
            ) from error
        self.CreatePipe = kernel32.CreatePipe
        self.SetHandleInformation = kernel32.SetHandleInformation
        self.InitializeProcThreadAttributeList = (
            kernel32.InitializeProcThreadAttributeList
        )
        self.UpdateProcThreadAttribute = kernel32.UpdateProcThreadAttribute
        self.DeleteProcThreadAttributeList = kernel32.DeleteProcThreadAttributeList
        self.CreateProcessW = kernel32.CreateProcessW
        self.WaitForSingleObject = kernel32.WaitForSingleObject
        self.GetExitCodeProcess = kernel32.GetExitCodeProcess
        self.CloseHandle = kernel32.CloseHandle
        self.ReadFile = kernel32.ReadFile
        self.WriteFile = kernel32.WriteFile
        self.CancelIoEx = kernel32.CancelIoEx
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self.CreatePseudoConsole.argtypes = [
            _Coord,
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self.CreatePseudoConsole.restype = wintypes.LONG
        self.ResizePseudoConsole.argtypes = [wintypes.HANDLE, _Coord]
        self.ResizePseudoConsole.restype = wintypes.LONG
        self.ClosePseudoConsole.argtypes = [wintypes.HANDLE]
        self.ClosePseudoConsole.restype = None
        self.CreatePipe.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self.CreatePipe.restype = wintypes.BOOL
        self.SetHandleInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.SetHandleInformation.restype = wintypes.BOOL
        self.InitializeProcThreadAttributeList.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        self.UpdateProcThreadAttribute.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.UpdateProcThreadAttribute.restype = wintypes.BOOL
        self.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
        self.DeleteProcThreadAttributeList.restype = None
        self.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(_StartupInfo),
            ctypes.POINTER(_ProcessInformation),
        ]
        self.CreateProcessW.restype = wintypes.BOOL
        self.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.WaitForSingleObject.restype = wintypes.DWORD
        self.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.GetExitCodeProcess.restype = wintypes.BOOL
        self.CloseHandle.argtypes = [wintypes.HANDLE]
        self.CloseHandle.restype = wintypes.BOOL
        self.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self.ReadFile.restype = wintypes.BOOL
        self.WriteFile.argtypes = self.ReadFile.argtypes
        self.WriteFile.restype = wintypes.BOOL
        self.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        self.CancelIoEx.restype = wintypes.BOOL

    def create_pipe(self) -> tuple[wintypes.HANDLE, wintypes.HANDLE]:
        read_handle = wintypes.HANDLE()
        write_handle = wintypes.HANDLE()
        if not self.CreatePipe(
            ctypes.byref(read_handle), ctypes.byref(write_handle), None, 0
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            for handle in (read_handle, write_handle):
                if not self.SetHandleInformation(handle, _HANDLE_FLAG_INHERIT, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close_handle(read_handle)
            self.close_handle(write_handle)
            raise
        return read_handle, write_handle

    def create_pseudoconsole(
        self,
        *,
        columns: int,
        rows: int,
        input_read: wintypes.HANDLE,
        output_write: wintypes.HANDLE,
        result: wintypes.HANDLE,
    ) -> None:
        status = self.CreatePseudoConsole(
            _Coord(columns, rows),
            input_read,
            output_write,
            0,
            ctypes.byref(result),
        )
        _raise_hresult(status, "CreatePseudoConsole")

    def resize_pseudoconsole(
        self, pseudoconsole: wintypes.HANDLE, columns: int, rows: int
    ) -> None:
        if columns <= 0 or rows <= 0 or columns > 32767 or rows > 32767:
            raise ValueError("ConPTY dimensions must be between 1 and 32767")
        _raise_hresult(
            self.ResizePseudoConsole(pseudoconsole, _Coord(columns, rows)),
            "ResizePseudoConsole",
        )

    def close_pseudoconsole(self, pseudoconsole: wintypes.HANDLE) -> None:
        self.ClosePseudoConsole(pseudoconsole)

    def create_attribute_list(
        self, pseudoconsole: wintypes.HANDLE
    ) -> tuple[Any, wintypes.LPVOID]:
        size = ctypes.c_size_t()
        self.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        attribute_list = ctypes.cast(buffer, wintypes.LPVOID)
        if not self.InitializeProcThreadAttributeList(
            attribute_list, 1, 0, ctypes.byref(size)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
            wintypes.LPVOID(pseudoconsole.value),
            ctypes.sizeof(pseudoconsole),
            None,
            None,
        ):
            self.DeleteProcThreadAttributeList(attribute_list)
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer, attribute_list

    def delete_attribute_list(self, attribute_list: wintypes.LPVOID) -> None:
        self.DeleteProcThreadAttributeList(attribute_list)

    def create_process(
        self,
        *,
        executable: Path,
        command_line: Any,
        cwd: Path,
        environment: Any,
        startup: _StartupInfoEx,
        process_info: _ProcessInformation,
    ) -> None:
        if not self.CreateProcessW(
            str(executable),
            command_line,
            None,
            None,
            False,
            _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT,
            ctypes.cast(environment, wintypes.LPVOID),
            str(cwd),
            ctypes.byref(startup.StartupInfo),
            ctypes.byref(process_info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait_for_single_object(self, handle: wintypes.HANDLE, timeout_ms: int) -> int:
        return int(self.WaitForSingleObject(handle, max(0, timeout_ms)))

    def get_exit_code(self, handle: wintypes.HANDLE) -> int:
        status = wintypes.DWORD()
        if not self.GetExitCodeProcess(handle, ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(status.value)

    def read_file(self, handle: wintypes.HANDLE, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        read = wintypes.DWORD()
        if not self.ReadFile(handle, buffer, size, ctypes.byref(read), None):
            error = ctypes.get_last_error()
            if error in {_ERROR_BROKEN_PIPE, _ERROR_OPERATION_ABORTED, _ERROR_NO_DATA}:
                return b""
            raise ctypes.WinError(error)
        return buffer.raw[: read.value]

    def write_file(self, handle: wintypes.HANDLE, data: bytes) -> int:
        if not data:
            return 0
        buffer = ctypes.create_string_buffer(data)
        written = wintypes.DWORD()
        if not self.WriteFile(
            handle, buffer, len(data), ctypes.byref(written), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if written.value == 0:
            raise OSError("ConPTY input pipe accepted zero bytes")
        return int(written.value)

    def cancel_io(self, handle: wintypes.HANDLE) -> None:
        if not self.CancelIoEx(handle, None):
            error = ctypes.get_last_error()
            if error != _ERROR_NOT_FOUND:
                raise ctypes.WinError(error)

    def close_handle(self, handle: wintypes.HANDLE) -> None:
        if handle and not self.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


_ERROR_NOT_FOUND = 1168


def _raise_hresult(status: int, operation: str) -> None:
    if status < 0:
        unsigned = ctypes.c_uint32(status).value
        raise OSError(f"{operation} failed with HRESULT 0x{unsigned:08X}")


def _environment_block(env: Mapping[str, str]) -> str:
    entries: list[str] = []
    seen: set[str] = set()
    for key, value in sorted(env.items(), key=lambda item: item[0].casefold()):
        folded = key.casefold()
        if folded in seen:
            continue
        if not key or "=" in key or "\0" in key or "\0" in value:
            raise ValueError(f"invalid Windows environment entry: {key!r}")
        seen.add(folded)
        entries.append(f"{key}={value}")
    return "\0".join(entries) + "\0\0"


def _resolve_executable(command: str, env: Mapping[str, str]) -> Path:
    candidate = Path(command)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    path = next(
        (value for key, value in env.items() if key.casefold() == "path"),
        None,
    )
    resolved = shutil.which(command, path=path)
    if resolved is None:
        raise FileNotFoundError(f"terminal executable was not found: {command}")
    return Path(resolved).resolve()


def _trusted_taskkill_path(env: Mapping[str, str]) -> Path:
    system_root = next(
        (value for key, value in env.items() if key.casefold() == "systemroot"),
        os.environ.get("SystemRoot", r"C:\Windows"),
    )
    taskkill = Path(system_root) / "System32" / "taskkill.exe"
    if not taskkill.is_file():
        raise FileNotFoundError(f"trusted taskkill.exe was not found: {taskkill}")
    return taskkill
