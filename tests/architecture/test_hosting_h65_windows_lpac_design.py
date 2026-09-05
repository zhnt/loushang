from __future__ import annotations

import ast
from pathlib import Path

DOCUMENT = Path(
    "docs/internals/architecture/hosting/managed-launch-preparation-h65-windows-lpac.md"
)
C55 = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c55-windows-containment.md"
)
INDEX = Path("docs/internals/architecture/hosting/README.md")
H6 = Path("docs/internals/architecture/hosting/managed-launch-preparation-h6.md")
HOSTING_ROOT = Path("src/loushang/hosting")
SOURCE_ROOT = Path("src/loushang")
LEGACY = Path("src/loushang/harness/sandbox/package_windows_legacy_runtime.py")
WINDOWS_PREPARATION = HOSTING_ROOT / "_windows_launch_preparation.py"
WINDOWS_RAW = HOSTING_ROOT / "_win32_process.py"
WINDOWS_PROCESS = HOSTING_ROOT / "_windows_process.py"

_PROFILE = "windows-lpac-contained-pe-v1"


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


def _method_source(path: Path, class_name: str, method_name: str) -> str:
    source = _read(path)
    tree = ast.parse(source, filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == method_name:
                    segment = ast.get_source_segment(source, member)
                    assert segment is not None
                    return segment
    raise AssertionError(f"missing {class_name}.{method_name}")


def test_h65_design_status_and_product_boundary_are_honest() -> None:
    document = " ".join(_read(DOCUMENT).split())
    c55 = " ".join(_read(C55).split())
    for token in (
        "ID: `HOST-H6.5-WINDOWS-LPAC`",
        "Authority: normative accepted design",
        "Design status: accepted",
        "Implementation status: implemented candidate through H6.5b native mechanics; H6.5c Product composition is not implemented",
        "Native activation: mandatory Windows AMD64 evidence gate only; no Product consumer",
        "Runtime posture: default-dark",
        "does not know Product, Plugin, Worker, Sandbox policy",
        "distinct `windows-lpac-contained-pe-v1` profile",
    ):
        assert token in document
    assert "HOST-H6.5-WINDOWS-LPAC" in c55
    assert _read(INDEX).count("(managed-launch-preparation-h65-windows-lpac.md)") == 1
    h6 = " ".join(_read(H6).split())
    assert (
        "H6.5b Windows LPAC native mechanics are an implemented default-dark "
        "candidate with no Product consumer"
    ) in h6
    assert "H6.5a" in h6 and "H6.5b" in h6
    assert "No unresolved high or medium design issue remains" in document


def test_h65_design_uses_a_dedicated_runtime_closure_and_rooted_scratch() -> None:
    document = " ".join(_read(DOCUMENT).split())
    for token in (
        "dedicated immutable Worker runtime closure, not a Plugin package root",
        "containing only the exact admitted executable",
        "No manifest, credential, other contribution, user file",
        "read, execute, and traverse rights only",
        "complete attempt-specific AppContainer profile is the only writable",
        "rooted, no-follow, bounded removal of its exact `Temp` scratch subtree",
        "`DeleteAppContainerProfile` is the sole owner",
        "Cleanup ambiguity or residue blocks a successor",
    ):
        assert token in document


def test_h65_design_freezes_durable_provisioning_and_recovery() -> None:
    document = " ".join(_read(DOCUMENT).split())
    for state in (
        "ABSENT",
        "RESERVED",
        "PROFILE_CREATED",
        "GRANTS_APPLIED",
        "VERIFIED",
        "ACTIVE",
        "CLEANING",
        "GRANTS_REVOKED",
        "PROFILE_DELETED",
        "SETTLED",
        "DEBT",
    ):
        assert state in document
    for token in (
        "caller remains the durable transaction owner",
        "persist each transition by CAS",
        "possibly effectful",
        "cannot be adopted",
        "Repeated exact cleanup is idempotent",
        "two Product or host processes",
        "Process-tree settlement and containment settlement are distinct",
        "cannot prove that the DACL grant",
    ):
        assert token in document


def test_h65_design_requires_atomic_lpac_job_and_handle_composition() -> None:
    document = " ".join(_read(DOCUMENT).split())
    for token in (
        "PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES",
        "PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY",
        "PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT",
        "PROC_THREAD_ATTRIBUTE_JOB_LIST",
        "PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
        "process is created suspended",
        "before the thread can execute",
        "zero capabilities",
        "No inherited environment is permitted",
    ):
        assert token in document


def test_h65_design_requires_real_in_child_negative_authority_evidence() -> None:
    document = " ".join(_read(DOCUMENT).split())
    for token in (
        "purpose-built no-CRT child",
        "proves from inside that child",
        "runtime closure is readable/executable but not writable",
        "same-user process cannot be opened with mutation, VM, or handle-duplication rights",
        "parent-created loopback listener is reachable by an unrestricted control process",
        "complete tree is gone before settlement",
        "fails the required CI job rather than skipping it",
    ):
        assert token in document


def test_h65b_runtime_symbols_are_hosting_private_without_cross_package_dependency() -> (
    None
):
    production_without_legacy = "\n".join(
        _read(path) for path in SOURCE_ROOT.rglob("*.py") if path != LEGACY
    )
    assert _PROFILE in production_without_legacy
    assert "_WindowsLpacProvisioner" in production_without_legacy
    outside_hosting = "\n".join(
        _read(path)
        for path in SOURCE_ROOT.rglob("*.py")
        if HOSTING_ROOT not in path.parents and path != LEGACY
    )
    assert _PROFILE not in outside_hosting
    assert "_WindowsLpacProvisioner" not in outside_hosting
    hosting_imports = {
        imported for path in HOSTING_ROOT.rglob("*.py") for imported in _imports(path)
    }
    assert not any(
        imported.startswith("loushang.harness") for imported in hosting_imports
    )


def test_h65b_implements_exact_atomic_launch_and_cleanup_only_recovery() -> None:
    raw_attributes = _method_source(
        WINDOWS_RAW,
        "_CtypesWin32Api",
        "_lpac_attribute_list",
    )
    for attribute in (
        "_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES",
        "_PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY",
        "_PROC_THREAD_ATTRIBUTE_JOB_LIST",
        "_PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
    ):
        assert raw_attributes.count(attribute) == 1
    assert "None, 4, 0" in raw_attributes
    assert "pointer,\n            4,\n            0" in raw_attributes
    assert "CapabilityCount = 0" in raw_attributes
    assert "_PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT" in raw_attributes

    raw_spawn = _method_source(WINDOWS_RAW, "_CtypesWin32Api", "spawn_lpac")
    assert "_CreateProcessW" in raw_spawn
    assert "_CreateProcessAsUserW" not in raw_spawn
    assert "_CREATE_SUSPENDED" in raw_spawn
    assert raw_spawn.index("lpac_process_identity") < raw_spawn.index("_ResumeThread")

    provisioner = _read(WINDOWS_PREPARATION)
    assert "def recover_cleanup_witness(" in provisioner
    assert 'state="DEBT"' in provisioner
    assert "only creates a DEBT witness accepted by exact revoke/delete" in provisioner
    process = _read(WINDOWS_PROCESS)
    assert "def _spawn_lpac_prepared(" in process
    assert "spawn_lpac(" in process
