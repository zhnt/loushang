from __future__ import annotations

from pathlib import Path

from tests.architecture._source_imports import imported_modules

CAPABILITY_ROOT = Path("src/loushang/harness/capabilities")
FOUNDATION_MODULES = {
    CAPABILITY_ROOT / "component_contracts.py",
    CAPABILITY_ROOT / "component_admission.py",
    CAPABILITY_ROOT / "component_selection.py",
    CAPABILITY_ROOT / "component_binding.py",
    CAPABILITY_ROOT / "component_runtime.py",
    CAPABILITY_ROOT / "owner_component_host.py",
}
INTENTIONAL_FOUNDATION_CONSUMERS = {
    Path("src/loushang/coding/continuity_bootstrap.py"),
    Path("src/loushang/harness/continuity/composition.py"),
    Path("src/loushang/harness/continuity/plugin_declaration.py"),
    Path("src/loushang/harness/continuity/plugin_runtime.py"),
    Path("src/loushang/harness/resource_catalog/components.py"),
    Path("src/loushang/harness/resource_catalog/shadow.py"),
}


def _imports_foundation(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if "loushang.harness.capabilities.component_" not in source:
        return False
    return any(
        module.startswith("loushang.harness.capabilities.component_")
        and module not in {"loushang.harness.capabilities.component_host"}
        for module in imported_modules(path, source)
    )


def test_owner_component_foundation_is_private_and_explicitly_mounted() -> None:
    assert all(path.is_file() for path in FOUNDATION_MODULES)
    production_paths = set(Path("src/loushang").rglob("*.py")) - FOUNDATION_MODULES

    assert {
        path for path in production_paths if _imports_foundation(path)
    } == INTENTIONAL_FOUNDATION_CONSUMERS
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
        for module in imported_modules(path)
        if module in forbidden
    }


def test_complete_bundle_component_host_is_not_silently_overloaded() -> None:
    host = (CAPABILITY_ROOT / "component_host.py").read_text(encoding="utf-8")
    owner_host = (CAPABILITY_ROOT / "owner_component_host.py").read_text(
        encoding="utf-8"
    )

    assert "CapabilityOwnerComponent" not in host
    assert "CapabilityBundleProviderBinding" in host
    assert "OwnerComponentActivationApprovalSubject" in owner_host
    assert "ContributionActivationApprovalSubject" not in owner_host
    assert "CapabilityBundleProviderBinding" not in owner_host
