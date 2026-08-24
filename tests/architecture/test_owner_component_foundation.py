from __future__ import annotations

import ast
from pathlib import Path

CAPABILITY_ROOT = Path("src/loushang/harness/capabilities")
FOUNDATION_MODULES = {
    CAPABILITY_ROOT / "component_contracts.py",
    CAPABILITY_ROOT / "component_admission.py",
    CAPABILITY_ROOT / "component_selection.py",
    CAPABILITY_ROOT / "component_binding.py",
    CAPABILITY_ROOT / "component_runtime.py",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def _imports_foundation(path: Path) -> bool:
    return any(
        module.startswith("loushang.harness.capabilities.component_")
        and module
        not in {"loushang.harness.capabilities.component_host"}
        for module in _imported_modules(path)
    )


def test_owner_component_foundation_is_unpublished_and_unmounted() -> None:
    assert all(path.is_file() for path in FOUNDATION_MODULES)
    production_paths = set(Path("src/loushang").rglob("*.py")) - FOUNDATION_MODULES

    assert not {path for path in production_paths if _imports_foundation(path)}
    public_surface = (CAPABILITY_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "CapabilityComponentDefinition" not in public_surface
    assert "CapabilityOwnerComponentRuntime" not in public_surface


def test_owner_component_foundation_does_not_create_another_graph_or_registry() -> None:
    forbidden = {
        "loushang.harness.capabilities.graph_binding",
        "loushang.harness.capabilities.graph_planning",
        "loushang.harness.capabilities.graph_runtime",
        "loushang.harness.runtime.registry",
        "loushang.harness.resources.loader",
        "loushang.harness.resources._loader_pipeline",
    }

    assert not {
        (path, module)
        for path in FOUNDATION_MODULES
        for module in _imported_modules(path)
        if module in forbidden
    }


def test_complete_bundle_component_host_is_not_silently_overloaded() -> None:
    host = (CAPABILITY_ROOT / "component_host.py").read_text(encoding="utf-8")

    assert "CapabilityOwnerComponent" not in host
    assert "CapabilityBundleProviderBinding" in host
