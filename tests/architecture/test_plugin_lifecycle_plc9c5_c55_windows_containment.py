from __future__ import annotations

import ast
import json
from pathlib import Path

DOCUMENT = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c55-windows-containment.md"
)
BASELINE = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-c50-baseline.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c50-inventory.md"
)
INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
DELIVERY_PLAN = Path(
    "docs/internals/architecture/drafts/hosted-product-runtime-v1-plan.md"
)
SOURCE_ROOT = Path("src/loushang")
HOSTING_ROOT = SOURCE_ROOT / "hosting"
WORKER_ROOT = SOURCE_ROOT / "harness" / "worker"
BRIDGE = WORKER_ROOT / "_native_profile_bridge.py"
WINDOWS_PREPARATION = HOSTING_ROOT / "_windows_launch_preparation.py"
LEGACY_APPCONTAINER = (
    SOURCE_ROOT / "harness" / "sandbox" / "package_windows_legacy_runtime.py"
)
MAKEFILE = Path("Makefile")
HOSTING_WORKFLOW = Path(".github/workflows/hosting-quality.yml")
MANIFEST = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-evidence-manifest.json"
)

_PLANNED_PROFILE = "windows-lpac-contained-pe-v1"
_C55B_CASES = {
    "C55B-PROFILE-CREATE",
    "C55B-CLEANUP-REPLAY",
    "C55B-FOREIGN-PROFILE-REJECT",
    "C55B-PROFILE-SID",
    "C55B-ZERO-CAPABILITIES",
    "C55B-LPAC-OPTOUT",
    "C55B-RUNTIME-RX",
    "C55B-RUNTIME-WRITE-DENY",
    "C55B-PRIVATE-FS-SCRATCH",
    "C55B-REGISTRY-DENY",
    "C55B-UNRELATED-FS-DENY",
    "C55B-PROCESS-MUTATION-DENY",
    "C55B-NETWORK-DENY",
    "C55B-EXEC-CWD-IDENTITY",
    "C55B-DACL-SUBSTITUTION",
    "C55B-PROFILE-SUBSTITUTION",
    "C55B-NO-AMBIENT-ENV",
    "C55B-HANDLE-LIST",
    "C55B-HANDLE-ALIAS-REJECT",
    "C55B-CANCEL-PRE-POST-EFFECT",
    "C55B-TOKEN-VERIFY-BEFORE-RESUME",
    "C55B-JOB-TREE-CLEANUP",
    "C55B-CONTAINMENT-CLEANUP-DEBT",
    "C55B-SENTINEL-REDACTION",
}
_C55C_CASES = {
    "C55C-PRODUCT-SELECTED",
    "C55C-PRODUCT-MISSING",
    "C55C-PRODUCT-WRONG",
    "C55C-PRODUCT-DISABLED",
    "C55C-SESSION-CANONICAL",
    "C55C-SESSION-CWD",
    "C55C-SESSION-HOME",
    "C55C-SESSION-TAMPERED",
    "C55C-SESSION-ALIAS",
    "C55C-SESSION-CONFLICT",
    "C55C-SESSION-CHANGED",
    "C55C-REQUIRED-SUCCESS",
    "C55C-REQUIRED-FAILURE",
    "C55C-OPTIONAL-SUCCESS",
    "C55C-OPTIONAL-DEGRADED",
    "C55C-POLICY-CLOSURE-FRESHNESS",
    "C55C-PROVISIONING-FRESHNESS",
    "C55C-HANDSHAKE-HEALTH-PUBLICATION",
    "C55C-WINDOWS-AMD64-ACCEPT",
    "C55C-UNSUPPORTED-WINDOWS-NON-AMD64",
    "C55C-UNSUPPORTED-WSL",
    "C55C-UNSUPPORTED-MACOS",
    "C55C-ORDERED-ROLLBACK",
    "C55C-RECOVERY-MATRIX",
    "C55C-NATIVE-CONTAINMENT-SETTLEMENT",
    "C55C-SHARED-ENTRYPOINT-RECEIPT",
    "C55C-NO-FALLBACK",
    "C55C-SENTINEL-REDACTION",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_c55a_status_index_and_parent_plan_are_honest() -> None:
    document = " ".join(_read(DOCUMENT).split())
    baseline = " ".join(_read(BASELINE).split())
    inventory = " ".join(_read(INVENTORY).split())
    delivery = " ".join(_read(DELIVERY_PLAN).split())
    for token in (
        "ID: `PLC9C5-C5.5-WINDOWS-CONTAINMENT`",
        "Authority: normative accepted design",
        "Design status: accepted",
        "Implementation status: implemented candidate through C5.5b native mechanics; C5.5c Product composition is not implemented",
        "Activation status: closed",
        "Production default: Current",
        "C5.5 closes G7 only after both the Windows native containment report",
        "It does not join AppHost; that remains G8",
        "It does not delete Current",
    ):
        assert token in document
    assert (
        _read(INDEX).count("(plugin-lifecycle-plc9c5-c55-windows-containment.md)") == 1
    )
    for slice_id in ("C5.5a", "C5.5b", "C5.5c"):
        assert slice_id in document
        assert slice_id in baseline
        assert slice_id in delivery
    assert "merged C5.5a design baseline `68151253`" in inventory
    assert "implemented C5.5b candidate grants no activation authority" in inventory


def test_c55a_freezes_the_threat_model_and_resource_lifetimes() -> None:
    document = " ".join(_read(DOCUMENT).split())
    for token in (
        "malicious or compromised Worker executable running under the same interactive user",
        "zero-capability Less-Privileged AppContainer",
        "opts out of ambient All Application Packages access",
        "no network capability",
        "unrelated same-user filesystem sentinel or obtain",
        "immutable Package material from attempt resources",
        "one attempt only",
        "fresh LPAC profile per attempt",
        "A host crash closes the Job",
        "profile, private state, and DACL may remain",
        "native containment cleanup has revoked the grant",
        "`native_containment_settled`",
        "Existing V1 Current/Linux records migrate losslessly",
        "no unresolved high or medium issue",
    ):
        assert token in document


def test_c55a_keeps_sole_writers_and_dependency_direction_explicit() -> None:
    document = " ".join(_read(DOCUMENT).split())
    for token in (
        "Product policy + selected immutable Worker revision",
        "pathless Product Worker activation receipt",
        "Product/Package/Sandbox durable provisioning authority",
        "Hosting-private LPAC profile + exact grant receipt",
        "sole Harness `_native_profile_bridge.py`",
        "Hosting continues to import no Harness",
        "Coding imports no Hosting module",
        "a second friend module is forbidden",
        "PLC9B's `package_windows_legacy_runtime.py` is evidence and a semantic precedent, not a reusable dependency",
    ):
        assert token in document


def test_c55b_keeps_runtime_private_until_product_report_exists() -> None:
    # C5.5b adds only Hosting-private mechanics. Harness and Product remain
    # unable to construct or select the candidate profile.
    production = "\n".join(
        _read(path) for path in SOURCE_ROOT.rglob("*.py") if path != LEGACY_APPCONTAINER
    )
    assert _PLANNED_PROFILE in production
    bridge = _read(BRIDGE)
    assert "_WindowsLpac" not in bridge
    assert "_build_windows_lpac" not in bridge
    assert "loushang.hosting._windows_launch_preparation" not in _imports(BRIDGE)
    assert "_WindowsLpacProvisioner" in _read(WINDOWS_PREPARATION)
    outside_hosting = "\n".join(
        _read(path)
        for path in SOURCE_ROOT.rglob("*.py")
        if HOSTING_ROOT not in path.parents and path != LEGACY_APPCONTAINER
    )
    assert _PLANNED_PROFILE not in outside_hosting
    assert "_WindowsLpacProvisioner" not in outside_hosting
    assert "windows-restricted-direct-import-pe-v1" in production


def test_c55a_requires_in_child_native_authority_and_lifecycle_evidence() -> None:
    document = " ".join(_read(DOCUMENT).split())
    for token in (
        "negative authorities from inside the child",
        "Source inspection, token flags alone",
        "profile create, cleanup-only exact replay, foreign pre-existing profile rejection",
        "zero capabilities, exact Package SID, LPAC opt-out",
        "runtime write denial, profile-private filesystem scratch-only write, registry denial",
        "network denial plus a local network sentinel",
        "exact endpoint/stderr handle list",
        "cancellation before and after effect",
        "same-boot uncertainty, changed-boot absence",
        "native-containment cleanup/debt",
        "separate native and Product XML files",
        "zero-skip/zero-failure/zero-error",
    ):
        assert token in document


def test_c55b_implements_native_and_keeps_product_report_planned() -> None:
    reports = json.loads(_read(MANIFEST))["reports"]
    native = reports["PLC9C5-C5.5B-WINDOWS-LPAC-NATIVE"]
    product = reports["PLC9C5-C5.5C-WINDOWS-PRODUCT"]
    assert native == {
        "junitPath": ".artifacts/plc9c5-c55b-windows-lpac-native.xml",
        "minimumTests": 24,
        "requiredCaseIds": list(native["requiredCaseIds"]),
        "status": "implemented",
    }
    assert set(native["requiredCaseIds"]) == _C55B_CASES
    assert len(native["requiredCaseIds"]) == len(_C55B_CASES)
    assert product == {
        "junitPath": ".artifacts/plc9c5-c55c-windows-product.xml",
        "minimumTests": 28,
        "requiredCaseIds": list(product["requiredCaseIds"]),
        "status": "planned",
    }
    assert set(product["requiredCaseIds"]) == _C55C_CASES
    assert len(product["requiredCaseIds"]) == len(_C55C_CASES)


def test_c55a_has_a_focused_local_architecture_gate() -> None:
    makefile = _read(MAKEFILE)
    workflow = _read(HOSTING_WORKFLOW)
    assert "check-plc9c5-c55-windows-containment-design" in makefile
    assert "check-plc9c5-c55b-windows-lpac-native" in makefile
    for token in (
        "LOUSHANG_PLC9C5_C55B_REPORT",
        "tests/hosting/test_plc9c5_c55b_windows_lpac_native.py",
        ".artifacts/plc9c5-c55b-windows-lpac-native.xml",
        "PLC9C5-C5.5B-WINDOWS-LPAC-NATIVE",
        "verify_pytest_xml.py",
        "verify_plc9c5_manifest.py",
    ):
        assert token in makefile
        assert token in workflow
    assert (
        "tests/architecture/test_plugin_lifecycle_plc9c5_c55_windows_containment.py"
    ) in makefile
