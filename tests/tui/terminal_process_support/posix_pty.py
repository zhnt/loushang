from __future__ import annotations

import codecs
import errno
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Self

from .base import BufferedTerminalDriver
from .protocol import TerminalProcessDiagnostics


class PosixPtyDriver(BufferedTerminalDriver):
    backend_name = "posix-pty"

    def __init__(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        columns: int,
        rows: int,
        master_fd: int,
        process: subprocess.Popen[bytes],
    ) -> None:
        super().__init__(
            args, cwd=cwd, env=env, columns=columns, rows=rows
        )
        self._master_fd = master_fd
        self._process = process
        self._stop_reader = threading.Event()
        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"loushang-posix-pty-reader-{process.pid}",
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
        if not args:
            raise ValueError("terminal argv must not be empty")
        master_fd, slave_fd = pty.openpty()
        try:
            _set_window_size(slave_fd, columns=columns, rows=rows)
            process = subprocess.Popen(
                [str(arg) for arg in args],
                cwd=cwd,
                env=dict(env),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
            )
        except BaseException:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)
        os.set_blocking(master_fd, False)
        return cls(
            args,
            cwd=cwd,
            env=env,
            columns=columns,
            rows=rows,
            master_fd=master_fd,
            process=process,
        )

    def write(self, text: str) -> None:
        with self._writer_lock:
            if self._closed:
                raise RuntimeError("terminal driver is closed")
            payload = text.encode("utf-8")
            offset = 0
            while offset < len(payload):
                offset += os.write(self._master_fd, payload[offset:])

    def resize(self, *, columns: int, rows: int) -> None:
        _set_window_size(self._master_fd, columns=columns, rows=rows)
        self._columns = columns
        self._rows = rows
        self._responder.columns = columns
        self._responder.rows = rows
        with _ignore_process_lookup():
            os.killpg(self._process.pid, signal.SIGWINCH)

    def is_alive(self) -> bool:
        return self._process.poll() is None

    def wait(self, *, timeout: float) -> int:
        try:
            status = self._process.wait(timeout=max(0.0, timeout))
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(f"terminal process wait timed out:\n{self.diagnostics}") from error
        self._wait_for_idle_output(timeout=min(1.0, max(0.1, timeout)))
        return status

    def terminate_tree(self, *, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        if not self.is_alive():
            return
        self._termination = "SIGTERM process group"
        with _ignore_process_lookup():
            os.killpg(self._process.pid, signal.SIGTERM)
        graceful_deadline = min(deadline, time.monotonic() + 0.5)
        while self.is_alive() and time.monotonic() < graceful_deadline:
            time.sleep(0.01)
        if self.is_alive():
            self._termination = "SIGKILL process group"
            with _ignore_process_lookup():
                os.killpg(self._process.pid, signal.SIGKILL)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"terminal process tree termination timed out:\n{self.diagnostics}")
        try:
            self._process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(
                f"terminal process tree termination timed out:\n{self.diagnostics}"
            ) from error

    def close(self, *, timeout: float = 5.0) -> None:
        with self._close_lock:
            if self._closed:
                return
            deadline = time.monotonic() + max(0.0, timeout)
            try:
                if self.is_alive():
                    self.terminate_tree(timeout=max(0.01, deadline - time.monotonic()))
                self._wait_for_idle_output(
                    timeout=max(0.01, min(0.5, deadline - time.monotonic()))
                )
            finally:
                self._stop_reader.set()
                with suppress(OSError):
                    os.close(self._master_fd)
                self._reader.join(timeout=max(0.0, deadline - time.monotonic()))
                self._closed = True
            if self._reader.is_alive():
                raise TimeoutError(f"POSIX PTY reader did not stop:\n{self.diagnostics}")

    @property
    def diagnostics(self) -> TerminalProcessDiagnostics:
        return self._base_diagnostics(
            pid=self._process.pid,
            exit_status=self._process.poll(),
            reader_alive=self._reader.is_alive(),
        )

    def _read_loop(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while not self._stop_reader.is_set():
                readable, _, _ = select.select([self._master_fd], [], [], 0.05)
                if not readable:
                    continue
                try:
                    chunk = os.read(self._master_fd, 65_536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                self._record_output(decoder.decode(chunk))
            tail = decoder.decode(b"", final=True)
            if tail:
                self._record_output(tail)
        except OSError as error:
            if not self._stop_reader.is_set() and error.errno not in {errno.EBADF}:
                self._record_reader_error(error)
        except BaseException as error:
            self._record_reader_error(error)
        finally:
            self._record_reader_done()


def _set_window_size(fd: int, *, columns: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


class _ignore_process_lookup:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        del traceback
        return exc_type is ProcessLookupError and isinstance(exc, ProcessLookupError)
