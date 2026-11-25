from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "macos_packager", Path(__file__).resolve().parents[2] / "scripts/build/build_full_macos.py",
)
assert SPEC is not None and SPEC.loader is not None
packager = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(Path(SPEC.origin).parent))
try:
    SPEC.loader.exec_module(packager)
finally:
    sys.path.pop(0)


@pytest.mark.parametrize(
    ("architectures", "minimum", "dependency", "error"),
    [
        ("arm64", "12.0", "@rpath/libpython.dylib", "Required x86_64 slice missing"),
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
            return (f"cmd LC_BUILD_VERSION\n cmdsize 32\n minos {minimum}\n sdk 15.0\n"
                    "cmd LC_ID_DYLIB\n cmdsize 152\n name /build/python/libpython.dylib (offset 24)")
        return ("program:\n\t/build/python/libpython.dylib (compatibility version 1.0.0, current version 1.0.0)\n"
                f"\t{dependency} (compatibility version 1.0.0, current version 1.0.0)")

    monkeypatch.setattr(packager, "run", run)
    if error:
        with pytest.raises(RuntimeError, match=error):
            packager.audit_native(tmp_path)
    else:
        report = packager.audit_native(tmp_path)
        assert report[0]["minimumVersions"] == ["12.0"]
