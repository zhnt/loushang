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
EXPECTED_PLUGIN_JSON_STATIC_SITES = {
    Path("src/loushang/harness/resources/packages/manifest.py"),
    Path("src/loushang/harness/resources/plugins/resolver.py"),
}
PLUGIN_PACKAGE_BOUNDARY_ROOTS = (
    Path("src/loushang/harness/resources/plugins"),
    Path("src/loushang/harness/resources/packages"),
)
EXPECTED_JSON_FILE_READER_FUNCTION_SITES = {
    (
        Path("src/loushang/harness/resources/plugins/resolver.py"),
        "PluginResolver._read_manifest",
    ),
    (
        Path("src/loushang/harness/resources/packages/manifest.py"),
        "resolve_package_manifest",
    ),
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "PackageMaterializer.load_trusted_sources",
    ),
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "PackageMaterializer._load_lockfile",
    ),
    (
        Path("src/loushang/harness/resources/packages/catalog.py"),
        "load_package_catalog",
    ),
}
EXPECTED_GRAPH_RUNTIME_EXTERNAL_WRITE_SITES = {
    Path("src/loushang/harness/capabilities/graph_binding.py"),
}
EXPECTED_EXTENSION_LIVE_DECLARATION_MUTATION_SITES = {
    Path("src/loushang/harness/extensions/api.py"),
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


def _static_string_value(
    node: ast.AST,
    bindings: Mapping[str, str],
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string_value(node.left, bindings)
        right = _static_string_value(node.right, bindings)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        values = tuple(_static_string_value(value, bindings) for value in node.values)
        return None if any(value is None for value in values) else "".join(values)
    if isinstance(node, ast.FormattedValue):
        return _static_string_value(node.value, bindings)
    return None


def _static_string_bindings(tree: ast.Module) -> dict[str, str]:
    bindings: dict[str, str] = {}
    pending = [node for node in tree.body if isinstance(node, ast.Assign)]
    changed = True
    while changed:
        changed = False
        for assignment in pending:
            value = _static_string_value(assignment.value, bindings)
            if value is None:
                continue
            for target in assignment.targets:
                if isinstance(target, ast.Name) and bindings.get(target.id) != value:
                    bindings[target.id] = value
                    changed = True
    return bindings


def _static_string_sites(sources: Mapping[Path, str], value: str) -> set[Path]:
    sites: set[Path] = set()
    fragments = tuple(fragment for fragment in value.split(".") if fragment)
    for path, source in sources.items():
        if any(fragment not in source for fragment in fragments):
            continue
        tree = ast.parse(source, filename=str(path))
        bindings = _static_string_bindings(tree)
        if any(
            _static_string_value(node, bindings) == value for node in ast.walk(tree)
        ):
            sites.add(path)
    return sites


def _external_attribute_write_sites(
    sources: Mapping[Path, str],
    *,
    receiver: str,
    attributes: frozenset[str],
) -> set[Path]:
    sites: set[Path] = set()
    for path, source in sources.items():
        if not any(f"{receiver}.{attribute}" in source for attribute in attributes):
            continue
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            targets: tuple[ast.AST, ...] = ()
            if isinstance(node, ast.Assign):
                targets = tuple(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = (node.target,)
            elif isinstance(node, ast.AugAssign):
                targets = (node.target,)
            if any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == receiver
                and target.attr in attributes
                for target in targets
            ):
                sites.add(path)
    return sites


def _attribute_call_sites(
    sources: Mapping[Path, str],
    attributes: frozenset[str],
) -> set[Path]:
    return {
        path
        for path, source in sources.items()
        if any(f".{attribute}(" in source for attribute in attributes)
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in attributes
            for node in ast.walk(ast.parse(source, filename=str(path)))
        )
    }


def _is_json_file_reader(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    calls = tuple(child for child in ast.walk(node) if isinstance(child, ast.Call))
    reads_file = any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr in {"read_text", "read_bytes"}
        for call in calls
    )
    parses_json = any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "json"
        and call.func.attr in {"load", "loads"}
        for call in calls
    )
    return reads_file and parses_json


