from __future__ import annotations

import ctypes as C
import os
import subprocess
from ctypes import wintypes as W
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordError,
    LocalRecordErrorCodeV1,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol import SessionScopeV1

pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires native Windows security handles")


def test_G16_PRIVATE_RECORD_windows_native_abi_and_handle_admission(tmp_path):
    from loushang.appserver._windows_local_record import (
        _Ace,
        _Attributes,
        _FileId,
        _FileInfo,
        _WindowsRecordFiles,
    )

    assert C.sizeof(_Ace) == 8
    assert C.sizeof(_FileInfo) == 52
    assert C.sizeof(_FileId) == 24
    assert C.sizeof(_Attributes) == (24 if C.sizeof(C.c_void_p) == 8 else 12)
    files = _WindowsRecordFiles(tmp_path / "runtime")
    try:
        files.prepare(create=True)
        descriptor = files.open("probe", "new")
        identity = files.identity(descriptor)
        assert identity == files.named_identity("probe")
        files.close_descriptor(descriptor)
        files.remove("probe", identity)
    finally:
        files.close()


def _publish(lease):
    return lease.publish(application_id="application", product_id="coding", port=12345,
                         scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),))


def _set_dacl(path, api, kind):
    """Install actual insecure native ACLs; do not mock the admission check."""
    descriptor = C.c_void_p()
    dacl = C.c_void_p()
    present, defaulted = W.BOOL(), W.BOOL()
    try:
        if kind != "null":
            trustees = sorted({api.user_sid, "S-1-5-18"})
            sddl = "D:P" + "".join(f"(A;;FA;;;{sid})" for sid in trustees)
            if kind == "world":
                sddl += "(A;;FR;;;WD)"
            assert api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, C.byref(descriptor), None
            )
            assert api.security.GetSecurityDescriptorDacl(
                descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted)
            )
            assert present.value and dacl.value
        function = api.security.SetNamedSecurityInfoW
        function.argtypes = [W.LPWSTR, C.c_int, W.DWORD] + [C.c_void_p] * 4
        function.restype = W.DWORD
        assert function(str(path), 1, 0x80000004, None, None, dacl, None) == 0
    finally:
        if descriptor.value is not None:
            assert not api.kernel.LocalFree(descriptor)


@pytest.mark.parametrize("target", ["root", "record", "lock"])
@pytest.mark.parametrize("kind", ["world", "null"])
def test_G16_PRIVATE_RECORD_windows_rejects_permissive_or_null_dacl_before_read(tmp_path, monkeypatch, target, kind):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    _publish(lease)
    name = sha256(b"workspace").hexdigest()
    path = root if target == "root" else root / (name + (".json" if target == "record" else ".lock"))
    api = directory._files.api
    _set_dacl(path, api, kind)
    reader = LocalConnectionDirectoryV1(root)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "read", lambda *_: pytest.fail("read credentials behind insecure DACL"))
            with pytest.raises(LocalRecordError) as error:
                if target == "lock":
                    reader.acquire("workspace")
                else:
                    reader.read("workspace")
        assert error.value.code is LocalRecordErrorCodeV1.UNAVAILABLE
    finally:
        _set_dacl(path, api, "private")
        reader.close()
        directory.close()


def test_G16_PRIVATE_RECORD_windows_root_junction_is_not_followed(tmp_path):
    root, target = tmp_path / "runtime", tmp_path / "target"
    directory = LocalConnectionDirectoryV1(root)
    other = LocalConnectionDirectoryV1(target)
    _publish(other.acquire("workspace"))
    other.close()
    command = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    subprocess.run([str(command), "/d", "/c", "mklink", "/J", str(root), str(target)],
                   check=True, capture_output=True, timeout=10)
    try:
        with pytest.raises(LocalRecordError) as error:
            directory.acquire("workspace")
        assert error.value.code is LocalRecordErrorCodeV1.UNAVAILABLE
    finally:
        directory.close()
        root.rmdir()
    assert target.is_dir()


def test_G16_PRIVATE_RECORD_windows_failed_crt_transfer_keeps_native_cleanup_owner(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    lease = directory.acquire("workspace")
    files = directory._files
    original = files.api.crt.open_osfhandle

    def failed_transfer(handle, flags):
        if flags & os.O_RDWR:
            raise OSError("injected CRT adoption failure")
        return original(handle, flags)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(files.api.crt, "open_osfhandle", failed_transfer)
            with pytest.raises(LocalRecordError):
                _publish(lease)
            assert len(files._unconverted) == 1
        lease.close()
        assert files._unconverted == {}
        assert list(root.glob("*.tmp")) == []
    finally:
        directory.close()


def test_G16_PRIVATE_RECORD_windows_failed_probe_close_keeps_native_handle(tmp_path, monkeypatch):
    directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
    directory.acquire("workspace")
    files = directory._files
    api = files.api
    before = set(api._handles)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(api.kernel, "CloseHandle", lambda _: 0)
            with pytest.raises(OSError):
                files.check_root()
            assert len(api._handles - before) == 1
        directory.close()
        assert api._handles == set()
    finally:
        directory.close()
