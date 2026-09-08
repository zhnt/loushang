from __future__ import annotations

import json
from pathlib import Path

from tests.coding.test_mux_native_evidence import _CASES


def test_G16_EVIDENCE_exact_platform_case_and_installation_requirements():
    manifest = json.loads(
        Path(
            "docs/internals/architecture/appserver/detachable-local-workspace-g16-evidence-manifest.json"
        ).read_text()
    )
    assert manifest["manifestVersion"] == 1
    reports = manifest["reports"]
    assert set(reports) == {
        f"G16-{kind}-{platform}"
        for kind in ("NATIVE", "WHEEL")
        for platform in ("LINUX", "DARWIN", "WIN32")
    }
    native_cases = [identity for identity, _ in _CASES]
    assert len(native_cases) == len(set(native_cases)) == 29
    for platform in ("linux", "darwin", "win32"):
        native = reports[f"G16-NATIVE-{platform.upper()}"]
        assert native["requiredCaseIds"] == native_cases
        assert native["minimumTests"] == len(native_cases)
        assert native["requiredProperties"] == {"native_platform": platform}
        wheel = reports[f"G16-WHEEL-{platform.upper()}"]
        assert wheel["requiredCaseIds"] == [
            "G16-INSTALLED-ATTACH",
            "G16-INSTALLED-TWO-MUX",
            "G16-INSTALLED-CRASH-CWD",
            "G16-INSTALLED-CRASH-HOME",
        ]
        assert wheel["minimumTests"] == 4
        assert wheel["requiredProperties"] == {
            "native_platform": platform,
            "installation": "wheel",
            "terminal_backend": "conpty" if platform == "win32" else "posix-pty",
        }
        for kind, report in (("native", native), ("wheel", wheel)):
            assert (
                report["status"] == "implemented"
            )  # Test implementation, not a CI pass claim.
            assert report["junitPath"] == f".artifacts/g16-{kind}-{platform}.xml"


def test_G16_EVIDENCE_ci_keeps_native_and_isolated_wheel_gates_required():
    workflow = Path(".github/workflows/appservice-quality.yml").read_text()
    for entry in (
        "g16-native-evidence:",
        "g16-wheel-evidence:",
        "tests/coding/test_mux_native_evidence.py",
        "run_g16_installed_evidence.py",
        "verify_evidence_manifest.py",
        "actions/upload-artifact@v4",
    ):
        assert entry in workflow
    assert "continue-on-error" not in workflow
    script = Path("scripts/dev/run_g16_installed_evidence.py").read_text()
    for invariant in (
        "args.platform != sys.platform",
        '"--offline"',
        '"-I"',
        'f"pythonpath={_ROOT}"',
        '"pythonpath", "pythonhome", "virtual_env"',
        "is_relative_to(prefix)",
        "archive_info",
        "_verify_wheel_source(wheel)",
        "verify_evidence_manifest.py",
    ):
        assert invariant in script
