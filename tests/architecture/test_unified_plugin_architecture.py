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
EXPECTED_MANIFEST_BOUNDARY_SINK_SITES = {
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
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "_pypi_latest_version_result",
    ),
}
EXPECTED_GRAPH_PRIVATE_MUTATION_SITES = {
    (
        Path("src/loushang/harness/capabilities/graph_runtime.py"),
        "RuntimeCapabilityGraphRuntime.__init__",
    ),
    (
        Path("src/loushang/harness/capabilities/graph_binding.py"),
        "RuntimeCapabilityGraphBinder.bind",
    ),
    (
        Path("src/loushang/harness/capabilities/graph_binding.py"),
        "RuntimeCapabilityGraphBinder.dispose",
    ),
    (
        Path("src/loushang/harness/capabilities/graph_binding.py"),
        "_publish_registration_inventory",
    ),
}
EXPECTED_EXTENSION_DECLARATION_METHODS = {
    "on",
    "register_tool",
    "register_policy",
    "register_approval",
    "register_command",
    "register_flag",
    "register_shortcut",
    "register_message_renderer",
}
EXPECTED_EXTENSION_LIVE_SINK_INVENTORY = {
    (
        Path("src/loushang/harness/extensions/api.py"),
        "ExtensionContributionAPI._register_runtime_tool",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/api.py"),
        "ExtensionContributionAPI._register_runtime_tool",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/extensions/api.py"),
        "ExtensionContributionAPI.register_tool",
        "_register_runtime_tool",
    ),
    (
        Path("src/loushang/harness/extensions/loader.py"),
        "_adapt_legacy_extension_object",
        "on",
    ),
    (
        Path("src/loushang/harness/extensions/loader.py"),
        "_adapt_legacy_extension_object",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runner.py"),
        "ExtensionRunner._bind_declared_tools",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runner.py"),
        "ExtensionRunner._bindings_for_activation",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runner.py"),
        "ExtensionRunner._supports_staged_activation",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runtime_bindings.py"),
        "ExtensionRuntimeBindingFactory.build",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runtime_bindings.py"),
        "ExtensionRuntimeBindingFactory.build",
        "register_tool",
    ),
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


class _QualifiedFunctionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: list[
            tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]
        ] = []

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
        qualified = ".".join((*self.scope, node.name))
        self.functions.append((qualified, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _qualified_functions(
    source: str,
    *,
    filename: Path,
) -> tuple[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef], ...]:
    visitor = _QualifiedFunctionVisitor()
    visitor.visit(ast.parse(source, filename=str(filename)))
    return tuple(visitor.functions)


def _import_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    json_modules = {"json"}
    json_decoders: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"json", "orjson"}:
                    json_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module in {"json", "orjson"}:
            for alias in node.names:
                if alias.name in {"load", "loads"}:
                    json_decoders.add(alias.asname or alias.name)
    return json_modules, json_decoders


def _manifest_boundary_sink_sites(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if not any(path.is_relative_to(root) for root in PLUGIN_PACKAGE_BOUNDARY_ROOTS):
            continue
        tree = ast.parse(source, filename=str(path))
        json_modules, json_decoders = _import_aliases(tree)
        for qualified, function in _qualified_functions(source, filename=path):
            calls = tuple(
                node for node in ast.walk(function) if isinstance(node, ast.Call)
            )
            reads_file = any(
                (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr in {"read_text", "read_bytes", "open"}
                )
                or (
                    isinstance(call.func, ast.Name)
                    and call.func.id in {"open", "read_text", "read_bytes"}
                )
                for call in calls
            )
            parses_json = any(
                (
                    isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in json_modules
                    and call.func.attr in {"load", "loads"}
                )
                or (
                    isinstance(call.func, ast.Name)
                    and call.func.id in json_decoders
                )
                for call in calls
            )
            if reads_file or parses_json:
                sites.add((path, qualified))
    return sites


def _contains_sensitive_attribute(node: ast.AST, attributes: frozenset[str]) -> bool:
    return any(
        isinstance(child, ast.Attribute) and child.attr in attributes
        for child in ast.walk(node)
    )


def _function_mutates_private_graph_state(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    attributes: frozenset[str],
) -> bool:
    mutation_methods = {
        "__setitem__",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "remove",
        "setdefault",
        "update",
    }
    for node in ast.walk(function):
        targets: tuple[ast.AST, ...] = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        elif isinstance(node, ast.AugAssign):
            targets = (node.target,)
        elif isinstance(node, (ast.Delete,)):
            targets = tuple(node.targets)
        if any(_contains_sensitive_attribute(target, attributes) for target in targets):
            return True
        if not isinstance(node, ast.Call):
            continue
        if (
            (
                isinstance(node.func, ast.Name)
                and node.func.id in {"setattr", "delattr"}
            )
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"__setattr__", "__delattr__"}
            )
        ) and any(
            isinstance(argument, ast.Constant) and argument.value in attributes
            for argument in node.args[1:2]
        ):
            return True
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in mutation_methods
            and _contains_sensitive_attribute(node.func.value, attributes)
        ):
            return True
    return False


