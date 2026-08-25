from __future__ import annotations

import ast
from pathlib import Path

from loushang.harness.resource_catalog.components import (
    RESOURCE_CATALOG_ENGINE_COMPONENT_KIND,
    RESOURCE_CATALOG_ENGINE_DEFINITION,
    RESOURCE_SOURCE_COMPONENT_KIND,
    RESOURCE_SOURCE_DEFINITION,
)

RESOURCE_ROOT = Path("src/loushang/harness/resources")
ORCHESTRATION_ROOT = Path("src/loushang/harness/resource_catalog")
COMPONENTS_PATH = ORCHESTRATION_ROOT / "components.py"
NATIVE_SOURCE_PATH = RESOURCE_ROOT / "_catalog_native_source.py"
SHADOW_RUNNER_PATH = ORCHESTRATION_ROOT / "shadow.py"
PREPARED_GENERATION_PATH = ORCHESTRATION_ROOT / "generation.py"
JOINT_GENERATION_PATH = ORCHESTRATION_ROOT / "joint_generation.py"
SESSION_BOOTSTRAP_PATH = ORCHESTRATION_ROOT / "session_bootstrap.py"
AGENT_PRODUCT_SESSION_PATH = Path("src/loushang/harness/session/agent_product.py")
EXTENSION_RESOURCE_SOURCE_PATH = RESOURCE_ROOT / "_catalog_extension_source.py"
EXTENSION_RESOURCE_RUNTIME_PATH = Path("src/loushang/harness/extensions/resources.py")


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


def test_rcp2_first_party_definitions_are_owned_narrow_component_seams() -> None:
    assert RESOURCE_CATALOG_ENGINE_COMPONENT_KIND == "resource.catalog_engine"
    assert RESOURCE_SOURCE_COMPONENT_KIND == "resource.source"
    assert RESOURCE_CATALOG_ENGINE_DEFINITION.capability_id == "harness.resources"
    assert RESOURCE_SOURCE_DEFINITION.capability_id == "harness.resources"
    assert RESOURCE_CATALOG_ENGINE_DEFINITION.owner_id == "harness"
    assert RESOURCE_SOURCE_DEFINITION.owner_id == "harness"
    assert RESOURCE_CATALOG_ENGINE_DEFINITION.compatible_bundle_contract.minimum == 1
    assert RESOURCE_CATALOG_ENGINE_DEFINITION.compatible_bundle_contract.maximum == 2
    assert RESOURCE_SOURCE_DEFINITION.compatible_bundle_contract.minimum == 1
    assert RESOURCE_SOURCE_DEFINITION.compatible_bundle_contract.maximum == 2
    assert RESOURCE_CATALOG_ENGINE_DEFINITION.service_references == ()
    assert RESOURCE_SOURCE_DEFINITION.service_references == ()


def test_rcp2_native_source_has_no_loader_resolution_plugin_network_or_mcp_route() -> (
    None
):
    imports = _imported_modules(NATIVE_SOURCE_PATH)

    assert not imports & {
        "httpx",
        "requests",
        "socket",
        "urllib",
        "loushang.harness.capabilities.graph",
        "loushang.harness.resources.loader",
        "loushang.harness.resources._loader_discovery",
        "loushang.harness.resources._loader_discovery_context",
        "loushang.harness.resources._loader_discovery_filesystem",
        "loushang.harness.resources._loader_pipeline",
        "loushang.harness.resources._loader_resolution",
        "loushang.harness.resources.plugins.manager",
        "loushang.harness.resources.plugins.registry",
    }
    assert all("mcp" not in name.lower() for name in imports)


def test_rcp2_replaceable_payloads_do_not_create_graph_registry_or_nested_host() -> (
    None
):
    payload_imports = _imported_modules(COMPONENTS_PATH) | _imported_modules(
        NATIVE_SOURCE_PATH
    )

    assert not {
        name
        for name in payload_imports
        if name.endswith("component_host")
        or name.endswith("component_runtime")
        or ".graph" in name
        or name.endswith(".registry")
    }
    assert "loushang.harness.capabilities.component_runtime" in _imported_modules(
        SHADOW_RUNNER_PATH
    )


