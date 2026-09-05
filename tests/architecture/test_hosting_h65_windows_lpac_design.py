from __future__ import annotations

import ast
from pathlib import Path

DOCUMENT = Path(
    "docs/internals/architecture/hosting/"
    "managed-launch-preparation-h65-windows-lpac.md"
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


def test_h65_design_status_and_product_boundary_are_honest() -> None:
    document = " ".join(_read(DOCUMENT).split())
    c55 = " ".join(_read(C55).split())
    for token in (
        "ID: `HOST-H6.5-WINDOWS-LPAC`",
        "Authority: normative accepted design",
        "Design status: accepted",
        "Implementation status: not implemented",
        "Native activation: none",
        "Runtime posture: default-dark",
        "does not know Product, Plugin, Worker, Sandbox policy",
        "distinct `windows-lpac-contained-pe-v1` profile",
    ):
        assert token in document
    assert "HOST-H6.5-WINDOWS-LPAC" in c55
    assert _read(INDEX).count("(managed-launch-preparation-h65-windows-lpac.md)") == 1
    h6 = " ".join(_read(H6).split())
    assert "H6.5 Windows LPAC design is accepted but not implemented" in h6
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
        "rooted, no-follow, bounded filesystem removal",
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


def test_h65a_has_no_runtime_symbols_or_new_cross_package_dependency() -> None:
    production_without_legacy = "\n".join(
        _read(path) for path in SOURCE_ROOT.rglob("*.py") if path != LEGACY
    )
    assert _PROFILE not in production_without_legacy
    assert "_WindowsLpac" not in production_without_legacy
    hosting_imports = {
        imported
        for path in HOSTING_ROOT.rglob("*.py")
        for imported in _imports(path)
    }
    assert not any(
        imported.startswith("loushang.harness") for imported in hosting_imports
    )
