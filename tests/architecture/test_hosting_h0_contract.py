from __future__ import annotations

import ast
import sys
from pathlib import Path

HOSTING_ROOT = Path("src/loushang/hosting")
H0_PUBLIC_MODULES = {
    HOSTING_ROOT / "__init__.py",
    HOSTING_ROOT / "contracts.py",
    HOSTING_ROOT / "errors.py",
}
H1_PRIVATE_MODULES = {
    HOSTING_ROOT / "_process_backend.py",
    HOSTING_ROOT / "_process_host.py",
}
FORBIDDEN_PUBLIC_TERMS = {
    "Approval",
    "Authorization",
    "Capability",
    "Plugin",
    "Policy",
    "Sandbox",
    "Worker",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def test_hosting_package_is_standard_library_only_and_product_neutral() -> None:
    modules = H0_PUBLIC_MODULES | H1_PRIVATE_MODULES
    assert {path for path in HOSTING_ROOT.rglob("*.py")} == modules

    for path in modules:
        for imported in _imports(path):
            root = imported.partition(".")[0]
            assert root in sys.stdlib_module_names, (path, imported)


def test_h0_public_surface_exposes_no_platform_or_caller_authority_types() -> None:
    public_surface = (HOSTING_ROOT / "__init__.py").read_text(encoding="utf-8")

    assert all(term not in public_surface for term in FORBIDDEN_PUBLIC_TERMS)
    for forbidden in (
        "ProcessSpawner",
        "PlatformBackend",
        "InheritedHandle",
        "RawHandle",
        "pid",
    ):
        assert forbidden not in public_surface

    assert all(path.name not in public_surface for path in H1_PRIVATE_MODULES)


def test_h0_observation_contract_has_no_arbitrary_payload_or_environment() -> None:
    contracts = (HOSTING_ROOT / "contracts.py").read_text(encoding="utf-8")
    tree = ast.parse(contracts)
    observation = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HostingObservation"
    )
    fields = {
        node.target.id
        for node in observation.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    assert fields == {
        "component",
        "transition",
        "owner_id",
        "session_id",
        "backend_id",
        "failure",
    }
    assert not fields.intersection({"payload", "details", "environment", "message"})


def test_h0_validation_does_not_resolve_ambient_process_state() -> None:
    contracts = (HOSTING_ROOT / "contracts.py").read_text(encoding="utf-8")

    for ambient_operation in (
        "os.environ",
        "os.getcwd",
        ".expanduser(",
        ".resolve(",
        "shlex",
        "subprocess",
    ):
        assert ambient_operation not in contracts
