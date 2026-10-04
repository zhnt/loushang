"""Read the actual Python images that execute the Windows LPAC backend.

This read grants no Worker authority. Product owns release approval, and the
Hosting capture must repeat the read before using an approved native plan.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path

from ._win32_process import _CtypesWin32Api

_MAX_IMAGE_BYTES = 64 * 1024 * 1024
_MAX_PACKAGE_BYTES = 128 * 1024 * 1024
_MAX_PACKAGE_MEMBERS = 8192
_CHUNK = 1024 * 1024
_PACKAGE_VERIFY_WORKERS = 8
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
WINDOWS_LPAC_BACKEND_CODE_MEMBERS = (
    "loushang/hosting/_win32_process.py",
    "loushang/hosting/_windows_process.py",
    "loushang/hosting/_windows_launch_preparation.py",
    "loushang/hosting/runtime.py",
    "loushang/harness/worker/_native_profile_bridge.py",
    "loushang/harness/worker/product_activation.py",
    "loushang/coding/package_product_worker_windows_provisioning.py",
    "loushang/coding/package_product_worker_windows_provisioning_journal.py",
)
WINDOWS_LPAC_PLATFORM_IMPORTS = (
    "ADVAPI32.DLL",
    "KERNEL32.DLL",
    "USERENV.DLL",
    "WS2_32.DLL",
)


@dataclass(frozen=True, slots=True)
class WindowsPythonHostImagesV1:
    python_executable_sha256: str
    python_runtime_dll_sha256: str


@dataclass(frozen=True, slots=True)
class WindowsBackendMaterialExpectationV1:
    """Product-neutral, bounded source and running-image expectation."""

    python_executable_sha256: str
    python_runtime_dll_sha256: str
    package_members: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or _DIGEST.fullmatch(value) is None
            for value in (
                self.python_executable_sha256,
                self.python_runtime_dll_sha256,
            )
        ):
            raise ValueError("Windows backend image expectation is invalid")
        if (
            type(self.package_members) is not tuple
            or not 1 <= len(self.package_members) <= _MAX_PACKAGE_MEMBERS
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not str
                or _DIGEST.fullmatch(item[1]) is None
                for item in self.package_members
            )
        ):
            raise ValueError("Windows backend source expectation is invalid")


def verify_windows_backend_material_expectation(
    expectation: WindowsBackendMaterialExpectationV1,
) -> None:
    """Recheck actual loaded backend material before native capture."""

    if os.name != "nt" or type(expectation) is not WindowsBackendMaterialExpectationV1:
        raise OSError("Windows backend material expectation is unavailable")
    images = capture_windows_python_host_images()
    if (
        images.python_executable_sha256 != expectation.python_executable_sha256
        or images.python_runtime_dll_sha256 != expectation.python_runtime_dll_sha256
    ):
        raise OSError("Windows backend Python images changed")
    verify_windows_loushang_installed_package_members(expectation.package_members)
    verify_windows_lpac_loaded_backend_sources(expectation.package_members)
    if capture_windows_python_host_images() != images:
        raise OSError("Windows backend Python images changed during capture")


def capture_windows_python_host_images() -> WindowsPythonHostImagesV1:
    """Capture the running executable and loaded Python DLL by native handle."""

    if os.name != "nt":
        raise OSError("Windows Python image capture requires Windows")
    executable = Path(sys.executable)
    runtime_dll = _loaded_python_runtime_dll_path()
    if executable == runtime_dll:
        raise OSError("Windows Python executable and runtime DLL are ambiguous")
    return WindowsPythonHostImagesV1(
        python_executable_sha256=_image_sha256(executable),
        python_runtime_dll_sha256=_image_sha256(runtime_dll),
    )


def verify_windows_lpac_loaded_backend_sources(
    package_members: tuple[tuple[str, str], ...],
) -> None:
    """Match the loaded LPAC source modules to a verified release Wheel."""

    if os.name != "nt":
        raise OSError("Windows LPAC source verification requires Windows")
    if type(package_members) is not tuple or any(
        type(item) is not tuple
        or len(item) != 2
        or type(item[0]) is not str
        or type(item[1]) is not str
        or _DIGEST.fullmatch(item[1]) is None
        for item in package_members
    ):
        raise ValueError("Windows LPAC release members are invalid")
    member_map = dict(package_members)
    if len(member_map) != len(package_members):
        raise ValueError("Windows LPAC release members repeat")
    package_root = Path(__file__).parent.parent
    api = _CtypesWin32Api()
    for name in WINDOWS_LPAC_BACKEND_CODE_MEMBERS:
        expected = member_map.get(name)
        if expected is None:
            raise ValueError("Windows LPAC backend module is absent from release")
        relative = name.removeprefix("loushang/")
        module_name = name.removesuffix(".py").replace("/", ".")
        spec = find_spec(module_name)
        source_path = package_root.joinpath(*relative.split("/"))
        if (
            spec is None
            or spec.origin is None
            or not os.path.samestat(source_path.lstat(), Path(spec.origin).lstat())
            or _image_sha256(source_path, _api=api) != expected
        ):
            raise OSError("Windows LPAC backend source changed")


def verify_windows_loushang_installed_package_members(
    package_members: tuple[tuple[str, str], ...],
) -> None:
    """Match every retained Wheel package member to the running installation."""

    if os.name != "nt":
        raise OSError("Windows package verification requires Windows")
    if (
        type(package_members) is not tuple
        or not 1 <= len(package_members) <= _MAX_PACKAGE_MEMBERS
    ):
        raise ValueError("Windows release member count is invalid")
    package_root = Path(__file__).parent.parent
    seen: set[str] = set()
    total = 0
    members: list[tuple[Path, str]] = []
    for item in package_members:
        if type(item) is not tuple or len(item) != 2:
            raise ValueError("Windows release member is invalid")
        name, expected = item
        if (
            type(name) is not str
            or not name.startswith("loushang/")
            or "\\" in name
            or ":" in name
            or name in seen
            or type(expected) is not str
            or _DIGEST.fullmatch(expected) is None
        ):
            raise ValueError("Windows release member is invalid")
        relative_parts = name.removeprefix("loushang/").split("/")
        if any(part in {"", ".", ".."} for part in relative_parts):
            raise ValueError("Windows release member path is invalid")
        seen.add(name)
        path = package_root.joinpath(*relative_parts)
        total += path.lstat().st_size
        if total > _MAX_PACKAGE_BYTES:
            raise OSError("Windows installed Loushang release changed")
        members.append((path, expected))
    if not set(WINDOWS_LPAC_BACKEND_CODE_MEMBERS) <= seen:
        raise ValueError("Windows LPAC source closure is incomplete")

    # Each member is still read from a locked handle and checked before/after
    # hashing. Bound the number of simultaneous Windows file and ADS queries;
    # do not retain a verification result across separate Product reads.
    worker_state = threading.local()

    def digest(path: Path) -> str:
        api = getattr(worker_state, "api", None)
        if api is None:
            api = _CtypesWin32Api()
            worker_state.api = api
        return _image_sha256(path, _api=api)

    with ThreadPoolExecutor(max_workers=_PACKAGE_VERIFY_WORKERS) as executor:
        for offset in range(0, len(members), _PACKAGE_VERIFY_WORKERS):
            batch = members[offset : offset + _PACKAGE_VERIFY_WORKERS]
            futures = tuple(executor.submit(digest, path) for path, _ in batch)
            for (_, expected), future in zip(batch, futures, strict=True):
                if future.result() != expected:
                    raise OSError("Windows installed Loushang release changed")


def _loaded_python_runtime_dll_path() -> Path:
    import ctypes
    from ctypes import wintypes

    module_handle = getattr(sys, "dllhandle", None)
    if type(module_handle) is not int or module_handle <= 0:
        raise OSError("The loaded Windows Python runtime DLL is unavailable")
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    get_path = kernel32.GetModuleFileNameW
    get_path.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    get_path.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_path(wintypes.HMODULE(module_handle), buffer, len(buffer))
    if length <= 0 or length >= len(buffer) - 1:
        raise OSError("The loaded Windows Python runtime DLL path is unavailable")
    path = Path(buffer.value)
    if not path.is_absolute() or path.suffix.lower() != ".dll":
        raise OSError("The loaded Windows Python runtime DLL path is invalid")
    return path


def _image_sha256(path: Path, *, _api: _CtypesWin32Api | None = None) -> str:
    if os.name != "nt" or not path.is_absolute():
        raise OSError("Windows Python image path is not absolute")
    import msvcrt

    api = _api or _CtypesWin32Api()
    owned: list[int] = []
    try:
        handle = api.open_locked_file(str(path), on_acquired=owned.append)
        identity = api.locked_path_identity(handle)
        if (
            identity.size <= 0
            or identity.size > _MAX_IMAGE_BYTES
            or api.file_stream_names(str(path)) != ("::$DATA",)
        ):
            raise OSError("Windows Python image is unsafe")
        descriptor = getattr(msvcrt, "open_osfhandle")(
            handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
        )
        owned.clear()
        try:
            before = os.fstat(descriptor)
            if before.st_size != identity.size or not os.path.samestat(
                before, path.lstat()
            ):
                raise OSError("Windows Python image is unsafe")
            digest = sha256()
            total = 0
            while block := os.read(descriptor, _CHUNK):
                total += len(block)
                if total > _MAX_IMAGE_BYTES:
                    raise OSError("Windows Python image exceeds its bound")
                digest.update(block)
            after = os.fstat(descriptor)
            if (
                total != before.st_size
                or not os.path.samestat(before, after)
                or not os.path.samestat(after, path.lstat())
                or api.locked_path_identity(handle) != identity
                or api.file_stream_names(str(path)) != ("::$DATA",)
            ):
                raise OSError("Windows Python image changed during capture")
            return digest.hexdigest()
        finally:
            os.close(descriptor)
    finally:
        for handle in owned:
            api.close_handle(handle)


__all__ = [
    "WINDOWS_LPAC_BACKEND_CODE_MEMBERS",
    "WINDOWS_LPAC_PLATFORM_IMPORTS",
    "WindowsBackendMaterialExpectationV1",
    "WindowsPythonHostImagesV1",
    "capture_windows_python_host_images",
    "verify_windows_loushang_installed_package_members",
    "verify_windows_lpac_loaded_backend_sources",
    "verify_windows_backend_material_expectation",
]