class _JsonFileReaderVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        if _is_json_file_reader(node):
            self.functions.add(".".join((*self.scope, node.name)))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _json_file_reader_function_sites(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if not any(path.is_relative_to(root) for root in PLUGIN_PACKAGE_BOUNDARY_ROOTS):
            continue
        if "json." not in source or ".read_" not in source:
            continue
        visitor = _JsonFileReaderVisitor()
        visitor.visit(ast.parse(source, filename=str(path)))
        sites.update((path, function) for function in visitor.functions)
    return sites


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
    assert "installed != enabled != preflight-approved != declared != requested" in (
        architecture
    )


def test_unified_plugin_architecture_defines_the_four_phase_pipeline() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for phase in (
        "Resolve once",
        "Preflight, then declare once",
        "Bind once",
        "Project once",
    ):
        assert phase in architecture


def test_executable_declaration_is_gated_by_inert_preflight() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert architecture.index("Plugin Preflight Decision") < architecture.index(
        "Plugin Definition"
    )
    assert "Only a digest-bound package with a positive preflight decision" in (
        architecture
    )
    assert "are never imported and never launched" in architecture
    assert "PluginExecutionApprovalSubject" in architecture
    assert "ContributionActivationApprovalSubject" in architecture
    assert "security-relevant configuration fingerprint" in architecture


def test_top_level_capability_provider_selection_is_not_a_profile_slot() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "ProductCapabilityProviderResolver" in architecture
    assert "CapabilityProviderBindingSpec" in architecture
    assert "one CapabilityBundleProvider metadata value per Capability" in architecture
    assert "A top-level Capability ID such\nas `coding.lsp` is never used" in architecture
    assert "Runtime Profile candidate for coding.lsp" not in architecture


def test_owner_admission_agent_event_and_disable_contracts_are_explicit() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "OwnerContributionAdmissionRecord" in architecture
    assert "never labels a contribution `admitted`" in architecture
    assert "`agent_definition`" in architecture
    assert "Product Agent Host" in architecture
    assert "EventDefinitionCatalog" in architecture
    assert "awaited serial broadcast" in architecture
    assert "calling a declaration-forming `register_*` after IR freeze" in architecture
    assert "performs no partial recompose and returns `restart_required`" in architecture


def test_revision_retention_and_python_import_realm_are_closed_for_v1() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "owner-generation/cleanup leases" in architecture
    assert "a retryable cleanup failure therefore retains its revision" in architecture
    assert "changing its package\ndigest is Product-Host `restart_required`" in (
        architecture
    )
    assert "digest-qualified import realm" in architecture


def test_unified_plugin_architecture_preserves_existing_runtime_authorities() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for authority in EXPECTED_AUTHORITY_CLASS_SITES:
        assert authority in architecture
    assert "There is no new Plugin Profile resolver" in architecture
    assert "not one global Plugin\ntransaction" in architecture
    assert "does not create a fifth effective clock" in architecture
    assert "aggregate retirement handles" in architecture
    assert "never becomes the Registration owner" in architecture


def test_current_plugin_manifest_reader_baseline_detects_static_aliases() -> None:
    sources = _source_texts()

    assert _static_string_sites(sources, "plugin.json") == EXPECTED_PLUGIN_JSON_STATIC_SITES
    synthetic = {
        Path("third_parser.py"): (
            'PREFIX = "plugin."\n'
            'MANIFEST = f"{PREFIX}json"\n'
            "payload = (root / MANIFEST).read_text()\n"
        )
    }
    assert _static_string_sites(synthetic, "plugin.json") == {
        Path("third_parser.py")
    }


def test_current_package_json_reader_sinks_reject_an_indirect_parser() -> None:
    sources = _source_texts()

    assert (
        _json_file_reader_function_sites(sources)
        == EXPECTED_JSON_FILE_READER_FUNCTION_SITES
    )
    synthetic = {
        Path("src/loushang/harness/resources/plugins/indirect.py"): (
            "from names import PLUGIN_MANIFEST\n"
            "def parse(root):\n"
            "    return json.loads((root / PLUGIN_MANIFEST).read_text())\n"
        )
    }
    assert _json_file_reader_function_sites(synthetic) == {
        (
            Path("src/loushang/harness/resources/plugins/indirect.py"),
            "parse",
        )
    }


def test_current_graph_publication_baseline_rejects_external_runtime_writes() -> None:
    sources = _source_texts()
    graph_state = frozenset({"_nodes", "_snapshot", "_registration_inventory"})

    assert _external_attribute_write_sites(
        sources,
        receiver="runtime",
        attributes=graph_state,
    ) == EXPECTED_GRAPH_RUNTIME_EXTERNAL_WRITE_SITES
    synthetic = {Path("second_publisher.py"): "runtime._snapshot = candidate\n"}
    assert _external_attribute_write_sites(
        synthetic,
        receiver="runtime",
        attributes=graph_state,
    ) == {Path("second_publisher.py")}


def test_current_extension_live_declaration_mutation_baseline_is_frozen() -> None:
    sources = _source_texts()
    mutation_methods = frozenset({"_register_runtime_tool"})

    assert _attribute_call_sites(
        sources,
        mutation_methods,
    ) == EXPECTED_EXTENSION_LIVE_DECLARATION_MUTATION_SITES
    synthetic = {Path("late_plugin.py"): "api._register_runtime_tool(tool)\n"}
    assert _attribute_call_sites(synthetic, mutation_methods) == {
        Path("late_plugin.py")
    }


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