def _graph_private_mutation_sites(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str]]:
    attributes = frozenset(
        {"_generation", "_nodes", "_snapshot", "_registration_inventory"}
    )
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if "harness/capabilities/graph_" not in path.as_posix():
            continue
        if not any(attribute in source for attribute in attributes):
            continue
        for qualified, function in _qualified_functions(source, filename=path):
            if _function_mutates_private_graph_state(function, attributes):
                sites.add((path, qualified))
    return sites


def _class_method_names(source: str, class_name: str) -> set[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (child.name == "on" or child.name.startswith("register_"))
            }
    raise AssertionError(f"missing class: {class_name}")


def _extension_live_sink_inventory(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str, str]]:
    tokens = frozenset(
        {
            *EXPECTED_EXTENSION_DECLARATION_METHODS,
            "_register_runtime_tool",
            "bind_approval",
            "bind_command",
            "bind_event",
            "bind_flag",
            "bind_handler",
            "bind_message_renderer",
            "bind_policy",
            "bind_shortcut",
            "bind_tool",
        }
    )
    inventory: set[tuple[Path, str, str]] = set()
    for path, source in sources.items():
        if "harness/extensions/" not in path.as_posix():
            continue
        if not any(token in source for token in tokens):
            continue
        for qualified, function in _qualified_functions(source, filename=path):
            for node in ast.walk(function):
                token: str | None = None
                if isinstance(node, ast.Attribute) and node.attr in tokens:
                    token = node.attr
                elif (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value in tokens
                ):
                    token = node.value
                if token is not None:
                    inventory.add((path, qualified, token))
    return inventory


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
    assert "PluginApprovalDecisionRecord" in architecture
    assert "consume_execution_decision(subject, decision_id)" in architecture
    assert "Revocation linearizes against consumption" in architecture
    assert "security-relevant configuration fingerprint" in architecture


def test_top_level_capability_provider_selection_is_not_a_profile_slot() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "ProductCapabilityProviderResolver" in architecture
    assert "CapabilityProviderEligibilityGrant" in architecture
    assert "CapabilityProviderBindingSpec" in architecture
    assert "one owner-eligible CapabilityBundleProvider metadata value" in architecture
    assert "A top-level Capability ID such\nas `coding.lsp` is never used" in architecture
    assert "Runtime Profile candidate for coding.lsp" not in architecture
    assert "Top-level Provider facts remain\nseparate data" in architecture
    assert "never carries a\n`ResolvedCapabilityProviderSet`" in architecture


def test_owner_admission_agent_event_and_disable_contracts_are_explicit() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "OwnerContributionAdmissionRecord" in architecture
    assert "never labels a contribution\n`admitted`" in architecture
    assert "`agent_definition`" in architecture
    assert "Product Agent Host" in architecture
    assert "EventDefinitionCatalog" in architecture
    assert "`durable_fact` after domain commit" in architecture
    assert "A durable interceptor/reducer/first-match declaration is invalid" in (
        architecture
    )
    assert "Agent fields have one authority each" in architecture
    assert "calling a declaration-forming `register_*` after IR freeze" in architecture
    assert "performs no partial recompose and returns `restart_required`" in architecture


def test_revision_retention_and_python_import_realm_are_closed_for_v1() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "owner-generation/cleanup leases" in architecture
    assert "a retryable cleanup failure therefore retains its revision" in architecture
    assert "SessionPluginMembershipLease" in architecture
    assert "AgentPluginMembershipLease" in architecture
    assert "REVOKING" in architecture
    assert "PluginCleanupJournal" in architecture
    assert "changing its package\ndigest is Product-Host `restart_required`" in (
        architecture
    )
    assert "digest-qualified import realm" in architecture
    assert "process-wide import-closure ledger" in architecture
    assert "VerifiedRevisionHandle" in architecture
    assert "data-generation/schema" in architecture


def test_unified_plugin_architecture_preserves_existing_runtime_authorities() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for authority in EXPECTED_AUTHORITY_CLASS_SITES:
        assert authority in architecture
    assert "There is no new Plugin Profile resolver" in architecture
    assert "not one global Plugin\ntransaction" in architecture
    assert "does not create a fifth effective clock" in architecture
    assert "aggregate retirement handles" in architecture
    assert "never becomes the Registration owner" in architecture