def test_rcp2_catalog_engine_component_has_no_ambient_io_dependency() -> None:
    imports = _imported_modules(COMPONENTS_PATH)

    assert not imports & {
        "os",
        "pathlib",
        "subprocess",
        "time",
        "loushang.harness.resources.loader",
        "loushang.harness.resources._loader_pipeline",
    }


def test_rcp2_shadow_runner_is_private_and_has_no_production_importer() -> None:
    private_paths = {
        COMPONENTS_PATH,
        NATIVE_SOURCE_PATH,
        SHADOW_RUNNER_PATH,
        PREPARED_GENERATION_PATH,
        JOINT_GENERATION_PATH,
        SESSION_BOOTSTRAP_PATH,
        RESOURCE_ROOT / "_catalog_engine.py",
        RESOURCE_ROOT / "_catalog_records.py",
        RESOURCE_ROOT / "_catalog_shadow.py",
    }
    production_paths = set(Path("src/loushang").rglob("*.py")) - private_paths

    forbidden_importers = set()
    for path in production_paths:
        allowed = (
            {"loushang.harness.resource_catalog.session_bootstrap"}
            if path == AGENT_PRODUCT_SESSION_PATH
            else set()
        )
        restricted = {
            imported
            for imported in _imported_modules(path)
            if imported.startswith("loushang.harness.resource_catalog")
            or imported == "loushang.harness.resources._catalog_native_source"
        }
        if restricted - allowed:
            forbidden_importers.add(path)
    assert not forbidden_importers
    assert "_catalog" not in (RESOURCE_ROOT / "__init__.py").read_text(encoding="utf-8")


def test_rcp4_prepared_generation_is_the_only_shadow_to_provider_bridge() -> None:
    production_paths = set(Path("src/loushang").rglob("*.py")) - {
        PREPARED_GENERATION_PATH,
    }

    assert PREPARED_GENERATION_PATH.is_file()
    assert not {
        path
        for path in production_paths
        if "loushang.harness.resource_catalog.shadow" in _imported_modules(path)
    }


def test_rcp4_extension_snapshot_has_one_non_publishing_runtime_bridge() -> None:
    production_paths = set(Path("src/loushang").rglob("*.py")) - {
        EXTENSION_RESOURCE_SOURCE_PATH,
        EXTENSION_RESOURCE_RUNTIME_PATH,
    }

    assert EXTENSION_RESOURCE_SOURCE_PATH.is_file()
    assert EXTENSION_RESOURCE_RUNTIME_PATH.is_file()
    assert "loushang.harness.resources._catalog_extension_source" in _imported_modules(
        EXTENSION_RESOURCE_RUNTIME_PATH
    )
    assert not {
        path
        for path in production_paths
        if (
            "loushang.harness.resources._catalog_extension_source"
            in _imported_modules(path)
        )
    }
    runtime_source = EXTENSION_RESOURCE_RUNTIME_PATH.read_text(encoding="utf-8")
    assert "prepare_catalog_inputs_async" in runtime_source
    assert "_defensive_bundle" in runtime_source


def test_rcp4_joint_generation_has_one_private_session_bootstrap_adapter() -> None:
    production_paths = set(Path("src/loushang").rglob("*.py")) - {
        JOINT_GENERATION_PATH,
        SESSION_BOOTSTRAP_PATH,
    }

    assert JOINT_GENERATION_PATH.is_file()
    assert not {
        path
        for path in production_paths
        if "loushang.harness.resource_catalog.joint_generation"
        in _imported_modules(path)
    }
    assert "loushang.harness.resource_catalog.joint_generation" in _imported_modules(
        SESSION_BOOTSTRAP_PATH
    )
    session_bootstrap_importers = {
        path
        for path in production_paths
        if "loushang.harness.resource_catalog.session_bootstrap"
        in _imported_modules(path)
    }
    assert session_bootstrap_importers == {AGENT_PRODUCT_SESSION_PATH}
    imports = _imported_modules(JOINT_GENERATION_PATH)
    assert "loushang.harness.extensions.runner" not in imports
    assert not {
        name
        for name in imports
        if name.startswith("loushang.harness.session") or "mcp" in name.lower()
    }
    source = JOINT_GENERATION_PATH.read_text(encoding="utf-8")
    assert "JointResourcePublication" in source
    assert "prepare_extension_resource_joint_generation" in source
