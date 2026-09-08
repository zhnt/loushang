"""Test supervisor's independent Windows Job, assigned before start admission."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path


def _venv_config(executable):
    candidates = [path for path in (
        executable.parent / "pyvenv.cfg", executable.parent.parent / "pyvenv.cfg",
    ) if path.is_file()]
    if len(candidates) > 1:
        raise ValueError("ambiguous controller venv configuration")
    return candidates[0] if candidates else None


def prepare_controller(executable, environment):
    """Avoid a redirector before Job admission; standard CPython layout only.

    Keep CPython's own venv executable override, not a PYTHONPATH substitute.
    All site processing remains behind the wrapper's -I -S/start gate.
    """
    target = Path(executable)
    if not target.is_absolute() or target.name.lower() != "python.exe" or not target.is_file():
        raise ValueError("controller requires an absolute CPython executable")
    config = _venv_config(target)
    base = target
    if config is not None:
        with config.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("controller venv configuration exceeds limit")
        homes = [value.strip() for line in raw.decode("utf-8").splitlines()
                 for key, separator, value in [line.partition("=")]
                 if separator and key.strip().lower() == "home"]
        if len(homes) != 1 or not Path(homes[0]).is_absolute():
            raise ValueError("controller venv requires one absolute home")
        base = Path(homes[0]) / "python.exe"
        if not base.is_file() or _venv_config(base) is not None:
            raise ValueError("controller base interpreter is missing or another venv")
    # Embedded/._pth distributions may re-enable site despite -S. Do not
    # launch them and then try to diagnose a pre-admission side effect.
    runtime = base.parent / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    if not runtime.is_file():
        raise ValueError("controller requires a matching standard CPython runtime")
    for directory in {target.parent, base.parent}:
        if any(path.name.lower().endswith("._pth") for path in directory.iterdir()):
            raise ValueError("controller does not admit ._pth interpreter layouts")
    clean = {key: value for key, value in environment.items()
             if key.lower() not in {"pythonexecutable", "__pyvenv_launcher__"}}
    if config is not None:
        clean["__PYVENV_LAUNCHER__"] = str(target)
    return str(base), clean


class Accounting(ctypes.Structure):
    _fields_ = [
        ("user", ctypes.c_longlong), ("kernel", ctypes.c_longlong),
        ("period_user", ctypes.c_longlong), ("period_kernel", ctypes.c_longlong),
        ("faults", wintypes.DWORD), ("total", wintypes.DWORD),
        ("active", wintypes.DWORD), ("terminated", wintypes.DWORD),
    ]


class EvidenceJob:
    def __init__(self, process):
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        self._create = api.CreateJobObjectW
        self._create.argtypes, self._create.restype = [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE
        self._assign = api.AssignProcessToJobObject
        self._assign.argtypes, self._assign.restype = [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL
        self._query = api.QueryInformationJobObject
        self._query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self._query.restype = wintypes.BOOL
        self._terminate = api.TerminateJobObject
        self._terminate.argtypes, self._terminate.restype = [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL
        self._close = api.CloseHandle
        self._close.argtypes, self._close.restype = [wintypes.HANDLE], wintypes.BOOL
        self.handle = self._create(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        # The wrapper is waiting for 'start'; no descendant can precede this
        # admission. Default Job limits do not permit breakaway. Hosting Jobs
        # nested below this Job do not escape its process accounting.
        if not self._assign(self.handle, int(process._handle)):
            error = ctypes.WinError(ctypes.get_last_error())
            self._close(self.handle)
            raise error

    def active(self):
        value = Accounting()
        if not self._query(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.active

    def terminate(self):
        if not self._terminate(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.active():
            raise RuntimeError("evidence Job still owns live processes")
        if not self._close(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())