def test_current_plugin_manifest_name_sites_are_a_baseline_inventory() -> None:
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


def test_current_package_manifest_boundary_sinks_use_qualified_allowlist() -> None:
    sources = _source_texts()

    assert (
        _manifest_boundary_sink_sites(sources)
        == EXPECTED_MANIFEST_BOUNDARY_SINK_SITES
    )
    synthetic = {
        Path("src/loushang/harness/resources/plugins/read_helper.py"): (
            "def read_text(path):\n"
            "    with path.open() as stream:\n"
            "        return stream.read()\n"
        ),
        Path("src/loushang/harness/resources/plugins/indirect.py"): (
            "from json import loads as decode\n"
            "from names import PLUGIN_MANIFEST\n"
            "from .read_helper import read_text\n"
            "def parse(root):\n"
            "    return decode(read_text(root / PLUGIN_MANIFEST))\n"
        ),
        Path("src/loushang/harness/resources/packages/alias.py"): (
            "import orjson as codec\n"
            "def parse(path):\n"
            "    return codec.loads(path.read_bytes())\n"
        ),
        Path("src/loushang/harness/resources/packages/stream.py"): (
            "from json import load as decode\n"
            "def parse(path):\n"
            "    with path.open() as stream:\n"
            "        return decode(stream)\n"
        ),
    }
    assert _manifest_boundary_sink_sites(synthetic) == {
        (
            Path("src/loushang/harness/resources/plugins/indirect.py"),
            "parse",
        ),
        (
            Path("src/loushang/harness/resources/plugins/read_helper.py"),
            "read_text",
        ),
        (
            Path("src/loushang/harness/resources/packages/alias.py"),
            "parse",
        ),
        (
            Path("src/loushang/harness/resources/packages/stream.py"),
            "parse",
        ),
    }


def test_current_graph_private_mutations_use_qualified_owner_allowlist() -> None:
    sources = _source_texts()

    assert _graph_private_mutation_sites(sources) == EXPECTED_GRAPH_PRIVATE_MUTATION_SITES
    synthetic = {
        Path("src/loushang/harness/capabilities/graph_alias.py"): (
            "def alias_write(graph, candidate):\n"
            "    graph._snapshot = candidate\n"
            "def nested_write(self, nodes):\n"
            "    self._runtime._nodes['new'] = nodes\n"
            "def setattr_write(runtime, candidate):\n"
            "    setattr(runtime, '_snapshot', candidate)\n"
            "def dunder_write(runtime, candidate):\n"
            "    object.__setattr__(runtime, '_snapshot', candidate)\n"
            "def container_write(runtime, nodes):\n"
            "    runtime._nodes.update(nodes)\n"
        )
    }
    assert _graph_private_mutation_sites(synthetic) == {
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "alias_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "nested_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "setattr_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "dunder_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "container_write",
        ),
    }


def test_current_extension_declaration_and_live_sink_inventory_is_frozen() -> None:
    sources = _source_texts()
    api_path = Path("src/loushang/harness/extensions/api.py")

    assert _class_method_names(
        sources[api_path],
        "ExtensionContributionAPI",
    ) == EXPECTED_EXTENSION_DECLARATION_METHODS
    assert (
        _extension_live_sink_inventory(sources)
        == EXPECTED_EXTENSION_LIVE_SINK_INVENTORY
    )
    synthetic = {
        Path("src/loushang/harness/extensions/late.py"): (
            "def direct(bindings, tool):\n"
            "    bindings.bind_tool(tool)\n"
            "def reflected(bindings, tool):\n"
            "    getattr(bindings, 'bind_tool')(tool)\n"
            "def saved(bindings, tool):\n"
            "    binder = bindings.bind_tool\n"
            "    binder(tool)\n"
            "def new_kind(bindings, policy):\n"
            "    bindings.bind_policy(policy)\n"
        )
    }
    assert _extension_live_sink_inventory(synthetic) == {
        (
            Path("src/loushang/harness/extensions/late.py"),
            "direct",
            "bind_tool",
        ),
        (
            Path("src/loushang/harness/extensions/late.py"),
            "reflected",
            "bind_tool",
        ),
        (
            Path("src/loushang/harness/extensions/late.py"),
            "saved",
            "bind_tool",
        ),
        (
            Path("src/loushang/harness/extensions/late.py"),
            "new_kind",
            "bind_policy",
        ),
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
