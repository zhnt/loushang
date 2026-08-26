from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from loushang.harness.resources._catalog_records import (
    ResourceCandidateSummary,
    ResourceCatalogSnapshot,
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
)

RESOURCE_ROOT = Path("src/loushang/harness/resources")
ORCHESTRATION_ROOT = Path("src/loushang/harness/resource_catalog")
CAPABILITY_ROOT = Path("src/loushang/harness/capabilities")
EXTENSION_ROOT = Path("src/loushang/harness/extensions")
RCP1_MODULES = {
    RESOURCE_ROOT / "_catalog_engine.py",
    RESOURCE_ROOT / "_catalog_records.py",
    RESOURCE_ROOT / "_catalog_shadow.py",
}
RCP2_MODULES = {
    RESOURCE_ROOT / "_catalog_native_source.py",
    ORCHESTRATION_ROOT / "components.py",
    ORCHESTRATION_ROOT / "shadow.py",
}
RCP3_MODULES = {
    RESOURCE_ROOT / "_catalog_embedded_source.py",
    RESOURCE_ROOT / "_catalog_package_source.py",
    RESOURCE_ROOT / "_catalog_source_contracts.py",
    ORCHESTRATION_ROOT / "inputs.py",
}
RCP4_MODULES = {
    RESOURCE_ROOT / "_catalog_input_receipt.py",
    RESOURCE_ROOT / "_catalog_extension_source.py",
    RESOURCE_ROOT / "_catalog_projection.py",
    ORCHESTRATION_ROOT / "generation.py",
    ORCHESTRATION_ROOT / "joint_generation.py",
    ORCHESTRATION_ROOT / "product_inputs.py",
    ORCHESTRATION_ROOT / "session_bootstrap.py",
    CAPABILITY_ROOT / "resources_consumers.py",
    EXTENSION_ROOT / "resources.py",
}
PRIVATE_CATALOG_MODULES = RCP1_MODULES | RCP2_MODULES | RCP3_MODULES | RCP4_MODULES


def _imports_catalog_module(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("loushang.harness.resources._catalog_")
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name.startswith("loushang.harness.resources._catalog_")
            for alias in node.names
        ):
            return True
    return False


def test_rcp1_records_match_the_frozen_field_contracts() -> None:
    assert tuple(field.name for field in fields(ResourceSourceGenerationRef)) == (
        "source_id",
        "product_id",
        "generation",
        "source_policy_fingerprint",
        "producer",
    )
    assert tuple(field.name for field in fields(ResourceSourceSnapshot)) == (
        "source_generation_ref",
        "discovery_request_fingerprint",
        "candidate_summaries",
        "diagnostics",
        "complete",
        "snapshot_fingerprint",
    )
    assert tuple(field.name for field in fields(ResourceCandidateSummary)) == (
        "identity",
        "canonical_name",
        "description",
        "media_type",
        "invocation_policy",
        "source_generation_ref",
        "source_class",
        "scope_id",
        "source_root_order",
        "content_origin",
        "opaque_locator",
        "discovery_fingerprint",
        "candidate_fingerprint",
        "expected_content_digest",
        "expected_content_length",
        "diagnostics",
    )
    assert tuple(field.name for field in fields(ResourceCatalogSnapshot)) == (
        "catalog_contract_version",
        "catalog_generation",
        "engine_binding_fingerprint",
        "source_generation_fingerprints",
        "merge_policy_revision",
        "activation_policy_fingerprint",
        "candidate_summaries",
        "effective_entries",
        "merge_decisions",
        "diagnostics",
        "complete",
        "snapshot_fingerprint",
    )


def test_resource_catalog_internals_remain_confined_to_migration_modules() -> None:
    assert all(path.is_file() for path in PRIVATE_CATALOG_MODULES)
    production_paths = set(Path("src/loushang").rglob("*.py")) - PRIVATE_CATALOG_MODULES

    assert {path for path in production_paths if _imports_catalog_module(path)} == {
        Path("src/loushang/coding/_resource_catalog_shadow.py"),
        RESOURCE_ROOT / "_loader_pipeline.py",
        RESOURCE_ROOT / "loader.py",
    }
    assert "_catalog" not in (RESOURCE_ROOT / "__init__.py").read_text(encoding="utf-8")


def test_rcp1_engine_has_no_ambient_loader_or_io_imports() -> None:
    engine_path = RESOURCE_ROOT / "_catalog_engine.py"
    tree = ast.parse(engine_path.read_text(encoding="utf-8"), filename=str(engine_path))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not imported_modules & {
        "asyncio",
        "os",
        "pathlib",
        "subprocess",
        "loushang.harness.resources.loader",
        "loushang.harness.resources._loader_pipeline",
        "loushang.harness.resources._loader_discovery",
    }
