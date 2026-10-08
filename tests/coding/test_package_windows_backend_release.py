"""Inert release-candidate verification for the Python/Win32 LPAC backend."""

from __future__ import annotations

import csv
import io
import stat
import zipfile
from base64 import urlsafe_b64encode
from hashlib import sha256
from importlib.metadata import version

import pytest

from loushang.coding.package_product_worker_windows_backend_release import (
    inspect_coding_windows_worker_backend_candidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageWheelVerificationError,
)

_MODULES = (
    "loushang/hosting/_win32_process.py",
    "loushang/hosting/_windows_process.py",
    "loushang/hosting/_windows_launch_preparation.py",
    "loushang/hosting/runtime.py",
    "loushang/harness/worker/_native_profile_bridge.py",
    "loushang/harness/worker/product_activation.py",
    "loushang/coding/package_product_worker_windows_provisioning.py",
    "loushang/coding/package_product_worker_windows_provisioning_journal.py",
)


def _backend_wheel(*, omit: str | None = None, corrupt_record: bool = False) -> bytes:
    current_version = version("loushang")
    dist_info = f"loushang-{current_version}.dist-info"
    files = {name: f"# {name}\n".encode() for name in _MODULES if name != omit}
    files[f"{dist_info}/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: backend-release-test\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n\n"
    ).encode()
    files[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: loushang\nVersion: {current_version}\n\n"
    ).encode()
    record = io.StringIO(newline="")
    rows = [
        (
            name,
            "sha256=" + urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode(),
            str(len(body)),
        )
        for name, body in sorted(files.items())
    ]
    rows.append((f"{dist_info}/RECORD", "", ""))
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    if corrupt_record:
        files[_MODULES[0]] += b"changed"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            item = zipfile.ZipInfo(name)
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | 0o644) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, body)
    return output.getvalue()


def test_backend_candidate_binds_wheel_and_python_images_without_approval() -> None:
    wheel = _backend_wheel()
    candidate = inspect_coding_windows_worker_backend_candidate(
        loushang_wheel=wheel,
        python_executable_sha256="a" * 64,
        python_runtime_dll_sha256="b" * 64,
    )
    assert len(candidate.package_members) == len(_MODULES)
    assert candidate.approval.wheel_sha256 == sha256(wheel).hexdigest()
    changed_image = inspect_coding_windows_worker_backend_candidate(
        loushang_wheel=wheel,
        python_executable_sha256="c" * 64,
        python_runtime_dll_sha256="b" * 64,
    )
    assert changed_image.approval.catalog_sha256 != candidate.approval.catalog_sha256
    assert changed_image.approval.launcher_sha256 != candidate.approval.launcher_sha256
    assert changed_image.approval.profile_sha256 == candidate.approval.profile_sha256


def test_backend_candidate_refuses_missing_code_and_changed_record() -> None:
    with pytest.raises(ValueError, match="members are incomplete"):
        inspect_coding_windows_worker_backend_candidate(
            loushang_wheel=_backend_wheel(omit=_MODULES[0]),
            python_executable_sha256="a" * 64,
            python_runtime_dll_sha256="b" * 64,
        )
    with pytest.raises(PackageWheelVerificationError):
        inspect_coding_windows_worker_backend_candidate(
            loushang_wheel=_backend_wheel(corrupt_record=True),
            python_executable_sha256="a" * 64,
            python_runtime_dll_sha256="b" * 64,
        )
