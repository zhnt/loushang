from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "macos_packager", Path(__file__).resolve().parents[2] / "scripts/gui/build_macos_full.py",
)
assert SPEC is not None and SPEC.loader is not None
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


@pytest.mark.parametrize(
    ("architectures", "minimum", "dependency", "error"),
    [
        ("arm64", "12.0", "@rpath/libpython.dylib", "Intel slice missing"),
        ("x86_64", "13.0", "@rpath/libpython.dylib", "Requires newer macOS"),
        ("x86_64", "12.0", "/usr/local/opt/python/libpython.dylib", "Unbundled native dependency"),
        ("x86_64 arm64", "12.0", "/usr/lib/libSystem.B.dylib", None),
    ],
)
def test_native_payload_audit_rejects_wrong_arch_os_and_external_dependencies(
    tmp_path, monkeypatch, architectures, minimum, dependency, error,
):
    (tmp_path / "program").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 32)

    def run(command, *args):
        if command.endswith("lipo"):
            return architectures
        if "-l" in args:
            return f"cmd LC_BUILD_VERSION\n cmdsize 32\n minos {minimum}\n sdk 15.0"
        return f"program:\n\t{dependency} (compatibility version 1.0.0, current version 1.0.0)"

    monkeypatch.setattr(packager, "run", run)
    if error:
        with pytest.raises(RuntimeError, match=error):
            packager.audit_native(tmp_path)
    else:
        report = packager.audit_native(tmp_path)
        assert report[0]["minimumVersions"] == ["12.0"]
