"""Native evidence for Python images used by the Windows LPAC backend."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_BACKEND_CODE_MEMBERS,
    WindowsBackendMaterialExpectationV1,
    _image_sha256,
    capture_windows_python_host_images,
    verify_windows_backend_material_expectation,
    verify_windows_loushang_installed_package_members,
    verify_windows_lpac_loaded_backend_sources,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")


def test_running_python_images_have_stable_native_digests() -> None:
    first = capture_windows_python_host_images()
    assert capture_windows_python_host_images() == first
    assert re.fullmatch(r"[0-9a-f]{64}", first.python_executable_sha256)
    assert re.fullmatch(r"[0-9a-f]{64}", first.python_runtime_dll_sha256)
    assert first.python_executable_sha256 != first.python_runtime_dll_sha256


def test_image_capture_refuses_named_data_streams(tmp_path: Path) -> None:
    image = tmp_path / "runtime.bin"
    image.write_bytes(b"release-image")
    baseline = _image_sha256(image)
    assert re.fullmatch(r"[0-9a-f]{64}", baseline)
    alternate = Path(str(image) + ":hidden")
    alternate.write_bytes(b"unreviewed")
    try:
        with pytest.raises(OSError, match="unsafe"):
            _image_sha256(image)
    finally:
        alternate.unlink()
    assert _image_sha256(image) == baseline


def test_loaded_lpac_backend_sources_match_selected_release_members() -> None:
    import loushang.hosting

    assert loushang.hosting.__file__ is not None
    package_root = Path(loushang.hosting.__file__).parent.parent
    members = tuple(
        (
            name,
            _image_sha256(
                package_root.joinpath(*name.removeprefix("loushang/").split("/"))
            ),
        )
        for name in WINDOWS_LPAC_BACKEND_CODE_MEMBERS
    )
    verify_windows_lpac_loaded_backend_sources(members)
    verify_windows_loushang_installed_package_members(members)
    images = capture_windows_python_host_images()
    expectation = WindowsBackendMaterialExpectationV1(
        python_executable_sha256=images.python_executable_sha256,
        python_runtime_dll_sha256=images.python_runtime_dll_sha256,
        package_members=members,
    )
    verify_windows_backend_material_expectation(expectation)
    changed_images = WindowsBackendMaterialExpectationV1(
        python_executable_sha256="f" * 64,
        python_runtime_dll_sha256=images.python_runtime_dll_sha256,
        package_members=members,
    )
    with pytest.raises(OSError, match="Python images changed"):
        verify_windows_backend_material_expectation(changed_images)
    changed = ((members[0][0], "f" * 64), *members[1:])
    if changed[0][1] == members[0][1]:
        changed = ((members[0][0], "e" * 64), *members[1:])
    with pytest.raises(OSError, match="source changed"):
        verify_windows_lpac_loaded_backend_sources(changed)
    with pytest.raises(OSError, match="release changed"):
        verify_windows_loushang_installed_package_members(changed)
