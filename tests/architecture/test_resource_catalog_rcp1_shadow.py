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
RCP1_MODULES = {
    RESOURCE_ROOT / "_catalog_engine.py",
    RESOURCE_ROOT / "_catalog_records.py",
    RESOURCE_ROOT / "_catalog_shadow.py",
}


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


def test_rcp1_catalog_remains_private_and_unmounted() -> None:
    assert all(path.is_file() for path in RCP1_MODULES)
    production_paths = set(Path("src/loushang").rglob("*.py")) - RCP1_MODULES

    assert not {path for path in production_paths if _imports_catalog_module(path)}
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
