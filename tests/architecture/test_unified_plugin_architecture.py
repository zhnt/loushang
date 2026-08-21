from __future__ import annotations

import ast
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import get_args

from loushang.harness.runtime import RuntimeCapabilityScope

ARCHITECTURE_PATH = Path(
    "docs/internals/architecture/harness/unified-plugin-architecture.md"
)
README_PATH = Path("docs/internals/architecture/harness/README.md")
SOURCE_ROOT = Path("src/loushang")
EXPECTED_PLUGIN_JSON_LITERAL_SITES = {
    Path("src/loushang/harness/resources/packages/manifest.py"),
    Path("src/loushang/harness/resources/plugins/resolver.py"),
}
EXPECTED_AUTHORITY_CLASS_SITES = {
    "RuntimeProfileResolver": Path(
        "src/loushang/harness/runtime/_profile_resolution.py"
    ),
    "RuntimeCapabilityGraphBinder": Path(
        "src/loushang/harness/capabilities/graph_binding.py"
    ),
    "RuntimeCapabilityGraphProjector": Path(
        "src/loushang/harness/capabilities/graph_projection.py"
    ),
}


@cache
def _source_texts() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in SOURCE_ROOT.rglob("*.py")
    }


def _literal_sites(sources: Mapping[Path, str], value: str) -> set[Path]:
    return {
        path
        for path, source in sources.items()
        if value in source
        if any(
            isinstance(node, ast.Constant) and node.value == value
            for node in ast.walk(ast.parse(source, filename=str(path)))
        )
    }


def _class_sites(
    sources: Mapping[Path, str], class_name: str
) -> tuple[Path, ...]:
    return tuple(
        path
        for path, source in sources.items()
        if f"class {class_name}" in source
        if any(
            isinstance(node, ast.ClassDef) and node.name == class_name
            for node in ast.walk(ast.parse(source, filename=str(path)))
        )
    )


def test_unified_plugin_architecture_document_is_indexed() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "unified-plugin-architecture.md" in readme
    assert "one manifest parser" in architecture
    assert "Plugin identity is not a Capability Graph node" in architecture
    assert "installed != enabled != selected != admitted != mounted" in architecture


def test_unified_plugin_architecture_defines_the_four_phase_pipeline() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for phase in (
        "Resolve once",
        "Declare once",
        "Bind once",
        "Project once",
    ):
        assert phase in architecture


def test_unified_plugin_architecture_preserves_existing_runtime_authorities() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for authority in EXPECTED_AUTHORITY_CLASS_SITES:
        assert authority in architecture
    assert "There is no new Plugin Profile resolver" in architecture
    assert "not one global Plugin\ntransaction" in architecture
    assert "does not create a fifth effective clock" in architecture
    assert "aggregate retirement handles" in architecture
    assert "never becomes the Registration owner" in architecture


def test_current_plugin_manifest_reader_baseline_rejects_a_third_path() -> None:
    sources = _source_texts()

    assert _literal_sites(sources, "plugin.json") == EXPECTED_PLUGIN_JSON_LITERAL_SITES
    synthetic = {Path("third_parser.py"): 'MANIFEST = "plugin.json"'}
    assert _literal_sites(synthetic, "plugin.json") == {Path("third_parser.py")}


def test_current_profile_graph_authority_classes_have_one_definition() -> None:
    sources = _source_texts()

    for class_name, expected_path in EXPECTED_AUTHORITY_CLASS_SITES.items():
        assert _class_sites(sources, class_name) == (expected_path,)
    assert _class_sites(sources, "EffectivePluginRuntimeProjector") == ()
    assert _class_sites(sources, "PluginProfileResolver") == ()


def test_plugin_scope_contract_preserves_current_runtime_scope_vocabulary() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    expected = {"process", "tenant", "workspace", "session", "turn", "channel"}

    assert set(get_args(RuntimeCapabilityScope)) == expected
    for scope in expected:
        assert scope in architecture
    assert "Agent is a composition membership boundary" in architecture


def test_unified_plugin_architecture_preserves_exact_registration_ownership() -> None:
    registration_source = Path(
        "src/loushang/harness/runtime/registration.py"
    ).read_text(encoding="utf-8")
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "if lease.owner != self._owner:" in registration_source
    assert "one lease never belongs to two scopes" in architecture
    assert "Root Plugin scope capturing foreign leases" in architecture


def test_unified_plugin_architecture_keeps_complete_model_input_authority() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "complete Tool definitions and schemas" in architecture
    assert "fingerprints are supplementary provenance only" in architecture
    assert "never reopens the current\nPlugin package" in architecture


def test_unified_plugin_architecture_keeps_product_kernel_outside_plugins() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "Coding Product Kernel" in architecture
    assert "coding.base" in architecture
    assert "must remain\nusable when every optional Plugin is disabled" in architecture
    assert "mandatory system prompt" in architecture
